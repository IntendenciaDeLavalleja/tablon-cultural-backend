from app.utils.dates import utcnow
import hashlib
import logging
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
from flask import current_app, render_template
from flask_mail import Message

from app.extensions import db
from app.models.user import User, TwoFactorCode
from app.utils.security import generate_random_code, hash_code, verify_code

class MailService:
    def deliver(self, msg):
        """Bounded, synchronous delivery. Failures must reach the caller."""
        import smtplib
        import ssl
        app = current_app
        if msg.has_bad_headers():
            raise ValueError('Encabezados de correo inválidos.')
        if app.config.get('MAIL_SUPPRESS_SEND'):
            return
        server = app.config.get('MAIL_SERVER')
        configured_sender = msg.sender or app.config.get('MAIL_DEFAULT_SENDER') or ''
        sender = configured_sender[1] if isinstance(configured_sender, tuple) else email.utils.parseaddr(configured_sender)[1]
        if not server or not sender:
            raise ValueError('El servicio de correo no está configurado.')
        factory = smtplib.SMTP_SSL if app.config['MAIL_USE_SSL'] else smtplib.SMTP
        options = {'timeout': 10}
        if app.config['MAIL_USE_SSL']:
            options['context'] = ssl.create_default_context()
        with factory(server, app.config['MAIL_PORT'], **options) as smtp:
            if app.config['MAIL_USE_TLS']:
                smtp.starttls(context=ssl.create_default_context())
            if app.config.get('MAIL_USERNAME'):
                smtp.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
            smtp.sendmail(sender, msg.recipients, msg.as_bytes())

    def send_email(self, subject, recipients, template, attachments=None, **kwargs):
        msg = Message(subject, recipients=recipients, html=render_template(template, **kwargs))
        for att in attachments or []:
            msg.attach(filename=att['filename'], content_type=att['content_type'], data=att['data'])
        self.deliver(msg)

    def send_admin_2fa_code(self, user, code):
        self.send_email(subject='Código de Verificación - Tablón Cultural',
                        recipients=[user.email], template='emails/admin_2fa_code.html',
                        code=code, user=user)

    def fetch_received_emails(self):
        """
        Filtra y descarga correos desde la bandeja de entrada.
        """
        from app.models.contact import ReceivedEmail, Contact
        
        app = current_app._get_current_object()
        server = app.config.get('MAIL_SERVER')
        user = app.config.get('MAIL_USERNAME')
        password = app.config.get('MAIL_PASSWORD')
        
        # Lógica simple de conexión (asumimos servidor IMAP estándar)
        imap_host = app.config.get('IMAP_SERVER')
        if not imap_host or not user or not password:
            raise ValueError('El servicio IMAP no está configurado.')

        new_count = 0
        connection = None
        try:
            # Conexión SSL (standard for imap.gmail.com etc)
            mail = imaplib.IMAP4_SSL(imap_host, app.config['IMAP_PORT'], timeout=10)
            connection = mail
            mail.login(user, password)
            status, _ = mail.select("inbox", readonly=True)
            if status != 'OK':
                raise ValueError('No se pudo abrir la bandeja de entrada.')
            validity = mail.response('UIDVALIDITY')[1][0].decode()

            # Buscar correos de los últimos 7 días para no saturar
            date_filter = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
            status, messages = mail.uid('search', None, f'(SINCE "{date_filter}")')

            if status != 'OK':
                raise ValueError('No se pudo consultar la bandeja de entrada.')
            for num in messages[0].split():
                uid = hashlib.sha256(f'{imap_host}:{user}:{validity}:{num.decode()}'.encode()).hexdigest()
                if ReceivedEmail.query.filter_by(uid=uid).first():
                    continue
                status, msg_data = mail.uid('fetch', num, "(BODY.PEEK[])")
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])

                        
                        # Evitar duplicados
                        if ReceivedEmail.query.filter_by(uid=uid).first():
                            continue

                        # Decodificar Asunto
                        subject_raw = msg.get("Subject", "(Sin Asunto)")
                        subject = subject_raw
                        try:
                            decoded_subject = decode_header(subject_raw)
                            subject_parts = []
                            for part, enc in decoded_subject:
                                if isinstance(part, bytes):
                                    subject_parts.append(part.decode(enc or "utf-8", errors="ignore"))
                                else:
                                    subject_parts.append(part)
                            subject = " ".join(subject_parts)
                        except:
                            pass
                        
                        sender_raw = msg.get("From", "")
                        sender_email = email.utils.parseaddr(sender_raw)[1].lower()

                        # Solo guardar si el remitente está en la agenda
                        contact = Contact.query.filter_by(email=sender_email).first()
                        if not contact:
                            continue

                        # Decodificar nombre del remitente de forma segura
                        sender_name = sender_raw
                        try:
                            decoded_parts = decode_header(sender_raw)
                            decoded_name = ""
                            for part, enc in decoded_parts:
                                if isinstance(part, bytes):
                                    decoded_name += part.decode(enc or "utf-8", errors="ignore")
                                else:
                                    decoded_name += part
                            sender_name = decoded_name
                        except:
                            pass

                        # Extraer cuerpo (simplificado)
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    body = (part.get_payload(decode=True) or b'').decode(part.get_content_charset() or 'utf-8', errors='replace')
                                    break
                        else:
                            body = (msg.get_payload(decode=True) or b'').decode(msg.get_content_charset() or 'utf-8', errors='replace')

                        new_email = ReceivedEmail(
                            sender_name=sender_name[:100],
                            sender_email=sender_email,
                            subject=subject[:255],
                            body=body,
                            uid=uid,
                            received_at=datetime.now()
                        )
                        db.session.add(new_email)
                        new_count += 1
            
            db.session.commit()
            return new_count
        except Exception as e:
            db.session.rollback()
            logging.error('Error fetching emails: %s', type(e).__name__)
            raise ValueError('No se pudo sincronizar el correo. Revisá la configuración IMAP.') from e
        finally:
            if connection:
                try:
                    connection.logout()
                except Exception:
                    pass

