from app.utils.dates import utcnow
from flask import render_template, redirect, url_for, flash, request, session, abort, Response
from flask_login import login_user, login_required, logout_user, current_user
from datetime import datetime
import csv
import io
import random

from app.extensions import db, limiter, login_manager
from app.models.user import User
from app.models.event import CulturalEvent, EventSubmission
from app.models.enums import SubmissionStatus, EventStatus, MessageStatus
from app.models.audit import ActivityLog
from app.models.contact import Contact, EmailLog, ReceivedEmail, ContactMessage
from app.forms.auth import LoginForm, TwoFactorForm
from app.forms.admin import UpdateSubmissionStatusForm, ContactForm, SendEmailForm, ReplyEmailForm, CulturalEventForm
from app.services.mail_service import mail_service, auth_service
from app.services.minio_service import minio_service
from app.utils.security import verify_password
from app.utils.logging_helper import log_activity

from . import admin_bp

@login_manager.user_loader
def load_user(user_id):
    try:
        user = db.session.get(User, int(user_id))
        return user if user and user.is_active else None
    except (ValueError, TypeError):
        return None

@admin_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))

    form = LoginForm()

    if request.method == 'GET':
        n1, n2 = random.randint(1, 9), random.randint(1, 9)
        session['captcha_question'] = f"{n1} + {n2}"
        session['captcha_answer'] = n1 + n2

    if form.validate_on_submit():
        user_captcha = form.captcha.data
        correct_captcha = session.get('captcha_answer')

        if not correct_captcha or str(user_captcha) != str(correct_captcha):
            flash('Captcha incorrecto. Intente de nuevo.', 'error')
            n1, n2 = random.randint(1, 9), random.randint(1, 9)
            session['captcha_question'] = f"{n1} + {n2}"
            session['captcha_answer'] = n1 + n2
            return render_template('admin/login.html', form=form)

        user = User.query.filter_by(email=form.email.data).first()

        valid_password = False
        if user and user.is_active:
            valid_password = verify_password(user.password_hash, form.password.data)

        if valid_password:
            try:
                auth_service.generate_and_send_2fa(user, mail_service)
                session['2fa_user_id'] = user.id
                flash('Código de verificación enviado a tu correo.', 'info')
                return redirect(url_for('admin.verify_2fa'))
            except ValueError as e:
                flash(str(e), 'error')
        else:
            flash('Email o contraseña inválidos', 'error')

    return render_template('admin/login.html', form=form)

