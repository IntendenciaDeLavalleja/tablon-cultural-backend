from app.utils.dates import utcnow
from datetime import datetime
from app.extensions import db


class OutboxEmail(db.Model):
    __tablename__ = 'outbox_emails'
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    html = db.Column(db.Text, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    next_attempt_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    sent_at = db.Column(db.DateTime)
    last_error = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
