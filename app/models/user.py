from app.utils.dates import utcnow
from datetime import datetime
from flask_login import UserMixin
from app.extensions import db


class User(UserMixin, db.Model):
    """
    Modelo de usuario administrador.
    
    Seguridad:
    - password_hash: Argon2 (u otro algoritmo robusto)
      via werkzeug o passlib externo.
      NUNCA guardar texto plano.
    - email: Indexed para búsquedas rápidas en login.
    - is_active: Para borrado lógico o bloqueo inmediato.
    """
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=True)
    email = db.Column(db.String(255), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_superuser = db.Column(db.Boolean, default=False, nullable=False)
    
    created_at = db.Column(db.DateTime, default=utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

    # Relaciones
    two_factor_codes = db.relationship(
        'TwoFactorCode',
        backref='user',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<User {self.username or self.email}>'


class TwoFactorCode(db.Model):
    """
    Códigos de verificación para 2FA o reseteo de password.
    
    Seguridad:
    - code_hash: NO guardamos el código real (ej: 123456) en la DB.
      Guardamos un hash para mitigar impacto si la DB es comprometida.
      Al validar, se hashea el input del usuario y se compara.
    - expires_at: Ventana de tiempo corta (ej: 5-10 min).
    - attempts: Rate limiting a nivel de DB para evitar fuerza bruta.
    - consumed_at: Para evitar replay attacks (reuso del código).
    """
    __tablename__ = 'two_factor_codes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id'),
        nullable=False,
        index=True
    )
    
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    
    attempts = db.Column(db.Integer, default=0)
    consumed_at = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=utcnow)
