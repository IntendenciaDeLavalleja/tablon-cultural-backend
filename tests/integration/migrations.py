"""Test fresh and legacy migrations in a disposable MariaDB, never the QA database."""
from pathlib import Path
import subprocess
import time
import uuid


def run(*args, stdin=None):
    result = subprocess.run(args, input=stdin, text=True, encoding='utf-8', capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr + result.stdout)
    return result.stdout.strip()


CHECKS = r'''
from pathlib import Path
import pymysql
from flask_migrate import upgrade
from sqlalchemy import inspect, text
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app import create_app
from app.extensions import db

host = 'MIGRATION_HOST'
connection = pymysql.connect(host=host, user='root')
with connection.cursor() as cursor:
    for name in ('fresh', 'legacy', 'invalid'):
        cursor.execute(f'CREATE DATABASE {name} CHARACTER SET utf8mb4')
connection.close()
for name in ('fresh', 'legacy', 'invalid'):
    app = create_app('testing', {'SQLALCHEMY_DATABASE_URI': f'mysql+pymysql://root@{host}/{name}?charset=utf8mb4'})
    with app.app_context():
        if name != 'fresh':
            upgrade(directory='/app/migrations', revision='d6d3c6d243b2')
            old_date = '2099-12-31' if name == 'legacy' else 'Viernes de noche'
            db.session.execute(text("INSERT INTO cultural_events (id,title,locality,datetime_text,description,status) VALUES (1,'Evento cultural','Minas',:value,'Descripción cultural','PUBLISHED')"), {'value': old_date})
            db.session.execute(text("INSERT INTO event_submissions (id,submission_code,full_name,email,event_name,locality,datetime_text,description,status) VALUES (1,'EVT-QA-LEGACY','Persona de prueba','qa@example.com','Evento cultural','Minas',:value,'Descripción cultural','NEW')"), {'value': old_date})
            db.session.commit()
        if name == 'invalid':
            try:
                upgrade(directory='/app/migrations')
            except SystemExit as exc:
                assert exc.code == 1
            else:
                raise AssertionError('An ambiguous historical date must stop the migration')
            for table in ('cultural_events', 'event_submissions'):
                assert 'event_date' not in {c['name'] for c in inspect(db.engine).get_columns(table)}
                assert db.session.execute(text(f'SELECT datetime_text FROM {table}')).scalar() == old_date
            print('PASS MariaDB ambiguous dates: migration stops before changing data', flush=True)
        else:
            upgrade(directory='/app/migrations')
            assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar() == 'a83bd5e91200'
            if name == 'legacy':
                for table in ('cultural_events', 'event_submissions'):
                    assert str(db.session.execute(text(f'SELECT event_date FROM {table}')).scalar()) == old_date
            with db.engine.connect() as sql_connection:
                differences = compare_metadata(MigrationContext.configure(sql_connection), db.metadata)
                assert not differences, differences
            print(f'PASS MariaDB {name} migration: data and model schema verified', flush=True)
'''


def main():
    root = Path(__file__).resolve().parents[2]
    assert (root / '.env.test').exists(), 'Create the isolated QA environment first'
    network = 'tablon-qa_default'
    run('docker', 'network', 'inspect', network)
    container_name = 'tablon-qa-migrations-' + uuid.uuid4().hex[:12]
    # No published port, persistent volume, institutional secret or production database.
    container_id = run('docker', 'run', '--detach', '--rm', '--network', network,
        '--name', container_name, '-e', 'MARIADB_ALLOW_EMPTY_ROOT_PASSWORD=1', 'mariadb:11.4')
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            result = subprocess.run(['docker', 'exec', container_id, 'healthcheck.sh',
                '--connect', '--innodb_initialized'], capture_output=True, timeout=10)
            if result.returncode == 0:
                break
            time.sleep(2)
        else:
            raise AssertionError('Disposable MariaDB did not become ready')
        print(run('docker', 'run', '--rm', '--network', network, '--entrypoint', 'python',
            '-i', 'tablon-qa-backend', '-', stdin=CHECKS.replace('MIGRATION_HOST', container_name)), flush=True)
    finally:
        run('docker', 'stop', container_id)


if __name__ == '__main__':
    main()
