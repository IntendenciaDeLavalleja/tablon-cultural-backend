"""Verify configured MinIO using temporary images and an in-memory database.

Reads .env, sends no mail and never modifies the configured database,
bucket policy, container or preexisting objects. Deletes only its own uploads.
"""
from io import BytesIO
from pathlib import Path
import argparse
import sys
import uuid

from dotenv import dotenv_values
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    args = parser.parse_args()
    values = dotenv_values(args.env_file)
    bucket = values.get('MINIO_BUCKET') or values.get('MINIO_BUCKET_NAME')
    assert all(values.get(k) for k in ('MINIO_ENDPOINT', 'MINIO_ACCESS_KEY', 'MINIO_SECRET_KEY')), 'Incomplete MinIO configuration'
    assert bucket, 'MINIO_BUCKET or MINIO_BUCKET_NAME is required'

    from flask import g
    from app import create_app
    from app.extensions import db
    from app.models.event import CulturalEvent, EventSubmission
    from app.models.enums import EventStatus, SubmissionStatus
    from app.models.outbox import OutboxEmail
    from app.models.user import User
    from app.services.minio_service import minio_service
    from app.utils.dates import local_today
    from app.utils.security import hash_password

    app = create_app('testing', {
        'MINIO_ENDPOINT': values['MINIO_ENDPOINT'],
        'MINIO_ACCESS_KEY': values['MINIO_ACCESS_KEY'],
        'MINIO_SECRET_KEY': values['MINIO_SECRET_KEY'],
        'MINIO_BUCKET': bucket,
        'MINIO_SECURE': values.get('MINIO_SECURE', 'true').lower() in ('true', '1', 't'),
        'MAIL_USE_TLS': False,
        'MAIL_USE_SSL': False,
    })
    assert app.config['SQLALCHEMY_DATABASE_URI'] == 'sqlite://'
    assert app.config['MAIL_SUPPRESS_SEND'] and not app.config['RATELIMIT_ENABLED']

    @app.before_request
    def clear_login_cache():
        g.pop('_login_user', None)

    storage = minio_service.client
    assert storage.bucket_exists(bucket), 'Configured bucket does not exist; nothing was created'

    def snapshot():
        return {obj.object_name: (obj.etag, obj.size) for obj in storage.list_objects(bucket, recursive=True)}

    before = snapshot()
    uploads = set()
    original_put = storage.put_object

    def track_upload(bucket_name, object_name, *a, **kw):
        assert bucket_name == bucket and object_name not in before
        uploads.add(object_name)
        return original_put(bucket_name, object_name, *a, **kw)

    storage.put_object = track_upload
    stream = BytesIO()
    Image.new('RGB', (20, 20), 'blue').save(stream, format='PNG')
    image_bytes = stream.getvalue()

    def image():
        return BytesIO(image_bytes), 'qa-verification.png'

    try:
        with app.app_context():
            db.create_all()
            user = User(username='isolated-qa', email='qa@example.com',
                        password_hash=hash_password(str(uuid.uuid4())), is_active=True, is_superuser=True)
            db.session.add(user)
            db.session.commit()
            admin = app.test_client()
            public = app.test_client()
            with admin.session_transaction() as session:
                session['_user_id'] = str(user.id)
                session['_fresh'] = True
            date = local_today().isoformat()
            fields = dict(full_name='Prueba aislada', email='qa@example.com', email_confirm='qa@example.com',
                          event_name='VerificaciÃ³n de MinIO existente', locality='Minas', event_date=date,
                          description='Prueba temporal de imÃ¡genes con base y correo aislados.',
                          captcha_question='3 + 4', captcha_answer='7')
            response = public.post('/api/event-submissions', data={**fields, 'image': image()},
                                   headers={'Idempotency-Key': str(uuid.uuid4())})
            assert response.status_code == 201, response.status_code
            received = EventSubmission.query.one()
            original_key = received.image_object_key
            assert received.status == SubmissionStatus.NEW
            assert OutboxEmail.query.count() == 2
            assert public.get(f'/media/{original_key}').status_code == 404
            assert admin.get(f'/media/{original_key}').data == image_bytes
            event_fields = dict(title=fields['event_name'], locality='Minas', event_date=date,
                                description=fields['description'], category='MÃºsica')
            response = admin.post('/admin/events/create', data={**event_fields, 'submission_id': received.id})
            assert response.status_code == 302
            event = CulturalEvent.query.one()
            assert event.status == EventStatus.PUBLISHED and received.status == SubmissionStatus.APPROVED
            assert event.image_object_key == original_key
            assert public.get(f'/media/{original_key}').data == image_bytes
            assert len(public.get('/api/events').json) == 1

            assert admin.post(f'/admin/events/{event.id}/edit', data={**event_fields, 'image': image()}).status_code == 302
            replacement = event.image_object_key
            assert replacement != original_key
            assert public.get(f'/media/{replacement}').data == image_bytes
            assert public.get(f'/media/{original_key}').status_code == 404
            assert admin.post(f'/admin/events/{event.id}/archive').status_code == 302
            assert public.get(f'/media/{replacement}').status_code == 404
            assert public.get('/api/events').json == []
            assert admin.post(f'/admin/events/{event.id}/publish').status_code == 302
            assert public.get(f'/media/{replacement}').data == image_bytes
            assert admin.post(f'/admin/events/{event.id}/delete').status_code == 302
            assert public.get(f'/media/{replacement}').status_code == 404

            response = public.post('/api/event-submissions', data={**fields, 'image': image()})
            assert response.status_code == 201
            rejected = EventSubmission.query.order_by(EventSubmission.id.desc()).first()
            rejected_key = rejected.image_object_key
            assert admin.post(f'/admin/event-submissions/{rejected.id}/update',
                              data={'status': 'REJECTED', 'note': 'Prueba temporal de rechazo.'}).status_code == 302
            assert rejected.status == SubmissionStatus.REJECTED and rejected.image_object_key is None
            assert rejected_key not in snapshot()
            assert public.get(f'/media/{rejected_key}').status_code == 404

            assert admin.post('/admin/events/create', data={**event_fields, 'image': image()}).status_code == 302
            direct = CulturalEvent.query.one()
            assert direct.status == EventStatus.PUBLISHED
            assert public.get(f'/media/{direct.image_object_key}').data == image_bytes
            assert len(public.get('/api/events').json) == 1
            assert admin.post(f'/admin/events/{direct.id}/delete').status_code == 302
            db.session.remove()
            db.drop_all()
        print('PASS: submission, private preview, publication, replacement, archive, republication, deletion, rejection and direct creation with configured MinIO.')
    finally:
        storage.put_object = original_put
        for key in uploads:
            assert key not in before
            storage.remove_object(bucket, key)
        after = snapshot()
        assert after == before, 'Storage contents changed beyond temporary verification objects'
        print(f'PASS: {len(uploads)} temporary images removed; {len(before)} preexisting objects unchanged. No database changes or mail sent.')


if __name__ == '__main__':
    main()
