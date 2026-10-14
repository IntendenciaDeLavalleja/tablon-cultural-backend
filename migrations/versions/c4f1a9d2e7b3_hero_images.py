"""Hero carousel images managed from the admin panel."""
from alembic import op
import sqlalchemy as sa

revision = 'c4f1a9d2e7b3'
down_revision = 'a83bd5e91200'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('hero_images',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('object_key', sa.String(255), nullable=False),
        sa.Column('file_name', sa.String(255)),
        sa.Column('content_type', sa.String(100)),
        sa.Column('size_bytes', sa.BigInteger),
        sa.Column('alt_text', sa.String(200), nullable=False),
        sa.Column('sort_order', sa.Integer, nullable=False),
        sa.Column('is_active', sa.Boolean, nullable=False),
        sa.Column('created_at', sa.DateTime))
    op.create_index('ix_hero_images_object_key', 'hero_images', ['object_key'], unique=True)
    op.create_index('ix_hero_images_sort_order', 'hero_images', ['sort_order'])
    op.create_index('ix_hero_images_is_active', 'hero_images', ['is_active'])
    op.create_index('ix_hero_images_created_at', 'hero_images', ['created_at'])


def downgrade():
    op.drop_index('ix_hero_images_created_at', table_name='hero_images')
    op.drop_index('ix_hero_images_is_active', table_name='hero_images')
    op.drop_index('ix_hero_images_sort_order', table_name='hero_images')
    op.drop_index('ix_hero_images_object_key', table_name='hero_images')
    op.drop_table('hero_images')
