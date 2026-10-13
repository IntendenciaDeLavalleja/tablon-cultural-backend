from pathlib import Path
from datetime import datetime, timedelta
import re
import pytest
from sqlalchemy import text, inspect
from flask_migrate import upgrade
from app import create_app
from app.extensions import db
from app.models.event import CulturalEvent
from app.models.user import User
from app.utils.security import hash_password


def test_fresh_migrations_and_model_schema_match(tmp_path):
    app = create_app('testing', {'SQLALCHEMY_DATABASE_URI': f'sqlite:///{tmp_path / "migrations.db"}'})
    with app.app_context():
        upgrade(directory=str(Path(__file__).resolve().parents[1] / 'migrations'))
        inspector = inspect(db.engine)
        for table in db.metadata.sorted_tables:
            assert table.name in inspector.get_table_names()
            assert {c.name for c in table.columns} == {c['name'] for c in inspector.get_columns(table.name)}
        assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar() == 'a83bd5e91200'


@pytest.mark.parametrize('legacy_date,valid', [('2026-09-23',True), ('Viernes de noche',False)])
def test_migration_preserves_existing_dates_or_stops_before_loss(tmp_path, legacy_date, valid):
    app = create_app('testing', {'SQLALCHEMY_DATABASE_URI': f'sqlite:///{tmp_path / "legacy.db"}'})
    directory = str(Path(__file__).resolve().parents[1] / 'migrations')
    with app.app_context():
        upgrade(directory=directory, revision='d6d3c6d243b2')
        db.session.execute(text("INSERT INTO cultural_events (id,title,locality,datetime_text,description,status) VALUES (1,'Evento','Minas',:value,'Descripción','PUBLISHED')"), {'value':legacy_date})
        db.session.commit()
        if valid:
            upgrade(directory=directory)
            assert str(db.session.execute(text('SELECT event_date FROM cultural_events')).scalar()) == legacy_date
        else:
            with pytest.raises(SystemExit) as failure:
                upgrade(directory=directory)
            assert failure.value.code == 1
            assert db.session.execute(text('SELECT datetime_text FROM cultural_events')).scalar() == legacy_date
            assert 'event_date' not in {c['name'] for c in inspect(db.engine).get_columns('cultural_events')}


def test_rendered_archive_publish_delete_forms_have_working_csrf(client, app):
    app.config['WTF_CSRF_ENABLED'] = True
    user=User(username='csrf',email='csrf@example.com',password_hash=hash_password('password'),is_active=True,is_superuser=True)
    value=CulturalEvent(title='Prueba',locality='Minas',event_date=(datetime.now()+timedelta(days=2)).date(),description='Texto cultural')
    db.session.add_all([user,value]);db.session.commit()
    with client.session_transaction() as session:
        session['_user_id']=str(user.id)
        session['_fresh']=True
    for action in ['archive','publish','delete']:
        html=client.get('/admin/events').text
        form=re.search(r'<form[^>]+action="/admin/events/'+str(value.id)+'/'+action+r'"[^>]*>(.*?)</form>',html,re.S)
        assert form, action
        token=re.search(r'name="csrf_token" value="([^"]+)"',form[1])
        assert token, action
        assert client.post(f'/admin/events/{value.id}/{action}',data={'csrf_token':token[1]}).status_code == 302


def test_rate_limit_is_per_client_and_returns_retry_header():
    app=create_app('testing',{'RATELIMIT_ENABLED':True})
    with app.app_context():
        db.create_all()
        client=app.test_client()
        for _ in range(8):
            assert client.post('/api/event-submissions',json={},environ_base={'REMOTE_ADDR':'192.0.2.1'}).status_code == 400
        response=client.post('/api/event-submissions',json={},environ_base={'REMOTE_ADDR':'192.0.2.1'})
        assert response.status_code == 429
        assert int(response.headers['Retry-After']) >= 0
        assert client.post('/api/event-submissions',json={},environ_base={'REMOTE_ADDR':'192.0.2.2'}).status_code == 400
        db.drop_all()


def test_proxy_https_does_not_redirect_forever():
    app=create_app('testing',{'FORCE_HTTPS':True,'TRUSTED_PROXY_COUNT':2})
    client=app.test_client()
    # Do not hit DB: login form confirms scheme and session settings behind two proxies.
    response=client.get('/admin/login',headers={'X-Forwarded-Proto':'https','X-Forwarded-For':'192.0.2.10, 172.18.0.4'})
    assert response.status_code == 200
    assert client.get('/admin/login').status_code in (301,302)


def test_audit_log_values_are_not_javascript(client):
    from app.models.audit import ActivityLog
    user=User(username='audit',email='audit@example.com',password_hash=hash_password('password'),is_active=True,is_superuser=True)
    db.session.add(user);db.session.flush()
    db.session.add(ActivityLog(user_id=user.id,username=user.username,action='CREATE_EVENT',details='${alert(1)} ` <script>alert(2)</script>'))
    db.session.commit()
    with client.session_transaction() as session:
        session['_user_id']=str(user.id)
    response=client.get('/admin/logs')
    assert response.status_code == 200
    assert "onclick='alert(`" not in response.text
    assert '<script>alert(2)</script>' not in response.text