class AuthService:
    """
    Servicio encargado de la lógica de seguridad y autenticación (2FA generation).
    Separado del MailService para mantener SRP.
    """
    RATE_LIMIT_MINUTES = 1 # Cooldown entre reenvíos de código

    def generate_and_send_2fa(self, user: User, mail_service: MailService):
        """
        Genera un código 2FA seguro, lo hashea, lo guarda en DB y lo envía por mail.
        Verifica rate limits antes de generar uno nuevo.
        """
        # Serialize code issuance per user across workers.
        db.session.execute(db.select(User).where(User.id == user.id).with_for_update()).scalar_one()
        # 1. Check Rate Limit (Cooldown)
        last_code = TwoFactorCode.query.filter_by(user_id=user.id)\
            .order_by(TwoFactorCode.created_at.desc()).first()
        
        if last_code:
            delta = utcnow() - last_code.created_at
            if delta < timedelta(minutes=self.RATE_LIMIT_MINUTES):
                raise ValueError(f"Por favor espere {self.RATE_LIMIT_MINUTES} minuto(s) antes de solicitar un nuevo código.")

        # 2. Generate Secure Code using centralized security util
        code = generate_random_code(length=6, numeric_only=True)
        
        # 3. Hash Code using centralized security util
        code_hash = hash_code(code)
        
        # 4. Save to DB
        expires_at = utcnow() + timedelta(minutes=10)
        
        TwoFactorCode.query.filter_by(user_id=user.id, consumed_at=None).update({'consumed_at': utcnow()})
        
        new_2fa = TwoFactorCode(
            user_id=user.id,
            code_hash=code_hash,
            expires_at=expires_at
        )
        
        db.session.add(new_2fa)
        try:
            mail_service.send_admin_2fa_code(user, code)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logging.error('2FA delivery failed: %s', type(exc).__name__)
            raise ValueError('No se pudo enviar el código. Intente nuevamente.') from exc
        
        return True

    def verify_2fa_code(self, user: User, code: str) -> bool:
        """
        Valida que el código sea correcto y no haya expirado.
        Marca el código como consumido si es válido.
        """
        # Buscar códigos válidos no consumidos
        valid_code_entry = TwoFactorCode.query.filter(
            TwoFactorCode.user_id == user.id,
            TwoFactorCode.consumed_at.is_(None),
            TwoFactorCode.expires_at > utcnow()
        ).order_by(TwoFactorCode.created_at.desc()).with_for_update().first()

        if not user.is_active or not valid_code_entry or valid_code_entry.attempts >= 5:
            return False

        # Verificar Hash
        if not verify_code(valid_code_entry.code_hash, code):
            # Incrementar intentos fallidos (opcional, para bloqueo)
            valid_code_entry.attempts += 1
            db.session.commit()
            return False

        # Marcar como consumido
        valid_code_entry.consumed_at = utcnow()
        db.session.commit()
        return True

# Singleton instances
mail_service = MailService()
auth_service = AuthService()
