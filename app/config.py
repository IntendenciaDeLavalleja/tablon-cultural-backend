import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # Core Flask
    SECRET_KEY = os.environ.get('SECRET_KEY')
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI') or os.environ.get('DATABASE_URI')
    if SQLALCHEMY_DATABASE_URI:
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace('mariadb+mariadbconnector://', 'mysql+pymysql://').replace('mysql+mariadbconnector://', 'mysql+pymysql://')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True, 'pool_recycle': 280}
    RATELIMIT_STORAGE_URI = os.environ.get('REDIS_URL', 'memory://')
    RATELIMIT_HEADERS_ENABLED = True
    RATELIMIT_IN_MEMORY_FALLBACK_ENABLED = True
    TRUSTED_PROXY_COUNT = int(os.environ.get('TRUSTED_PROXY_COUNT', '0'))
    EVENT_TIMEZONE = 'America/Montevideo'
    FORCE_HTTPS = os.environ.get('FORCE_HTTPS', 'true').lower() == 'true'
    ADMIN_NOTIFICATION_EMAIL = os.environ.get('ADMIN_NOTIFICATION_EMAIL')
    IMAP_SERVER = os.environ.get('IMAP_SERVER')
    IMAP_PORT = int(os.environ.get('IMAP_PORT', '993'))

    # Mail
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'False').lower() in ('true', '1', 't')
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False').lower() in ('true', '1', 't')
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')

    # MinIO
    MINIO_ENDPOINT = os.environ.get('MINIO_ENDPOINT')
    MINIO_ACCESS_KEY = os.environ.get('MINIO_ACCESS_KEY')
    MINIO_SECRET_KEY = os.environ.get('MINIO_SECRET_KEY')
    MINIO_BUCKET = os.environ.get('MINIO_BUCKET') or os.environ.get('MINIO_BUCKET_NAME')
    MINIO_SECURE = os.environ.get('MINIO_SECURE', 'True').lower() in ('true', '1', 't')
    MINIO_PUBLIC_BASE_URL = os.environ.get('MINIO_PUBLIC_BASE_URL')

    # Security Defaults
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # Max 5MB upload/payload

class DevelopmentConfig(Config):
    DEBUG = True
    # Rate Limiting - Memory storage for development
    RATELIMIT_STORAGE_URL = "memory://"
    
    # Looser security for dev
    SESSION_COOKIE_SECURE = False
    FORCE_HTTPS = False

class ProductionConfig(Config):
    DEBUG = False
    
    # Rate Limiting - Redis recommended for production
    # RATELIMIT_STORAGE_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
    
    # Security - HSTS & HTTPS
    SESSION_COOKIE_SECURE = Config.FORCE_HTTPS
    REMEMBER_COOKIE_SECURE = Config.FORCE_HTTPS
    PREFERRED_URL_SCHEME = 'https'

class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = 'isolated-test-secret'
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    RATELIMIT_STORAGE_URI = 'memory://'
    MAIL_SUPPRESS_SEND = True
    MAIL_DEFAULT_SENDER = 'cultura@example.com'
    ADMIN_NOTIFICATION_EMAIL = 'admin@example.com'
    MINIO_ENDPOINT = None
    FORCE_HTTPS = False
    SESSION_COOKIE_SECURE = False
    TRUSTED_PROXY_COUNT = 0

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
