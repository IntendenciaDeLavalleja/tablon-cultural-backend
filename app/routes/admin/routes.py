from app.utils.dates import utcnow
from flask import render_template, redirect, url_for, flash, request, session, abort, Response
from flask_login import login_user, login_required, logout_user, current_user
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from datetime import datetime
import csv
import io
import random

from app.extensions import db, limiter, login_manager
from app.models.user import User
from app.models.ticket import Ticket, TicketAttachment, TicketStatus, TicketStatusHistory
from app.models.audit import ActivityLog
from app.models.contact import Contact, EmailLog, ReceivedEmail
from app.forms.auth import LoginForm, TwoFactorForm
from app.forms.admin import UpdateTicketStatusForm, ContactForm, SendEmailForm
from app.services.mail_service import mail_service, auth_service
from app.services.minio_service import minio_service
from app.utils.security import verify_password
from app.utils.logging_helper import log_activity

from . import admin_bp

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@admin_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))

    form = LoginForm()
    
    # Si es GET o el formulario falló (pero no por submit inicial), generamos captcha
    if request.method == 'GET':
        n1, n2 = random.randint(1, 9), random.randint(1, 9)
        session['captcha_question'] = f"{n1} + {n2}"
        session['captcha_answer'] = n1 + n2

    if form.validate_on_submit():
        # Verificar Captcha
        user_captcha = form.captcha.data
        correct_captcha = session.get('captcha_answer')
        
        if not correct_captcha or str(user_captcha) != str(correct_captcha):
            flash('Captcha incorrecto. Intente de nuevo.', 'error')
            # Regenerar para el siguiente intento
            n1, n2 = random.randint(1, 9), random.randint(1, 9)
            session['captcha_question'] = f"{n1} + {n2}"
            session['captcha_answer'] = n1 + n2
            return render_template('admin/login.html', form=form)

        user = User.query.filter_by(email=form.email.data).first()
        
        # Validación de credenciales
        valid_password = False
        if user and user.is_active:
            valid_password = verify_password(user.password_hash, form.password.data)

        if valid_password:
            # NO loguear, generar 2FA y guardar ID en sesión temporal
            try:
                auth_service.generate_and_send_2fa(user, mail_service)
                session['2fa_user_id'] = user.id
                flash('Código de verificación enviado a tu correo.', 'info')
                return redirect(url_for('admin.verify_2fa'))
            except ValueError as e:
                # Rate limit de 2FA
                flash(str(e), 'error')
        else:
            # Mensaje genérico por seguridad (User Enumeration)
            flash('Email o contraseña inválidos', 'error')

    return render_template('admin/login.html', form=form)

