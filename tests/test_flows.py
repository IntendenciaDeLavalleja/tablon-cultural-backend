from app.utils.dates import utcnow
from datetime import date, datetime, timedelta
from io import BytesIO
from unittest.mock import Mock
import pytest
from PIL import Image
from app.extensions import db
from app.models.event import CulturalEvent, EventSubmission
from app.models.contact import Contact, ContactMessage, EmailLog
from app.models.enums import EventStatus, SubmissionStatus, MessageStatus
from app.models.user import User, TwoFactorCode
from app.models.outbox import OutboxEmail
from app.services.mail_service import mail_service, auth_service
from app.services.minio_service import minio_service, StorageError
from app.services.outbox_service import process_outbox
from app.utils.security import hash_password, hash_code


@pytest.fixture
def payload():
    return dict(full_name='Persona de Prueba', email='persona@example.com',
        email_confirm='persona@example.com', event_name='Evento de Prueba',
        locality='Minas', event_date='2099-12-31', description='Descripción del evento cultural.',
        links='https://example.com', captcha_question='3 + 4', captcha_answer='7')


@pytest.fixture
def admin(client):
    user = User(username='admin', email='admin@example.com', password_hash=hash_password('Password-123'), is_active=True, is_superuser=True)
    db.session.add(user)
    db.session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    return user


def png():
    stream = BytesIO()
    Image.new('RGB', (20, 20), 'red').save(stream, format='PNG')
    stream.seek(0)
    return stream


def event(**kwargs):
    values = dict(title='Evento público', locality='Minas', event_date=date(2099, 12, 31), description='Descripción válida del evento.', status=EventStatus.PUBLISHED)
    values.update(kwargs)
    value = CulturalEvent(**values)
    db.session.add(value)
    db.session.commit()
    return value


def admin_payload(**kwargs):
    values = dict(title='Evento administrativo', locality='Minas', event_date='2099-12-31', description='Descripción del evento administrativo.', category='Música')
    values.update(kwargs)
    return values


def test_submission_persists_and_queues_both_notifications(client, payload, monkeypatch):
    deliver = Mock(side_effect=OSError('SMTP down'))
    monkeypatch.setattr(mail_service, 'deliver', deliver)
    response = client.post('/api/event-submissions', data=payload)
    assert response.status_code == 201
    assert response.json['submission_code'].startswith('EVT-')
    assert EventSubmission.query.one().links == payload['links']
    assert OutboxEmail.query.count() == 2
    assert all('31/12/2099' in item.html for item in OutboxEmail.query.all())
    deliver.assert_not_called()
    process_outbox()
    assert all(item.attempts == 1 and item.sent_at is None for item in OutboxEmail.query.all())
    assert EventSubmission.query.count() == 1
    monkeypatch.setattr(mail_service, 'deliver', Mock())
    for item in OutboxEmail.query.all():
        item.next_attempt_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    process_outbox()
    assert all(item.sent_at and item.attempts == 2 for item in OutboxEmail.query.all())
    assert process_outbox() == 0


