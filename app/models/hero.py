from app.utils.dates import utcnow
from app.extensions import db

DEFAULT_HERO_ALT_TEXT = 'Imagen de portada del Tablón Cultural'


class HeroImage(db.Model):
    """
    Imagen de portada del carrusel del encabezado público.
    """
    __tablename__ = 'hero_images'

    id = db.Column(db.Integer, primary_key=True)
    object_key = db.Column(db.String(255), unique=True, nullable=False)
    file_name = db.Column(db.String(255), nullable=True)
    content_type = db.Column(db.String(100), nullable=True)
    size_bytes = db.Column(db.BigInteger, nullable=True)
    alt_text = db.Column(db.String(200), nullable=False, default=DEFAULT_HERO_ALT_TEXT)
    sort_order = db.Column(db.Integer, nullable=False, default=0, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime, default=utcnow, index=True)

    def __repr__(self):
        return f'<HeroImage {self.object_key}>'
