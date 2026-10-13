from flask import request, has_request_context
from flask_login import current_user
from app.extensions import db
from app.models.audit import ActivityLog


def log_activity(action, details=None, user=None):
    """
    Registra una actividad en la base de datos con información forense.
    Usa el usuario actual si no se pasa uno explícitamente.
    """
    try:
        user_id = None
        username = "ANONYMOUS"

        if user:
            user_id = user.id
            username = user.username or user.email
        elif current_user and current_user.is_authenticated:
            user_id = current_user.id
            username = current_user.username or current_user.email

        ip = None
        user_agent = None
        if has_request_context():
            ip = request.remote_addr
            user_agent = request.user_agent.string[:255]

        log = ActivityLog(
            user_id=user_id,
            username=username[:64],
            action=action,
            details=details,
            ip_address=ip,
            user_agent=user_agent
        )

        db.session.add(log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error logging activity: {e}")