@admin_bp.route('/2fa', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def verify_2fa():
    # Verificar que el usuario pasó por el login step 1
    user_id = session.get('2fa_user_id')
    if not user_id:
        return redirect(url_for('admin.login'))

    user = User.query.get(user_id)
    if not user:
        session.pop('2fa_user_id', None)
        return redirect(url_for('admin.login'))

    form = TwoFactorForm()
    if form.validate_on_submit():
        if auth_service.verify_2fa_code(user, form.code.data):
            # Éxito: Login real
            login_user(user)
            
            # Registrar Log de Acceso
            log_activity(
                action='LOGIN',
                details='Inicio de sesión exitoso con 2FA',
                user=user
            )

            session.pop('2fa_user_id', None) # Limpiar sesión temporal
            
            # Actualizar last_login
            user.last_login_at = utcnow()
            db.session.commit()
            
            flash('Sesión iniciada correctamente.', 'success')
            return redirect(url_for('admin.dashboard'))
        else:
            flash('Código inválido o expirado.', 'error')

    return render_template('admin/verify_2fa.html', form=form)

@admin_bp.route('/logout')
@login_required
def logout():
    log_activity(
        action='LOGOUT',
        details='Cierre de sesión manual',
        user=current_user
    )
    logout_user()
    flash('Sesión cerrada.', 'info')
    return redirect(url_for('admin.login'))

@admin_bp.route('/dashboard')
@login_required
def dashboard():
    # Stats counters
    stats = {
        'NEW': Ticket.query.filter_by(status=TicketStatus.NEW).count(),
        'IN_PROGRESS': Ticket.query.filter_by(status=TicketStatus.IN_PROGRESS).count(),
        'RESOLVED': Ticket.query.filter_by(status=TicketStatus.RESOLVED).count(),
        'ARCHIVED': Ticket.query.filter_by(status=TicketStatus.ARCHIVED).count(),
    }
    return render_template('admin/dashboard.html', stats=stats)

@admin_bp.route('/tickets')
@login_required
def tickets_list():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status')
    search_query = request.args.get('q')

    query = Ticket.query.order_by(Ticket.created_at.desc())

    if status_filter and status_filter in TicketStatus.__members__:
        query = query.filter_by(status=TicketStatus(status_filter))

    if search_query:
        search = f"%{search_query}%"
        query = query.filter(
            (Ticket.tracking_code.like(search)) |
            (Ticket.email.like(search))
        )

    pagination = query.paginate(page=page, per_page=20)
    
    return render_template(
        'admin/tickets.html', 
        tickets=pagination, 
        current_status=status_filter
    )

@admin_bp.route('/tickets/<int:id>', methods=['GET'])
@login_required
def ticket_detail(id):
    ticket = Ticket.query.get_or_404(id)
    form = UpdateTicketStatusForm(status=ticket.status.value)
    
    # Generar URLs para adjuntos
    files_urls = []
    for attachment in ticket.attachments:
        url = minio_service.get_file_url(attachment.object_key)
        files_urls.append({
            'name': attachment.file_name,
            'url': url,
            'size': attachment.size_bytes
        })

    return render_template(
        'admin/ticket_detail.html', 
        ticket=ticket, 
        form=form,
        files_urls=files_urls
    )

@admin_bp.route('/tickets/<int:id>/update', methods=['POST'])
@login_required
def update_ticket_status(id):
    ticket = Ticket.query.get_or_404(id)
    form = UpdateTicketStatusForm()
    
    if form.validate_on_submit():
        new_status = form.status.data
        note = form.note.data
        
        if new_status != ticket.status.value or note:
            # Registrar historial
            history = TicketStatusHistory(
                ticket_id=ticket.id,
                old_status=ticket.status.value,
                new_status=new_status,
                changed_by_user_id=current_user.id,
                note=note
            )
            db.session.add(history)
            
            # Actualizar ticket
            ticket.status = TicketStatus(new_status)
            db.session.commit()

            # Registrar Actividad de Gestión
            log_activity(
                action='UPDATE_TICKET',
                details=f'Cambio de estado del ticket #{ticket.tracking_code} a {new_status}. Nota: {note[:50]}...',
                user=current_user
            )
            
            flash('Ticket actualizado correctamente.', 'success')
            
            # Opcional: Enviar correo al ciudadano notificando cambio de estado
            
    return redirect(url_for('admin.ticket_detail', id=ticket.id))

@admin_bp.route('/logs')
@login_required
def view_logs():
    if not current_user.is_superuser:
        log_activity(
            action='UNAUTHORIZED_ACCESS',
            details='Intento de acceso a logs sin privilegios de super admin.',
            user=current_user
        )
        abort(403)
    page = request.args.get('page', 1, type=int)
    action_filter = request.args.get('action')
    user_filter = request.args.get('username')
    date_filter = request.args.get('date')

    query = ActivityLog.query

    if action_filter:
        query = query.filter(ActivityLog.action == action_filter)
    if user_filter:
        query = query.filter(ActivityLog.username == user_filter)
    if date_filter:
        query = query.filter(db.func.date(ActivityLog.created_at) == date_filter)

    pagination = query.order_by(ActivityLog.created_at.desc()).paginate(page=page, per_page=50)
    logs = pagination.items

    actions = db.session.query(ActivityLog.action).distinct().all()
    actions = sorted([a[0] for a in actions])

    users = db.session.query(ActivityLog.username).distinct().all()
    users = sorted([u[0] for u in users if u[0]])

    return render_template(
        'admin/audit_logs.html',
        logs=logs,
        pagination=pagination,
        actions=actions,
        users=users,
        current_action=action_filter,
        current_username=user_filter,
        current_date=date_filter
    )

@admin_bp.route('/logs/export')
@login_required
def export_logs():
    if not current_user.is_superuser:
        log_activity(
            action='UNAUTHORIZED_ACCESS',
            details='Intento de exportar logs sin privilegios de super admin.',
            user=current_user
        )
        abort(403)

    action_filter = request.args.get('action')
    user_filter = request.args.get('username')
    date_filter = request.args.get('date')

    query = ActivityLog.query

    if action_filter:
        query = query.filter(ActivityLog.action == action_filter)
    if user_filter:
        query = query.filter(ActivityLog.username == user_filter)
    if date_filter:
        query = query.filter(db.func.date(ActivityLog.created_at) == date_filter)

    logs = query.order_by(ActivityLog.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Timestamp', 'Usuario', 'Acción', 'Detalles', 'IP Address', 'User Agent'])

    for log in logs:
        writer.writerow([
            log.id,
            log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            log.username or (log.user.email if log.user else 'Anónimo'),
            log.action,
            log.details,
            log.ip_address,
            log.user_agent
        ])

    output.seek(0)
    filename = f"auditoria_extracto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-disposition': f'attachment; filename={filename}'}
    )

@admin_bp.route('/agenda', methods=['GET', 'POST'])
@login_required
def agenda():
    form = ContactForm()
    if form.validate_on_submit():
        contact = Contact(name=form.name.data, email=form.email.data)
        db.session.add(contact)
        db.session.commit()
        
        log_activity(
            action='CREATE_CONTACT',
            details=f'Añadido contacto: {contact.name} ({contact.email})',
            user=current_user
        )
        flash('Contacto guardado en la agenda.', 'success')
        return redirect(url_for('admin.agenda'))
    
    contacts = Contact.query.order_by(Contact.name.asc()).all()
    return render_template('admin/agenda.html', form=form, contacts=contacts)

@admin_bp.route('/email/send', methods=['GET', 'POST'])
@login_required
def send_email():
    contact_id = request.args.get('contact_id', type=int)
    form = SendEmailForm()
    
    # Poblar el desplegable de contactos
    contacts = Contact.query.order_by(Contact.name.asc()).all()
    form.contact_id.choices = [(c.id, c.name) for c in contacts]

    # Poblar el multiselect de tickets pendientes con una consulta específica de columnas
    pending_data = db.session.query(Ticket.id, Ticket.description, Ticket.category).filter(
        Ticket.status == TicketStatus.NEW
    ).order_by(Ticket.created_at.desc()).all()
    
    form.ticket_ids.choices = [(str(t.id), f"#{t.id} [{t.category}] - {t.description[:50]}...") for t in pending_data]
    
    # Si viene un contact_id por URL (desde Agenda), pre-seleccionamos
    if request.method == 'GET' and contact_id:
        form.contact_id.data = contact_id
    
    if form.validate_on_submit():
        contact = Contact.query.get(form.contact_id.data)
        if contact:
            try:
                # Obtener detalles de los tickets seleccionados para el correo
                selected_tickets = []
                attachments_to_send = []
                
                if form.ticket_ids.data:
                    selected_tickets = Ticket.query.filter(Ticket.id.in_(form.ticket_ids.data)).all()
                    
                    # Recolectar adjuntos de estos tickets
                    for ticket in selected_tickets:
                        for att in ticket.attachments:
                            file_content = minio_service.get_file_content(att.object_key)
                            if file_content:
                                attachments_to_send.append({
                                    'filename': att.file_name,
                                    'content_type': att.content_type,
                                    'data': file_content
                                })

                # Enviar el mail real usando el servicio existente
                mail_service.send_email(
                    subject=form.subject.data,
                    recipients=[contact.email],
                    template='emails/internal_communication.html',
                    title=form.subject.data,
                    message=form.message.data,
                    tickets=selected_tickets,
                    attachments=attachments_to_send
                )
                
                # Registrar el log del email (podemos guardar los IDs de los tickets en el body o una tabla nueva, 
                # por ahora los incluiremos en el detalle del log)
                ticket_info = f" | Tickets: {', '.join(form.ticket_ids.data)}" if form.ticket_ids.data else ""
                
                email_log = EmailLog(
                    recipient_name=contact.name,
                    recipient_email=contact.email,
                    subject=form.subject.data,
                    body=form.message.data + ticket_info,
                    sent_by_id=current_user.id
                )
                db.session.add(email_log)
                db.session.commit()
                
                log_activity(
                    action='SEND_INTERNAL_EMAIL',
                    details=f'Correo enviado a {contact.name} ({contact.email}) - Asunto: {form.subject.data}',
                    user=current_user
                )
                
                flash(f'Correo enviado correctamente a {contact.name}.', 'success')
                return redirect(url_for('admin.email_logs'))
            except Exception as e:
                flash(f'Error al enviar el correo: {str(e)}', 'error')
    
    return render_template('admin/send_email.html', form=form)

@admin_bp.route('/email/logs')
@login_required
def email_logs():
    if not current_user.is_superuser:
        log_activity(
            action='UNAUTHORIZED_ACCESS',
            details='Intento de acceso a logs de correos enviados sin privilegios de super admin.',
            user=current_user
        )
        abort(403)
    page = request.args.get('page', 1, type=int)
    logs = EmailLog.query.order_by(EmailLog.sent_at.desc()).paginate(page=page, per_page=30)
    return render_template('admin/email_logs.html', logs=logs)

@admin_bp.route('/email/received')
@login_required
def email_received():
    if not current_user.is_superuser:
        log_activity(
            action='UNAUTHORIZED_ACCESS',
            details='Intento de acceso a logs de correos recibidos sin privilegios de super admin.',
            user=current_user
        )
        abort(403)
    page = request.args.get('page', 1, type=int)
    
    # Solo mostrar si el remitente está en la agenda (Contact)
    contacts = Contact.query.all()
    contact_emails = [c.email for c in contacts]
    contacts_name_map = {c.email: c.name for c in contacts}
    
    query = ReceivedEmail.query.filter(ReceivedEmail.sender_email.in_(contact_emails))
    
    emails = query.order_by(ReceivedEmail.received_at.desc()).paginate(page=page, per_page=30)
    return render_template('admin/email_received.html', emails=emails, contacts_name_map=contacts_name_map)

@admin_bp.route('/email/sync')
@login_required
def email_sync():
    """Trigger manual de sincronización de correos."""
    count = mail_service.fetch_received_emails()
    if count > 0:
        flash(f'¡Sincronización completa! Se recibieron {count} correos nuevos.', 'success')
    else:
        flash('No hay correos nuevos de las direcciones agendadas.', 'info')
    return redirect(url_for('admin.email_received'))

