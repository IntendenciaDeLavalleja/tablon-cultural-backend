"""Disruption tests ONLY for the isolated tablon-qa Compose project.

No production environment is read. Run after the browser tests.
"""
import concurrent.futures
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import urllib.error
import uuid

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ['docker', 'compose', '--env-file', '.env.test', '-p', 'tablon-qa',
           '-f', 'compose.yaml', '-f', 'deploy/compose.test.yaml']
BASE = 'http://localhost:5000'


def compose(*args, stdin=None):
    result = subprocess.run(COMPOSE + list(args), cwd=ROOT, input=stdin, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def database(code):
    return compose('exec', '-T', 'backend', 'python', '-', stdin='from wsgi import app\nwith app.app_context():\n' + '\n'.join('    '+line for line in code.splitlines()))


def request(path, data=None, key=None):
    headers={'Content-Type':'application/json'}
    if key: headers['Idempotency-Key']=key
    req=urllib.request.Request(BASE+path, data=json.dumps(data).encode() if data else None, headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def submission(key=None, name='Evento de recuperaciÃ³n'):
    return request('/api/event-submissions',dict(full_name='Prueba de recuperaciÃ³n',email='recovery@example.com',
        email_confirm='recovery@example.com',event_name=name,locality='Minas',event_date='2099-12-31',
        description='Prueba aislada de recuperaciÃ³n de servicios.',captcha_question='3 + 4',captcha_answer='7'),key or str(uuid.uuid4()))


def until(fn, seconds=60):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        try:
            if fn(): return
        except (OSError, RuntimeError):
            pass
        time.sleep(2)
    raise AssertionError('Recovery deadline exceeded')


def main():
    assert (ROOT/'.env.test').exists(), 'Create the isolated test environment first'
    started=time.monotonic()
    # Exercise row locking with MariaDB, which SQLite unit tests cannot reproduce.
    publication = database('''from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from app.extensions import db
from app.models.user import User
from app.models.event import EventSubmission, CulturalEvent
from app.utils.dates import local_today
app.config['WTF_CSRF_ENABLED'] = False
admin_id = User.query.filter_by(email='qa@example.com', is_active=True).one().id
title = 'Concurrent publication ' + str(uuid4())
s = EventSubmission(submission_code='EVT-QA-' + str(uuid4()), full_name='QA concurrency',
    email='concurrency@example.com', event_name=title, locality='Minas',
    event_date=local_today(), description='Concurrent administrative publication test.')
db.session.add(s)
db.session.commit()
submission_id = s.id
fields = dict(submission_id=submission_id, title=title, locality='Minas',
    event_date=local_today().isoformat(), description='Concurrent administrative publication test.')
db.session.remove()
barrier = Barrier(2)
def publish(_):
    with app.test_client() as client:
        with client.session_transaction() as session:
            session['_user_id'] = str(admin_id)
            session['_fresh'] = True
        barrier.wait(timeout=10)
        return client.post('/admin/events/create', data=fields).status_code
with ThreadPoolExecutor(max_workers=2) as pool:
    statuses = list(pool.map(publish, range(2)))
assert statuses == [302, 302], statuses
submission = db.session.get(EventSubmission, submission_id)
events = CulturalEvent.query.filter_by(title=title).all()
assert len(events) == 1 and submission.published_event_id == events[0].id
db.session.delete(submission)
db.session.delete(events[0])
db.session.commit()
print('PASS concurrent administrative publication: one event')''')
    print(publication, flush=True)
    key=str(uuid.uuid4())
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:submission(key), range(4)))
    assert all(status == 201 for status, _ in results), results
    assert len({body['submission_code'] for _,body in results}) == 1
    count=database(f"from app.models.event import EventSubmission\nprint(EventSubmission.query.filter_by(idempotency_key='{key}').count())")
    assert count == '1', count
    print('PASS concurrent retries: one submission, one receipt',flush=True)

    try:
        compose('stop','mailpit')
        status, receipt=submission(name='Prueba SMTP caÃ­do')
        assert status == 201, receipt
        code=receipt['submission_code']
        lookup=f"from app.models.outbox import OutboxEmail\ne=OutboxEmail.query.filter(OutboxEmail.subject.contains('{code}')).one()\n"
        until(lambda: int(database(lookup+'print(e.attempts)')) >= 1,30)
        assert database(lookup+'print(e.sent_at is None)') == 'True'
        print('PASS SMTP outage: request persisted, notification pending',flush=True)
    finally:
        compose('start','mailpit')

    try:
        compose('stop','db')
        assert request('/healthz')[0] == 503
        assert request('/api/events')[0] == 503
    finally:
        compose('start','db')
    until(lambda: request('/api/events')[0] == 200,60)
    assert submission()[0] == 201
    print('PASS MariaDB outage and pool reconnection',flush=True)

    try:
        compose('stop','redis')
        assert request('/api/events')[0] == 200
        assert submission()[0] == 201
    finally:
        compose('start','redis')
    print('PASS Redis outage: fallback permits submissions',flush=True)

    until(lambda: database(lookup+'print(e.sent_at is not None)') == 'True',90)
    print('PASS automatic SMTP retry after recovery',flush=True)

    try:
        compose('stop','minio')
        assert request('/api/events')[0] == 200
        assert submission()[0] == 201
    finally:
        compose('start','minio')
    print('PASS storage outage: submissions without image stay available',flush=True)

    compose('restart','backend','mail-worker')
    until(lambda: request('/healthz')[0] == 200,60)
    status, repeated=submission(key)
    assert status == 201 and repeated['submission_code'] == results[0][1]['submission_code']
    print('PASS application restart: saved data and retry protection persist',flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        statuses=list(pool.map(lambda _:request('/api/events')[0],range(20)))
    assert statuses == [200]*20, statuses
    print(f'PASS 20 concurrent reads; recovery suite completed in {time.monotonic()-started:.1f}s',flush=True)


if __name__ == '__main__':
    main()
