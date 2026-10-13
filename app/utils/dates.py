from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import current_app


def local_today():
    return datetime.now(ZoneInfo(current_app.config['EVENT_TIMEZONE'])).date()


def utcnow():
    """Naive UTC for existing SQL DateTime columns; no deprecated utcnow API."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
