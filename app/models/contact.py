from app.utils.dates import utcnow
from datetime import datetime
from app.extensions import db
from .enums import MessageStatus


class Contact(db.Model):
    """
    Agenda de contactos culturales (actores, colectivos, emprendedores).
    """
    __tablename__ = 'contacts'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    email = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    def __repr__(self):
        return f'<Contact {self.name}>'


class ReceivedEmail(db.Model):
    """
    Registro de correos externos recibidos desde direcciones agendadas.
    """
    __tablename__ = 'received_emails'

    id = db.Column(db.Integer, primary_key=True)
    sender_name = db.Column(db.String(100))
    sender_email = db.Column(db.String(255), nullable=False, index=True)
    subject = db.Column(db.String(255))
    body = db.Column(db.Text)
    uid = db.Column(
        db.String(100),
        unique=True
    )  # ID único del servidor de correo para evitar duplicados
    received_at = db.Column(db.DateTime, default=utcnow, index=True)


class EmailLog(db.Model):
    """
    Registro de correos externos enviados a contactos o postulantes.
    """
    __tablename__ = 'sent_emails'

    id = db.Column(db.Integer, primary_key=True)
    recipient_name = db.Column(db.String(120), nullable=False)
    recipient_email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    sent_by_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id'),
        nullable=False
    )
    sent_at = db.Column(db.DateTime, default=utcnow)

    sent_by = db.relationship('User', backref='sent_emails')


class ContactMessage(db.Model):
    """
    Mensajes de contacto general enviados desde el sitio.
    """
    __tablename__ = 'contact_messages'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    subject = db.Column(db.String(255), nullable=True)
    message = db.Column(db.Text, nullable=False)

    status = db.Column(
        db.Enum(MessageStatus),
        default=MessageStatus.NEW,
        index=True,
        nullable=False
    )
    replied_at = db.Column(db.DateTime, nullable=True)
    replied_by_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id'),
        nullable=True
    )

    created_at = db.Column(db.DateTime, default=utcnow, index=True)

    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))

    replied_by = db.relationship('User', backref='replied_messages')
