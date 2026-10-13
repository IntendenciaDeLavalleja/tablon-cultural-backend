import click
import secrets
from flask.cli import with_appcontext
from app.extensions import db
from app.models.user import User
from app.utils.security import hash_password
from app.services.minio_service import minio_service

@click.command('create-admin')
@click.argument('username')
@click.argument('email')
@click.argument('password')
@click.argument('is_superuser', default='false')
@with_appcontext
def create_admin(username, email, password, is_superuser):
    """Crea un nuevo usuario administrador."""
    if User.query.filter_by(email=email).first():
        click.secho(f'Error: User {email} already exists.', fg='red')
        return
    if User.query.filter_by(username=username).first():
        click.secho(f'Error: Username {username} already exists.', fg='red')
        return

    is_super = str(is_superuser).lower() == 'true'

    try:
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            is_active=True,
            is_superuser=is_super
        )
        db.session.add(user)
        db.session.commit()
        role = 'Super Admin' if is_super else 'Admin'
        click.secho(f'{role} {username} created successfully.', fg='green')
    except Exception as e:
        db.session.rollback()
        click.secho(f'Error creating user: {e}', fg='red')

@click.command('rotate-secret')
def rotate_secret():
    """Genera un nuevo SECRET_KEY seguro."""
    click.secho('WARNING: Changing the secret key will invalidate all active sessions and signed tokens.', fg='yellow')
    click.echo('New Secret Key (copy to .env):')
    click.secho(secrets.token_hex(32), fg='green', bold=True)

@click.command('init-bucket')
@with_appcontext
def init_bucket():
    """Inicializa/Verifica el bucket de MinIO."""
    try:
        minio_service.ensure_bucket_exists()
        click.secho(f"Bucket '{minio_service.bucket_name}' verified/created successfully.", fg='green')
    except Exception as e:
        raise click.ClickException('No se pudo inicializar el almacenamiento.') from e
