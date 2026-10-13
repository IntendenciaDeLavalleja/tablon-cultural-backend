from app.utils.dates import utcnow
from datetime import datetime
from app.extensions import db

class ActivityLog(db.Model):
    """
    Sistema de Auditoría y Logs.
    Registra actividad administrativa y acceso de usuarios.
    """
    __tablename__ = 'activity_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # Null si es sistema o anon
    username = db.Column(db.String(64), nullable=True)
    action = db.Column(db.String(100), nullable=False) # LOGIN, LOGOUT, UPDATE_TICKET, etc.
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    # Relación
    user = db.relationship('User', backref='activity_logs')

    @staticmethod
    def log(user_id, action, details=None, ip=None, ua=None, username=None):
        """Método utilitario para registrar logs rápidamente."""
        try:
            new_log = ActivityLog(
                user_id=user_id,
                username=username,
                action=action,
                details=details,
                ip_address=ip,
                user_agent=ua
            )
            db.session.add(new_log)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            # No bloqueamos la app si falla el logger
            print(f"Error guardando Log: {e}")
