"""Generate local QA secrets and add missing QA configuration without replacing values."""
from pathlib import Path
import secrets

root=Path(__file__).resolve().parents[2]
path=root/'.env.test'
if not path.exists():
    path.write_text('\n'.join(f'{name}={secrets.token_hex(32)}' for name in (
        'SECRET_KEY','DB_PASSWORD','DB_ROOT_PASSWORD','MINIO_PASSWORD')) + '''
SITE_URL=http://localhost:8088
MAIL_SERVER=mailpit
MAIL_DEFAULT_SENDER=cultura@example.com
ADMIN_NOTIFICATION_EMAIL=admin@example.com
''', encoding='utf-8')
existing = path.read_text(encoding='utf-8')
names = {line.partition('=')[0].strip() for line in existing.splitlines() if '=' in line}
defaults = {
    'MINIO_ENDPOINT': 'minio:9000',
    'MINIO_ACCESS_KEY': 'tablon-storage',
    'MINIO_SECRET_KEY': '${MINIO_PASSWORD}',
    'MINIO_BUCKET_NAME': 'cultural-images',
    'MINIO_SECURE': 'false',
}
missing = [f'{name}={value}' for name, value in defaults.items() if name not in names]
if missing:
    with path.open('a', encoding='utf-8') as stream:
        stream.write('\n' + '\n'.join(missing) + '\n')
print('Local QA environment ready.')