def test_submission_retry_is_idempotent(client, payload):
    headers = {'Idempotency-Key': '12345678-1234-1234-1234-123456789abc'}
    first = client.post('/api/event-submissions', json=payload, headers=headers)
    second = client.post('/api/event-submissions', json=payload, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json == second.json
    assert EventSubmission.query.count() == 1
    assert OutboxEmail.query.count() == 2
    payload['event_name'] = 'Otro evento'
    assert client.post('/api/event-submissions', json=payload, headers=headers).status_code == 409


@pytest.mark.parametrize('field,value', [('full_name','  '), ('email','bad'), ('email_confirm','otro@example.com'),
    ('event_name','ab'), ('locality','Montevideo'), ('event_date','2000-01-01'), ('event_date','2099-02-30'),
    ('event_date','2099-12-31T20:00:00'), ('event_date',1234), ('description','short'),
    ('description','a'*5001), ('phone','x'*51), ('address','x'*256), ('links','x'*1001),
    ('captcha_answer','8'), ('captcha_answer','7abc'), ('email',None), ('full_name',{}),
    ('event_name','<b></b>'), ('email','x'*256+'@example.com')])
def test_invalid_submission_never_persists(client, payload, field, value):
    payload[field] = value
    response = client.post('/api/event-submissions', json=payload)
    assert response.status_code == 400, response.json
    assert EventSubmission.query.count() == OutboxEmail.query.count() == 0


@pytest.mark.parametrize('payload', [[], ['a'], 'string', 123, True])
@pytest.mark.parametrize('path', ['/api/event-submissions','/api/contact-messages'])
def test_non_object_json_is_400(client, path, payload):
    assert client.post(path, json=payload).status_code == 400


def test_aliases_and_email_normalization(client, payload):
    payload['eventName'] = payload.pop('event_name')
    payload['datetime'] = payload.pop('event_date')
    payload['emailConfirm'] = payload.pop('email_confirm')
    payload['email'] = ' PERSONA@example.com '
    assert client.post('/api/event-submissions', json=payload).status_code == 201
    assert EventSubmission.query.one().email == 'persona@example.com'


def test_images_valid_invalid_and_storage_failure(client, payload, monkeypatch):
    upload = Mock(return_value=dict(object_key='event-submissions/test/a.png', file_name='a.png', content_type='image/png', size_bytes=100))
    monkeypatch.setattr(minio_service, 'upload_event_image', upload)
    assert client.post('/api/event-submissions', data={**payload, 'image': (BytesIO(b'bad'), 'bad.png')}).status_code == 400
    upload.assert_not_called()
    upload.side_effect = StorageError('unavailable')
    assert client.post('/api/event-submissions', data={**payload, 'image': (png(), 'good.png')}).status_code == 500
    assert EventSubmission.query.count() == 0
    upload.side_effect = None
    assert client.post('/api/event-submissions', data={**payload, 'image': (png(), 'good.png')}).status_code == 201
    assert EventSubmission.query.one().image_object_key.endswith('a.png')


def test_payload_limit_returns_json(client):
    response = client.post('/api/event-submissions', data=b'x'*(5*1024*1024+1), content_type='application/json')
    assert response.status_code == 413
    assert response.is_json


def test_date_window_inclusive_and_archive(client, monkeypatch):
    from app.routes.public import routes
    today = date(2026, 9, 23)
    monkeypatch.setattr(routes, 'local_today', lambda: today)
    for offset in [-1, 0, 15, 16]:
        event(title=str(offset), event_date=today+timedelta(days=offset))
    event(title='Archived', event_date=today, status=EventStatus.ARCHIVED)
    response = client.get('/api/events')
    assert [item['title'] for item in response.json] == ['0','15']
    assert response.headers['Cache-Control'] == 'no-store'
    assert [item['title'] for item in client.get('/api/events?all=true').json] == ['0','15','16']
    monkeypatch.setattr(routes, 'local_today', lambda: today+timedelta(days=1))
    assert [item['title'] for item in client.get('/api/events').json] == ['15','16']


def test_uruguay_midnight(app, monkeypatch):
    from app.utils import dates
    class Clock:
        @staticmethod
        def now(zone):
            from datetime import timezone
            return datetime(2026, 9, 24, 2, 59, tzinfo=timezone.utc).astimezone(zone)
    monkeypatch.setattr(dates, 'datetime', Clock)
    assert dates.local_today() == date(2026, 9, 23)


@pytest.mark.parametrize('path', ['/admin/dashboard','/admin/events','/admin/events/create','/admin/event-submissions',
    '/admin/contact-messages','/admin/agenda','/admin/email/send','/admin/email/logs','/admin/email/received','/admin/email/queue','/admin/logs','/admin/logs/export'])
def test_admin_pages_render_and_require_login(client, path, admin):
    assert client.get(path).status_code == 200
    with client.session_transaction() as session:
        session.clear()
    assert client.get(path).status_code == 302


def test_full_submission_publish_edit_archive_delete(client, payload, admin):
    assert client.post('/api/event-submissions', data=payload).status_code == 201
    submission = EventSubmission.query.one()
    assert client.get(f'/admin/event-submissions/{submission.id}').status_code == 200
    assert client.get(f'/admin/events/create?submission_id={submission.id}').status_code == 200
    fields = admin_payload(submission_id=submission.id)
    assert client.post('/admin/events/create', data=fields).status_code == 302
    published_id = submission.published_event_id
    assert submission.status == SubmissionStatus.APPROVED
    assert len(client.get('/api/events?all=true').json) == 1
    # Repeat publication must not create another event.
    assert client.post('/admin/events/create', data=fields).status_code == 302
    assert CulturalEvent.query.count() == 1
    assert client.get(f'/admin/events/{published_id}/edit').status_code == 200
    assert client.post(f'/admin/events/{published_id}/edit', data=admin_payload(title='Editado')).status_code == 302
    assert client.get('/api/events?all=true').json[0]['title'] == 'Editado'
    assert client.post(f'/admin/events/{published_id}/archive').status_code == 302
    assert client.get('/api/events?all=true').json == []
    assert client.post(f'/admin/events/{published_id}/publish').status_code == 302
    assert client.post(f'/admin/events/{published_id}/delete').status_code == 302
    assert CulturalEvent.query.count() == 0
    assert submission.published_event_id is None
    assert submission.status == SubmissionStatus.NEW


@pytest.mark.parametrize('field,value', [('title',' '), ('locality','Wrong'), ('event_date','2000-01-01'), ('description','short'),('category','x'*101)])
def test_admin_validation_does_not_create(client, admin, field, value):
    response = client.post('/admin/events/create', data=admin_payload(**{field:value}))
    assert response.status_code == 200
    assert CulturalEvent.query.count() == 0


def test_admin_image_failure_does_not_create_or_edit(client, admin, monkeypatch):
    upload = Mock(side_effect=StorageError('down'))
    monkeypatch.setattr(minio_service, 'upload_cultural_event_image', upload)
    assert client.post('/admin/events/create', data=admin_payload(image=(png(),'ok.png'))).status_code == 503
    assert CulturalEvent.query.count() == 0
    value = event()
    assert client.post(f'/admin/events/{value.id}/edit', data=admin_payload(image=(png(),'ok.png'))).status_code == 503
    assert db.session.get(CulturalEvent, value.id).title == 'Evento público'
    assert client.post('/admin/events/create', data=admin_payload(image=(BytesIO(b'bad'),'ok.png'))).status_code == 200
    assert upload.call_count == 2


def test_submission_status_requires_note_and_publication(client, admin, payload):
    client.post('/api/event-submissions', data=payload)
    submission = EventSubmission.query.one()
    url = f'/admin/event-submissions/{submission.id}/update'
    client.post(url, data={'status':'APPROVED'})
    assert submission.status == SubmissionStatus.NEW
    client.post(url, data={'status':'REJECTED'})
    assert submission.status == SubmissionStatus.NEW
    client.post(url, data={'status':'REJECTED','note':'Fuera del alcance cultural'})
    assert submission.status == SubmissionStatus.REJECTED


def test_contacts_duplicates_email_success_and_failure(client, admin, monkeypatch):
    data = dict(name='Contacto',email='actor@example.com')
    assert client.post('/admin/agenda', data=data).status_code == 302
    response = client.post('/admin/agenda', data=data)
    assert response.status_code == 200
    assert b'Ya existe' in response.data
    contact = Contact.query.one()
    fields = dict(contact_id=contact.id,subject='Asunto',message='Contenido del correo')
    monkeypatch.setattr(mail_service,'deliver',Mock(side_effect=OSError('SMTP down')))
    assert client.post('/admin/email/send', data=fields).status_code == 200
    assert EmailLog.query.count() == 0
    monkeypatch.setattr(mail_service,'deliver',Mock())
    assert client.post('/admin/email/send', data=fields).status_code == 302
    assert EmailLog.query.count() == 1


def test_contact_reply_and_submission_reply(client, payload, admin, monkeypatch):
    assert client.post('/api/contact-messages', json=dict(full_name='Persona',email='p@example.com',message='Consulta de prueba')).status_code == 201
    message = ContactMessage.query.one()
    assert client.get(f'/admin/contact-messages/{message.id}').status_code == 200
    fields = dict(subject='Respuesta',message='Respondemos a su consulta')
    monkeypatch.setattr(mail_service,'deliver',Mock(side_effect=OSError()))
    client.post(f'/admin/contact-messages/{message.id}/reply',data=fields)
    assert message.status == MessageStatus.NEW
    monkeypatch.setattr(mail_service,'deliver',Mock())
    client.post(f'/admin/contact-messages/{message.id}/reply',data=fields)
    assert message.status == MessageStatus.REPLIED
    payload['full_name']='a'*120
    client.post('/api/event-submissions',data=payload)
    submission=EventSubmission.query.one()
    client.post(f'/admin/event-submissions/{submission.id}/reply',data=fields)
    assert EmailLog.query.count() == 2


def test_admin_role_and_inactive_user(client, admin):
    admin.is_superuser=False
    db.session.commit()
    for path in ['/admin/logs','/admin/logs/export','/admin/email/logs','/admin/email/received']:
        assert client.get(path).status_code == 403
    assert client.post('/admin/email/sync').status_code == 403
    admin.is_active=False
    db.session.commit()
    assert client.get('/admin/dashboard').status_code == 302


def test_two_factor_login_replay_and_logout(client, monkeypatch):
    user=User(email='user@example.com',username='user',password_hash=hash_password('Password-123'),is_active=True)
    db.session.add(user); db.session.commit()
    import importlib
    monkeypatch.setattr(importlib.import_module('app.services.mail_service'), 'generate_random_code',lambda **kw:'123456')
    monkeypatch.setattr(mail_service,'deliver',Mock())
    client.get('/admin/login')
    with client.session_transaction() as session:
        answer=session['captcha_answer']
    response=client.post('/admin/login',data=dict(email=user.email,password='Password-123',captcha=str(answer)))
    assert response.status_code == 302 and '/2fa' in response.location
    assert client.get('/admin/dashboard').status_code == 302
    assert client.post('/admin/2fa',data={'code':'123456'}).status_code == 302
    assert client.get('/admin/dashboard').status_code == 200
    assert not auth_service.verify_2fa_code(user,'123456')
    assert client.get('/admin/logout').status_code == 405
    assert client.post('/admin/logout').status_code == 302
    assert client.get('/admin/dashboard').status_code == 302


def test_two_factor_delivery_failure_and_attempt_lockout(admin, monkeypatch):
    monkeypatch.setattr(mail_service,'deliver',Mock(side_effect=OSError()))
    with pytest.raises(ValueError):
        auth_service.generate_and_send_2fa(admin,mail_service)
    assert TwoFactorCode.query.count() == 0
    code=TwoFactorCode(user_id=admin.id,code_hash=hash_code('123456'),expires_at=utcnow()+timedelta(minutes=1))
    db.session.add(code);db.session.commit()
    for _ in range(5):
        assert not auth_service.verify_2fa_code(admin,'000000')
    assert not auth_service.verify_2fa_code(admin,'123456')


def test_csrf_enforced_on_mutations(app, client, admin):
    app.config['WTF_CSRF_ENABLED']=True
    value=event()
    assert client.post(f'/admin/events/{value.id}/delete').status_code == 400
    assert CulturalEvent.query.count() == 1
    assert client.post('/admin/logout').status_code == 400


def test_media_access_and_storage_failure(client, monkeypatch):
    monkeypatch.setattr(minio_service,'get_file_content',Mock(return_value=png().getvalue()))
    assert client.get('/media/event-submissions/private.png').status_code == 404
    value=event(image_object_key='event-submissions/public.png')
    assert client.get('/media/event-submissions/public.png').status_code == 200
    value.status=EventStatus.ARCHIVED;db.session.commit()
    assert client.get('/media/event-submissions/public.png').status_code == 404


def test_health(client):
    assert client.get('/healthz').json == {'status':'ok'}
    assert client.get('/admin').status_code == 302
    assert client.get('/admin/').status_code == 302


def test_notification_retry_and_permissions(client, admin):
    entry=OutboxEmail(recipient='actor@example.com',subject='Aviso',html='Aviso',next_attempt_at=utcnow()+timedelta(hours=1),last_error='OSError')
    db.session.add(entry);db.session.commit()
    assert client.post(f'/admin/email/queue/{entry.id}/retry').status_code == 302
    assert entry.next_attempt_at <= utcnow()
    admin.is_superuser=False;db.session.commit()
    assert client.get('/admin/email/queue').status_code == 403
    assert client.post(f'/admin/email/queue/{entry.id}/retry').status_code == 403


@pytest.mark.parametrize('closed_status', [SubmissionStatus.REJECTED, SubmissionStatus.ARCHIVED])
def test_closed_submission_cannot_be_published_from_stale_form(client, admin, payload, closed_status):
    client.post('/api/event-submissions', data=payload)
    submission = EventSubmission.query.one()
    assert client.get(f'/admin/events/create?submission_id={submission.id}').status_code == 200
    client.post(f'/admin/event-submissions/{submission.id}/update',
                data={'status': closed_status.value, 'note': 'No corresponde publicar.'})
    response = client.post('/admin/events/create', data=admin_payload(submission_id=submission.id))
    assert response.status_code == 302
    assert CulturalEvent.query.count() == 0
    assert submission.status == closed_status
    assert submission.published_event_id is None
    assert client.get(f'/admin/events/create?submission_id={submission.id}').status_code == 302


def test_closed_submission_cannot_be_reopened_from_stale_form(client, admin, payload):
    client.post('/api/event-submissions', data=payload)
    submission = EventSubmission.query.one()
    url = f'/admin/event-submissions/{submission.id}/update'
    client.post(url, data={'status': 'REJECTED', 'note': 'No corresponde publicar.'})
    client.post(url, data={'status': 'NEW', 'note': 'Formulario anterior.'})
    assert submission.status == SubmissionStatus.REJECTED
    assert submission.admin_note == 'No corresponde publicar.'


def test_archived_event_is_not_reported_as_published(client, admin, payload):
    client.post('/api/event-submissions', data=payload)
    submission = EventSubmission.query.one()
    client.post('/admin/events/create', data=admin_payload(submission_id=submission.id))
    client.post(f'/admin/events/{submission.published_event_id}/archive')
    response = client.get(f'/admin/event-submissions/{submission.id}')
    assert 'Ya aprobado y publicado' not in response.text
    assert 'Evento archivado' in response.text
    response = client.post(f'/admin/event-submissions/{submission.id}/update',
                           data={'status': 'APPROVED'}, follow_redirects=True)
    assert 'publicar el evento vinculado' in response.text
    assert submission.published_event.status == EventStatus.ARCHIVED


def test_notification_subject_accepts_multiline_event_name(client, payload, monkeypatch):
    from flask_mail import Message
    payload['event_name'] = 'Festival cultural\r\nEdición primavera'
    assert client.post('/api/event-submissions', data=payload).status_code == 201
    entries = OutboxEmail.query.all()
    for entry in entries:
        assert not Message(entry.subject, recipients=[entry.recipient], html=entry.html).has_bad_headers()
    monkeypatch.setattr(mail_service, 'deliver', Mock())
    process_outbox()
    assert all(entry.sent_at for entry in entries)


def test_return_to_review_unpublishes_the_linked_event(client, admin, payload):
    client.post('/api/event-submissions', data=payload)
    submission = EventSubmission.query.one()
    client.post('/admin/events/create', data=admin_payload(submission_id=submission.id))
    client.post(f'/admin/event-submissions/{submission.id}/update', data={'status': 'NEW'})
    assert submission.status == SubmissionStatus.NEW
    assert client.get('/api/events?all=true').json == []
    client.post(f'/admin/events/{submission.published_event_id}/publish')
    assert submission.status == SubmissionStatus.APPROVED
    assert len(client.get('/api/events?all=true').json) == 1


@pytest.mark.parametrize('closed_status', [SubmissionStatus.REJECTED, SubmissionStatus.ARCHIVED])
def test_closed_submission_event_cannot_be_republished(client, admin, payload, closed_status):
    client.post('/api/event-submissions', data=payload)
    submission = EventSubmission.query.one()
    client.post('/admin/events/create', data=admin_payload(submission_id=submission.id))
    client.post(f'/admin/event-submissions/{submission.id}/update',
                data={'status': closed_status.value, 'note': 'No corresponde publicar.'})
    client.post(f'/admin/events/{submission.published_event_id}/publish')
    assert submission.status == closed_status
    assert submission.published_event.status == EventStatus.ARCHIVED
    assert client.get('/api/events?all=true').json == []


@pytest.mark.parametrize('closed_status', [SubmissionStatus.REJECTED, SubmissionStatus.ARCHIVED])
def test_deleting_a_closed_submission_event_preserves_the_decision(client, admin, payload, closed_status):
    client.post('/api/event-submissions', data=payload)
    submission = EventSubmission.query.one()
    client.post('/admin/events/create', data=admin_payload(submission_id=submission.id))
    client.post(f'/admin/event-submissions/{submission.id}/update',
                data={'status': closed_status.value, 'note': 'No corresponde publicar.'})
    client.post(f'/admin/events/{submission.published_event_id}/delete')
    assert submission.published_event_id is None
    assert submission.status == closed_status
    assert submission.admin_note == 'No corresponde publicar.'
    client.post('/admin/events/create', data=admin_payload(submission_id=submission.id))
    assert CulturalEvent.query.count() == 0


def test_rejection_database_failure_does_not_delete_the_received_image(client, admin, payload, monkeypatch):
    from sqlalchemy.exc import OperationalError
    client.post('/api/event-submissions', data=payload)
    submission = EventSubmission.query.one()
    submission.image_object_key = 'event-submissions/test/image.png'
    db.session.commit()
    delete = Mock()
    monkeypatch.setattr(minio_service, 'delete_file', delete)
    monkeypatch.setattr(db.session, 'commit', Mock(side_effect=OperationalError('update', {}, OSError())))
    response = client.post(f'/admin/event-submissions/{submission.id}/update',
                           data={'status': 'REJECTED', 'note': 'No corresponde publicar.'})
    assert response.status_code == 503
    delete.assert_not_called()
    assert submission.status == SubmissionStatus.NEW
    assert submission.image_object_key == 'event-submissions/test/image.png'


def test_rejection_storage_cleanup_failure_keeps_the_decision_and_records_the_file(client, admin, payload, monkeypatch):
    from app.models.audit import ActivityLog
    client.post('/api/event-submissions', data=payload)
    submission = EventSubmission.query.one()
    submission.image_object_key = 'event-submissions/test/image.png'
    db.session.commit()
    monkeypatch.setattr(minio_service, 'delete_file', Mock(side_effect=StorageError('down')))
    response = client.post(f'/admin/event-submissions/{submission.id}/update',
                           data={'status': 'REJECTED', 'note': 'No corresponde publicar.'}, follow_redirects=True)
    assert response.status_code == 200
    assert submission.status == SubmissionStatus.REJECTED
    assert 'imagen del almacenamiento' in response.text
    audit = ActivityLog.query.filter_by(action='UPDATE_EVENT_SUBMISSION').one()
    assert 'event-submissions/test/image.png' in audit.details
