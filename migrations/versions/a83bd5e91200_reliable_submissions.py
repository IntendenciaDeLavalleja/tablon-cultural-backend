"""Durable email notifications, submission retry protection and field sizes."""
from alembic import op
import sqlalchemy as sa

revision = 'a83bd5e91200'
down_revision = '607d234605dd'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('event_submissions') as batch:
        batch.add_column(sa.Column('idempotency_key', sa.String(64)))
        batch.add_column(sa.Column('request_digest', sa.String(64)))
        batch.create_unique_constraint('uq_submission_idempotency', ['idempotency_key'])
    with op.batch_alter_table('sent_emails') as batch:
        batch.alter_column('recipient_name', existing_type=sa.String(100), type_=sa.String(120), existing_nullable=False)
    op.create_table('outbox_emails',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('recipient', sa.String(255), nullable=False),
        sa.Column('subject', sa.String(255), nullable=False),
        sa.Column('html', sa.Text, nullable=False),
        sa.Column('attempts', sa.Integer, nullable=False),
        sa.Column('next_attempt_at', sa.DateTime, nullable=False),
        sa.Column('sent_at', sa.DateTime),
        sa.Column('last_error', sa.String(500)),
        sa.Column('created_at', sa.DateTime, nullable=False))
    op.create_index('ix_outbox_emails_next_attempt_at', 'outbox_emails', ['next_attempt_at'])


def downgrade():
    op.drop_table('outbox_emails')
    with op.batch_alter_table('event_submissions') as batch:
        batch.drop_constraint('uq_submission_idempotency', type_='unique')
        batch.drop_column('request_digest')
        batch.drop_column('idempotency_key')
