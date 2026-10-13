from app.utils.dates import utcnow
from datetime import datetime
from app.extensions import db
from .enums import EventStatus, SubmissionStatus

class CulturalEvent(db.Model):
    """
    Evento cultural publicado.
    """
    __tablename__ = 'cultural_events'

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)
    locality = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    event_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), nullable=True)

    status = db.Column(db.Enum(EventStatus), default=EventStatus.PUBLISHED, index=True, nullable=False)

    image_object_key = db.Column(db.String(255), nullable=True)
    image_file_name = db.Column(db.String(255), nullable=True)
    image_content_type = db.Column(db.String(100), nullable=True)
    image_size_bytes = db.Column(db.BigInteger, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self):
        return f'<CulturalEvent {self.title}>'

class EventSubmission(db.Model):
    """
    Postulación de evento enviada desde el formulario público.
    """
    __tablename__ = 'event_submissions'

    id = db.Column(db.Integer, primary_key=True)
    submission_code = db.Column(db.String(50), unique=True, index=True, nullable=False)
    idempotency_key = db.Column(db.String(64), unique=True, nullable=True)
    request_digest = db.Column(db.String(64), nullable=True)

    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    phone = db.Column(db.String(50), nullable=True)

    event_name = db.Column(db.String(200), nullable=False)
    locality = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    event_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text, nullable=False)
    links = db.Column(db.Text, nullable=True)

    status = db.Column(db.Enum(SubmissionStatus), default=SubmissionStatus.NEW, index=True, nullable=False)
    admin_note = db.Column(db.Text, nullable=True)

    image_object_key = db.Column(db.String(255), nullable=True)
    image_file_name = db.Column(db.String(255), nullable=True)
    image_content_type = db.Column(db.String(100), nullable=True)
    image_size_bytes = db.Column(db.BigInteger, nullable=True)

    published_event_id = db.Column(db.Integer, db.ForeignKey('cultural_events.id'), nullable=True)
    published_event = db.relationship('CulturalEvent', backref='submission')

    created_at = db.Column(db.DateTime, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))

    def __repr__(self):
        return f'<EventSubmission {self.submission_code}>'
