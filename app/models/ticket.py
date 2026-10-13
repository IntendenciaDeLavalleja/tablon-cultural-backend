from app.utils.dates import utcnow
from datetime import datetime
import secrets
import string
from app.extensions import db
from .enums import TicketStatus

class Ticket(db.Model):
    """
    Ticket de gestión ciudadana.
    
    Seguridad y Diseño:
    - tracking_code: String aleatorio URL-safe (BUZ-YYYY-XXXX). 
      Se indexa para búsquedas públicas sin exponer IDs numéricos secuenciales (evita enumeration attacks).
    - ip_address/user_agent: Auditoría básica para detectar spam/abuso.
    - status: Enum para integridad de datos.
    - email: Indexado para que el usuario pueda consultar historial si se implementa.
    """
    __tablename__ = 'tickets'

    id = db.Column(db.Integer, primary_key=True)
    
    # Formato: BUZ-2026-XC9D8F (no predecible)
    tracking_code = db.Column(db.String(50), unique=True, index=True, nullable=False)
    
    municipality_or_destination = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(100), nullable=False) # Podría ser otro Enum o tabla si crece
    
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    
    status = db.Column(db.Enum(TicketStatus), default=TicketStatus.NEW, index=True, nullable=False)
    
    created_at = db.Column(db.DateTime, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    
    # Auditoría
    ip_address = db.Column(db.String(45)) # Soporta IPv6
    user_agent = db.Column(db.String(255))
    
    # Relaciones
    attachments = db.relationship('TicketAttachment', backref='ticket', cascade='all, delete-orphan')
    history = db.relationship('TicketStatusHistory', backref='ticket', order_by='TicketStatusHistory.created_at.desc()')

    @staticmethod
    def generate_tracking_code():
        """Genera un código tipo BUZ-YYYY-RANDOM seguro y URL-safe."""
        from app.utils.security import generate_tracking_code
        return generate_tracking_code()

    def __repr__(self):
        return f'<Ticket {self.tracking_code}>'

class TicketAttachment(db.Model):
    """
    Adjuntos almacenados en Object Storage (MinIO).
    
    - object_key: La ruta real en MinIO. No guardamos el binario en SQL.
    - size_bytes: Para reportes y control de cuotas.
    """
    __tablename__ = 'ticket_attachments'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False, index=True)
    
    object_key = db.Column(db.String(255), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(100), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False)
    
    created_at = db.Column(db.DateTime, default=utcnow)

class TicketStatusHistory(db.Model):
    """
    Historial de cambios de estado (Audit Log).
    """
    __tablename__ = 'ticket_status_history'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False, index=True)
    
    old_status = db.Column(db.String(50), nullable=True) # Puede ser Null si es el primer estado
    new_status = db.Column(db.String(50), nullable=False)
    
    # Nullable porque el sistema podría cambiar el estado automáticamente (ej: expiración)
    changed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
