import logging
import os
from flask import Flask
from .config import config
from .extensions import db, migrate, login_manager, csrf, mail, limiter, talisman, ma, cors
from .services.minio_service import minio_service
from .error_handlers import register_error_handlers
from .commands import create_admin, rotate_secret, init_bucket
import logging.config

def create_app(config_name=None, overrides=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])
    if overrides:
        app.config.update(overrides)
    if not app.config.get('SECRET_KEY'):
        raise ValueError('SECRET_KEY is required')
    if config_name == 'production' and len(app.config['SECRET_KEY']) < 32:
        raise ValueError('Production SECRET_KEY must contain at least 32 characters')
    from werkzeug.middleware.proxy_fix import ProxyFix
    proxies = app.config['TRUSTED_PROXY_COUNT']
    if proxies:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=1)

    if app.config.get('MAIL_USE_TLS') and app.config.get('MAIL_USE_SSL'):
        raise ValueError('Choose MAIL_USE_TLS or MAIL_USE_SSL, not both')

    # Configure Logging (Structured)
    if not app.debug:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(module)s: %(message)s',
            handlers=[logging.StreamHandler()]
        )
    else:
        logging.basicConfig(level=logging.DEBUG)

    # Initialize Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    mail.init_app(app)
    ma.init_app(app)
    limiter.init_app(app)
    
    # Configure CORS
    allowed_origins = [
        origin.strip() for origin in os.environ.get('CORS_ALLOWED_ORIGINS', 'http://localhost:4321,http://localhost:5173').split(',')
    ]
    cors.init_app(app, resources={r"/api/*": {
        "origins": allowed_origins,
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-Requested-With", "Idempotency-Key"]
    }}, supports_credentials=True)

    # Initialize Services
    minio_service.init_app(app)

    # Register Error Handlers
    register_error_handlers(app)

    # Register CLI Commands
    app.cli.add_command(create_admin)
    app.cli.add_command(rotate_secret)
    app.cli.add_command(init_bucket)

    # Login Manager Configuration
    login_manager.init_app(app)
    login_manager.login_view = 'admin.login' # Requires 'login' route in admin blueprint
    login_manager.login_message_category = 'info'

    # Talisman (Security Headers)
    # Define Content Security Policy
    csp = {
        'default-src': "'self'",
        'img-src': ["'self'", 'data:', 'https:'],
        'script-src': ["'self'", "'unsafe-inline'"],
        'style-src': ["'self'", "'unsafe-inline'"],
        'font-src': ["'self'"],
        'object-src': "'none'",
        'base-uri': "'self'",
        'form-action': "'self'",
    }

    force_https = app.config['FORCE_HTTPS']
    
    talisman.init_app(
        app, 
        content_security_policy=csp, 
        force_https=force_https,
        session_cookie_secure=app.config.get('SESSION_COOKIE_SECURE', False),
        force_https_permanent=True
    )

    # Register Blueprints
    from .routes.public import public_bp
    from .routes.admin import admin_bp
    
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    from .services.outbox_service import process_outbox_command
    app.cli.add_command(process_outbox_command)

    @app.get('/healthz')
    @talisman(force_https=False)
    def health():
        from sqlalchemy import text
        try:
            db.session.execute(text('SELECT 1'))
            return {'status': 'ok'}
        except Exception:
            db.session.rollback()
            return {'status': 'unavailable'}, 503

    # Context Processor for Templates
    from .models.enums import EVENT_STATUS_TRANSLATIONS, SUBMISSION_STATUS_TRANSLATIONS, MESSAGE_STATUS_TRANSLATIONS
    
    @app.context_processor
    def inject_enums():
        return dict(
            EVENT_STATUS_TRANSLATIONS=EVENT_STATUS_TRANSLATIONS,
            SUBMISSION_STATUS_TRANSLATIONS=SUBMISSION_STATUS_TRANSLATIONS,
            MESSAGE_STATUS_TRANSLATIONS=MESSAGE_STATUS_TRANSLATIONS
        )

    # Date Filter
    @app.template_filter('date_es')
    def date_es_filter(dt):
        if not dt: return ''
        months = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        time = f", {dt.strftime('%H:%M')}" if hasattr(dt, 'hour') else ''
        return f"{dt.day} de {months[dt.month-1]} de {dt.year}{time}"

    return app