@admin_bp.route('/2fa', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def verify_2fa():
    user_id = session.get('2fa_user_id')
    if not user_id:
        return redirect(url_for('admin.login'))

    user = db.session.get(User, user_id)
    if not user or not user.is_active:
        session.pop('2fa_user_id', None)
        return redirect(url_for('admin.login'))

    form = TwoFactorForm()
    if form.validate_on_submit():
        if auth_service.verify_2fa_code(user, form.code.data):
            login_user(user)

            log_activity(
                action='LOGIN',
                details='Inicio de sesión exitoso con 2FA',
                user=user
            )

            session.pop('2fa_user_id', None)

            user.last_login_at = utcnow()
            db.session.commit()

            flash('Sesión iniciada correctamente.', 'success')
            return redirect(url_for('admin.dashboard'))
        else:
            flash('Código inválido o expirado.', 'error')

    return render_template('admin/verify_2fa.html', form=form)

@admin_bp.route('/logout', methods=['POST'])
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
    stats = {
        'SUBMISSIONS_NEW': EventSubmission.query.filter_by(status=SubmissionStatus.NEW).count(),
        'SUBMISSIONS_APPROVED': EventSubmission.query.filter_by(status=SubmissionStatus.APPROVED).count(),
        'SUBMISSIONS_REJECTED': EventSubmission.query.filter_by(status=SubmissionStatus.REJECTED).count(),
        'EVENTS_PUBLISHED': CulturalEvent.query.filter_by(status=EventStatus.PUBLISHED).count(),
        'CONTACT_NEW': ContactMessage.query.filter_by(status=MessageStatus.NEW).count()
    }
    return render_template('admin/dashboard.html', stats=stats)

@admin_bp.route('/event-submissions')
@login_required
def event_submissions_list():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status')
    search_query = request.args.get('q')

    query = EventSubmission.query.order_by(EventSubmission.created_at.desc())

    if status_filter and status_filter in SubmissionStatus.__members__:
        query = query.filter_by(status=SubmissionStatus(status_filter))

    if search_query:
        search = f"%{search_query}%"
        query = query.filter(
            (EventSubmission.submission_code.like(search)) |
            (EventSubmission.email.like(search)) |
            (EventSubmission.event_name.like(search))
        )

    pagination = query.paginate(page=page, per_page=20)

    return render_template(
        'admin/event_submissions.html',
        submissions=pagination,
        current_status=status_filter
    )

@admin_bp.route('/event-submissions/<int:id>', methods=['GET'])
@login_required
def event_submission_detail(id):
    submission = db.get_or_404(EventSubmission, id)
    status_form = UpdateSubmissionStatusForm(status=submission.status.value)
    reply_form = ReplyEmailForm()

    image_url = None
    if submission.image_object_key:
        try:
            image_url = minio_service.get_file_url(submission.image_object_key)
        except Exception:
            image_url = None

    return render_template(
        'admin/event_submission_detail.html',
        submission=submission,
        status_form=status_form,
        reply_form=reply_form,
        image_url=image_url
    )

@admin_bp.route('/event-submissions/<int:id>/update', methods=['POST'])
@login_required
def update_event_submission_status(id):
    submission = EventSubmission.query.filter_by(id=id).with_for_update().first_or_404()
    if submission.status in {SubmissionStatus.REJECTED, SubmissionStatus.ARCHIVED}:
        flash('La postulación está cerrada y no admite cambios de estado.', 'error')
        return redirect(url_for('admin.event_submission_detail', id=submission.id))
    form = UpdateSubmissionStatusForm()

    if form.validate_on_submit():
        quick_status = request.form.get('quick_status')
        if quick_status in SubmissionStatus.__members__:
            new_status = quick_status
        else:
            new_status = form.status.data

        note = (form.note.data or '').strip()

        if new_status in {SubmissionStatus.REJECTED.value, SubmissionStatus.ARCHIVED.value} and not note:
            flash('Debes agregar una nota interna para rechazar o archivar la postulación.', 'error')
            return redirect(url_for('admin.event_submission_detail', id=submission.id))

        linked_event = CulturalEvent.query.filter_by(id=submission.published_event_id).with_for_update().first() if submission.published_event_id else None
        if new_status == SubmissionStatus.APPROVED.value and not linked_event:
            flash('Usá Crear evento para aprobar y publicar esta postulación.', 'error')
            return redirect(url_for('admin.event_submission_detail', id=submission.id))
        if new_status == SubmissionStatus.APPROVED.value and linked_event.status != EventStatus.PUBLISHED:
            flash('Debés publicar el evento vinculado antes de aprobar la postulación.', 'error')
            return redirect(url_for('admin.event_submission_detail', id=submission.id))
        if linked_event and new_status in {SubmissionStatus.NEW.value, SubmissionStatus.REJECTED.value, SubmissionStatus.ARCHIVED.value}:
            linked_event.status = EventStatus.ARCHIVED
        removed_submission_image = False
        image_to_delete = None
        if new_status in {SubmissionStatus.REJECTED.value, SubmissionStatus.ARCHIVED.value} and submission.image_object_key:
            image_in_use_by_event = CulturalEvent.query.filter_by(image_object_key=submission.image_object_key).first()
            if image_in_use_by_event:
                flash('La imagen está en uso por un evento publicado; se desvincula de la postulación sin borrar el archivo físico.', 'warning')
            else:
                image_to_delete = submission.image_object_key

            submission.image_object_key = None
            submission.image_file_name = None
            submission.image_content_type = None
            submission.image_size_bytes = None

        if new_status != submission.status.value or note:
            submission.status = SubmissionStatus(new_status)
            submission.admin_note = note

            db.session.commit()

            # Never destroy the received file before the moderation transaction succeeds.
            cleanup_note = ''
            if image_to_delete:
                try:
                    minio_service.delete_file(image_to_delete)
                    removed_submission_image = True
                except Exception:
                    cleanup_note = f' Imagen pendiente de eliminar: {image_to_delete}.'
                    flash('La postulación se cerró, pero no se pudo eliminar su imagen del almacenamiento. Revisá la auditoría.', 'warning')
            log_activity(
                action='UPDATE_EVENT_SUBMISSION',
                details=f'Postulación #{submission.submission_code} actualizada a {new_status}. Imagen eliminada: {"sí" if removed_submission_image else "no"}.{cleanup_note}',
                user=current_user
            )

            flash('Postulación actualizada correctamente.', 'success')

    if form.errors:
        flash('Revisá el formulario: ' + '; '.join(error for errors in form.errors.values() for error in errors), 'error')
    return redirect(url_for('admin.event_submission_detail', id=submission.id))

@admin_bp.route('/events/create', methods=['GET', 'POST'])
@login_required
def create_event():
    form = CulturalEventForm()
    submission_id = request.args.get('submission_id', type=int) or request.form.get('submission_id', type=int)
    submission = EventSubmission.query.filter_by(id=submission_id).with_for_update().first_or_404() if submission_id else None
    if submission and submission.status in {SubmissionStatus.REJECTED, SubmissionStatus.ARCHIVED}:
        flash('La postulación está cerrada y no puede convertirse en evento.', 'error')
        return redirect(url_for('admin.event_submission_detail', id=submission.id))
    if submission and submission.published_event_id:
        flash('Esta postulación ya tiene un evento. Podés editarlo.', 'info')
        return redirect(url_for('admin.edit_event', id=submission.published_event_id))
    submission_image_url = None
    if submission and submission.image_object_key:
        try:
            submission_image_url = minio_service.get_file_url(submission.image_object_key)
        except Exception:
            submission_image_url = None
    
    if submission_id and request.method == 'GET':
        if submission:
            form.title.data = submission.event_name
            form.locality.data = submission.locality
            form.address.data = submission.address
            form.event_date.data = submission.event_date
            form.description.data = submission.description

    if form.validate_on_submit():
        event = CulturalEvent(
            title=form.title.data,
            locality=form.locality.data,
            address=form.address.data,
            event_date=form.event_date.data,
            description=form.description.data,
            category=form.category.data,
            status=EventStatus.PUBLISHED
        )
        
        # Gestionar subida de imagen manual
        if form.image.data:
            try:
                upload_result = minio_service.upload_cultural_event_image(form.image.data)
                event.image_object_key = upload_result['object_key']
                event.image_file_name = upload_result['file_name']
                event.image_content_type = upload_result['content_type']
                event.image_size_bytes = upload_result['size_bytes']
                try:
                    event.image_url = minio_service.get_file_url(event.image_object_key)
                except Exception:
                    pass
            except Exception as e:
                db.session.rollback()
                flash('No se pudo guardar la imagen. Intente nuevamente.', 'error')
                return render_template('admin/event_form.html', form=form, title='Guardar evento', submission_id=submission_id), 503

        # Si viene de una postulación, vincular y copiar imagen (si no se subió una nueva)
        if submission:
            if not form.image.data and submission.image_object_key:
                event.image_object_key = submission.image_object_key
                event.image_file_name = submission.image_file_name
                event.image_content_type = submission.image_content_type
                event.image_size_bytes = submission.image_size_bytes
                try:
                    event.image_url = minio_service.get_file_url(event.image_object_key)
                except Exception:
                    pass

            submission.status = SubmissionStatus.APPROVED
            db.session.add(event)
            db.session.flush()
            submission.published_event_id = event.id
        else:
            db.session.add(event)

        db.session.commit()
        log_activity(
            action='CREATE_EVENT',
            details=f'Evento "{event.title}" creado directamente por admin.',
            user=current_user
        )
        flash('Evento creado exitosamente.', 'success')
        return redirect(url_for('admin.events_list'))

    return render_template(
        'admin/event_form.html',
        form=form,
        title="Crear Nuevo Evento",
        submission_id=submission_id,
        submission=submission,
        submission_image_url=submission_image_url
    )

@admin_bp.route('/events/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_event(id):
    event = db.get_or_404(CulturalEvent, id)
    form = CulturalEventForm(obj=event)
    
    if form.validate_on_submit():
        for field in ('title', 'locality', 'address', 'event_date', 'description', 'category'):
            setattr(event, field, getattr(form, field).data)
        
        # Gestionar subida de imagen manual
        if form.image.data:
            try:
                upload_result = minio_service.upload_cultural_event_image(form.image.data)
                event.image_object_key = upload_result['object_key']
                event.image_file_name = upload_result['file_name']
                event.image_content_type = upload_result['content_type']
                event.image_size_bytes = upload_result['size_bytes']
                
                # Actualizar URL pública si existe
                try:
                    event.image_url = minio_service.get_file_url(event.image_object_key)
                except Exception:
                    pass
            except Exception as e:
                db.session.rollback()
                flash('No se pudo guardar la imagen. Intente nuevamente.', 'error')
                return render_template('admin/event_form.html', form=form, title='Editar evento', event=event), 503

        db.session.commit()
        log_activity(
            action='EDIT_EVENT',
            details=f'Evento "{event.title}" editado por admin.',
            user=current_user
        )
        flash('Evento actualizado.', 'success')
        return redirect(url_for('admin.events_list'))
        
    # Obtener URL actual para vista previa, refrescar si es de MinIO
    image_url = None
    if event.image_object_key:
        try:
            image_url = minio_service.get_file_url(event.image_object_key)
        except Exception:
            pass
    
    if not image_url:
        image_url = event.image_url

    return render_template('admin/event_form.html', form=form, title="Editar Evento", event=event, image_url=image_url)

@admin_bp.route('/events/<int:id>/delete', methods=['POST'])
@login_required
def delete_event(id):
    event = db.get_or_404(CulturalEvent, id)
    title = event.title
    
    # Nullify references in submissions
    submissions = EventSubmission.query.filter_by(published_event_id=id).all()
    for s in submissions:
        s.published_event_id = None
        if s.status == SubmissionStatus.APPROVED:
            s.status = SubmissionStatus.NEW
    
    db.session.delete(event)
    db.session.commit()
    
    log_activity(
        action='DELETE_EVENT',
        details=f'Evento "{title}" eliminado por admin.',
        user=current_user
    )
    flash('Evento eliminado permanentemente.', 'info')
    return redirect(url_for('admin.events_list'))

@admin_bp.route('/event-submissions/<int:id>/reply', methods=['POST'])
@login_required
def reply_event_submission(id):
    submission = db.get_or_404(EventSubmission, id)
    form = ReplyEmailForm()

    if form.validate_on_submit():
        try:
            mail_service.send_email(
                subject=form.subject.data,
                recipients=[submission.email],
                template='emails/internal_communication.html',
                title=form.subject.data,
                message=form.message.data
            )

            email_log = EmailLog(
                recipient_name=submission.full_name,
                recipient_email=submission.email,
                subject=form.subject.data,
                body=form.message.data,
                sent_by_id=current_user.id
            )
            db.session.add(email_log)
            db.session.commit()

            log_activity(
                action='REPLY_EVENT_SUBMISSION',
                details=f'Respuesta enviada a {submission.email} - Asunto: {form.subject.data}',
                user=current_user
            )

            flash('Respuesta enviada correctamente.', 'success')
        except Exception as e:
            db.session.rollback()
            flash('No se pudo enviar el correo. Intente nuevamente.', 'error')

    if form.errors:
        flash('Revisá el formulario: ' + '; '.join(error for errors in form.errors.values() for error in errors), 'error')
    return redirect(url_for('admin.event_submission_detail', id=submission.id))

@admin_bp.route('/events')
@login_required
def events_list():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status')

    query = CulturalEvent.query.order_by(CulturalEvent.created_at.desc())

    if status_filter and status_filter in EventStatus.__members__:
        query = query.filter_by(status=EventStatus(status_filter))

    pagination = query.paginate(page=page, per_page=20)

    return render_template(
        'admin/events.html',
        events=pagination,
        current_status=status_filter
    )

@admin_bp.route('/events/<int:id>/archive', methods=['POST'])
@login_required
def archive_event(id):
    event = db.get_or_404(CulturalEvent, id)
    event.status = EventStatus.ARCHIVED
    db.session.commit()

    log_activity(
        action='ARCHIVE_EVENT',
        details=f'Evento #{event.id} archivado',
        user=current_user
    )
    flash('Evento archivado.', 'success')
    return redirect(url_for('admin.events_list'))

@admin_bp.route('/events/<int:id>/publish', methods=['POST'])
@login_required
def publish_event(id):
    submissions = EventSubmission.query.filter_by(published_event_id=id).with_for_update().all()
    event = CulturalEvent.query.filter_by(id=id).with_for_update().first_or_404()
    if any(s.status in {SubmissionStatus.REJECTED, SubmissionStatus.ARCHIVED} for s in submissions):
        flash('El evento pertenece a una postulación cerrada y no puede volver a publicarse.', 'error')
        return redirect(url_for('admin.events_list'))
    from app.utils.dates import local_today
    if event.event_date < local_today():
        flash('Actualizá la fecha antes de publicar un evento pasado.', 'error')
        return redirect(url_for('admin.events_list'))
    event.status = EventStatus.PUBLISHED
    for submission in submissions:
        submission.status = SubmissionStatus.APPROVED
    db.session.commit()

    log_activity(
        action='PUBLISH_EVENT',
        details=f'Evento #{event.id} publicado',
        user=current_user
    )
    flash('Evento publicado.', 'success')
    return redirect(url_for('admin.events_list'))

@admin_bp.route('/contact-messages')
@login_required
def contact_messages():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status')
    search_query = request.args.get('q')

    query = ContactMessage.query.order_by(ContactMessage.created_at.desc())

    if status_filter and status_filter in MessageStatus.__members__:
        query = query.filter_by(status=MessageStatus(status_filter))

    if search_query:
        search = f"%{search_query}%"
        query = query.filter(
            (ContactMessage.email.like(search)) |
            (ContactMessage.full_name.like(search)) |
            (ContactMessage.subject.like(search))
        )

    pagination = query.paginate(page=page, per_page=20)

    return render_template(
        'admin/contact_messages.html',
        messages=pagination,
        current_status=status_filter
    )

@admin_bp.route('/contact-messages/<int:id>', methods=['GET'])
@login_required
def contact_message_detail(id):
    message = db.get_or_404(ContactMessage, id)
    reply_form = ReplyEmailForm()
    return render_template(
        'admin/contact_message_detail.html',
        message=message,
        reply_form=reply_form
    )

@admin_bp.route('/contact-messages/<int:id>/reply', methods=['POST'])
@login_required
def reply_contact_message(id):
    message = db.get_or_404(ContactMessage, id)
    form = ReplyEmailForm()

    if form.validate_on_submit():
        try:
            mail_service.send_email(
                subject=form.subject.data,
                recipients=[message.email],
                template='emails/internal_communication.html',
                title=form.subject.data,
                message=form.message.data
            )

            email_log = EmailLog(
                recipient_name=message.full_name,
                recipient_email=message.email,
                subject=form.subject.data,
                body=form.message.data,
                sent_by_id=current_user.id
            )
            db.session.add(email_log)

            message.status = MessageStatus.REPLIED
            message.replied_at = utcnow()
            message.replied_by_id = current_user.id

            db.session.commit()

            log_activity(
                action='REPLY_CONTACT_MESSAGE',
                details=f'Respuesta enviada a {message.email} - Asunto: {form.subject.data}',
                user=current_user
            )

            flash('Respuesta enviada correctamente.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al enviar el correo: {str(e)}', 'error')

    if form.errors:
        flash('Revisá el formulario: ' + '; '.join(error for errors in form.errors.values() for error in errors), 'error')
    return redirect(url_for('admin.contact_message_detail', id=message.id))

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
        writer.writerow([csv_safe(value) for value in [
            log.id,
            log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            log.username or (log.user.email if log.user else 'Anónimo'),
            log.action,
            log.details,
            log.ip_address,
            log.user_agent
        ]])

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

    contacts = Contact.query.order_by(Contact.name.asc()).all()
    form.contact_id.choices = [(c.id, c.name) for c in contacts]

    if request.method == 'GET' and contact_id:
        form.contact_id.data = contact_id

    if form.validate_on_submit():
        contact = db.session.get(Contact, form.contact_id.data)
        if contact:
            try:
                mail_service.send_email(
                    subject=form.subject.data,
                    recipients=[contact.email],
                    template='emails/internal_communication.html',
                    title=form.subject.data,
                    message=form.message.data
                )

                email_log = EmailLog(
                    recipient_name=contact.name,
                    recipient_email=contact.email,
                    subject=form.subject.data,
                    body=form.message.data,
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
                return redirect(url_for('admin.email_logs' if current_user.is_superuser else 'admin.agenda'))
            except Exception as e:
                db.session.rollback()
                flash('No se pudo enviar el correo. Intente nuevamente.', 'error')

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

    contacts = Contact.query.all()
    contact_emails = [c.email for c in contacts]
    contacts_name_map = {c.email: c.name for c in contacts}

    query = ReceivedEmail.query.filter(ReceivedEmail.sender_email.in_(contact_emails))

    emails = query.order_by(ReceivedEmail.received_at.desc()).paginate(page=page, per_page=30)
    return render_template('admin/email_received.html', emails=emails, contacts_name_map=contacts_name_map)

@admin_bp.route('/email/sync', methods=['POST'])
@login_required
def email_sync():
    if not current_user.is_superuser:
        abort(403)
    try:
        count = mail_service.fetch_received_emails()
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('admin.email_received'))
    if count > 0:
        flash(f'¡Sincronización completa! Se recibieron {count} correos nuevos.', 'success')
    else:
        flash('No hay correos nuevos de las direcciones agendadas.', 'info')
    return redirect(url_for('admin.email_received'))


def csv_safe(value):
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


@admin_bp.route('')
@admin_bp.route('/')
def redirect_admin_root():
    return redirect(url_for('admin.dashboard'))


@admin_bp.after_request
def prevent_admin_caching(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@admin_bp.get('/email/queue')
@login_required
def email_queue():
    if not current_user.is_superuser:
        abort(403)
    from app.models.outbox import OutboxEmail
    query = OutboxEmail.query.filter(OutboxEmail.sent_at.is_(None))
    return render_template('admin/email_queue.html', pending=query.count(),
        failed=query.filter(OutboxEmail.last_error.is_not(None)).count(),
        entries=OutboxEmail.query.order_by(OutboxEmail.id.desc()).paginate(page=request.args.get('page', 1, type=int), per_page=30))


@admin_bp.post('/email/queue/<int:id>/retry')
@login_required
def retry_notification(id):
    if not current_user.is_superuser:
        abort(403)
    from app.models.outbox import OutboxEmail
    entry = db.get_or_404(OutboxEmail, id)
    if not entry.sent_at:
        entry.next_attempt_at = utcnow()
        db.session.commit()
        flash('Notificación programada para reintento.', 'success')
    return redirect(url_for('admin.email_queue'))
