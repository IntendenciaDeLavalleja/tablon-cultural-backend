from app.utils.dates import utcnow
"""Durable notification queue, committed in the same transaction as a submission.

Run exactly one worker. Delivery is at least once: an SMTP acknowledgement followed
by a process crash can cause a repeated email, but never a repeated submission.
"""
import time
from datetime import datetime, timedelta
import click
from flask import current_app, render_template
from flask.cli import with_appcontext
from flask_mail import Message
from app.extensions import db
from app.models.outbox import OutboxEmail


def queue_submission_emails(submission):
    targets = [(submission.email, f'Postulación recibida: {submission.submission_code}',
                'emails/event_submission_received.html')]
    admin = current_app.config.get('ADMIN_NOTIFICATION_EMAIL')
    if admin:
        event_name = ' '.join(submission.event_name.splitlines())
        targets.append((admin, f'Nueva postulación de evento: {event_name}',
                        'emails/admin_new_event_notification.html'))
    for recipient, subject, template in targets:
        db.session.add(OutboxEmail(recipient=recipient, subject=subject[:255],
                                   html=render_template(template, submission=submission)))


def process_outbox():
    from .mail_service import mail_service
    pending = OutboxEmail.query.filter(OutboxEmail.sent_at.is_(None),
        OutboxEmail.next_attempt_at <= utcnow()).order_by(OutboxEmail.id).limit(50).all()
    for entry in pending:
        entry.attempts += 1
        try:
            mail_service.deliver(Message(entry.subject, recipients=[entry.recipient], html=entry.html))
            entry.sent_at = utcnow()
            entry.last_error = None
        except Exception as exc:
            entry.last_error = type(exc).__name__
            entry.next_attempt_at = utcnow() + timedelta(seconds=min(3600, 30 * 2 ** min(entry.attempts, 7)))
            current_app.logger.warning('Outbox email %s failed: %s', entry.id, type(exc).__name__)
        db.session.commit()
    return len(pending)


@click.command('process-outbox')
@click.option('--once', is_flag=True)
@with_appcontext
def process_outbox_command(once):
    while True:
        try:
            process_outbox()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Outbox worker failed; retrying')
            if once:
                raise
        finally:
            db.session.remove()
        if once:
            return
        time.sleep(5)
