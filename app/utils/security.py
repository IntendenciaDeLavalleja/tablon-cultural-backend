from html.parser import HTMLParser
import secrets
import string
from datetime import datetime
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

ph = PasswordHasher()

def sanitize_text(text: str) -> str:
    """
    Sanitiza texto eliminando cualquier tag HTML.
    Permite solo texto plano seguro.
    """
    if not text:
        return text
    # This is plain-text normalization, not a safe-HTML generator. Templates and
    # React must continue escaping the result (never mark user text as safe).
    class PlainText(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts = []
        def handle_data(self, data):
            self.parts.append(data)
    parser = PlainText()
    parser.feed(text)
    parser.close()
    return ''.join(parser.parts)

def generate_random_code(length: int = 6, numeric_only: bool = True) -> str:
    """Genera un código aleatorio criptográficamente seguro."""
    if numeric_only:
        alphabet = string.digits
    else:
        alphabet = string.ascii_uppercase + string.digits
    
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def generate_tracking_code() -> str:
    """Genera un código de seguimiento URL-safe: BUZ-YYYY-XXXXXXXX"""
    year = datetime.now().year
    suffix = generate_random_code(8, numeric_only=False)
    return f"BUZ-{year}-{suffix}"

def generate_submission_code() -> str:
    """Genera un código de postulación URL-safe: EVT-YYYY-XXXXXXXX"""
    year = datetime.now().year
    suffix = generate_random_code(8, numeric_only=False)
    return f"EVT-{year}-{suffix}"

def hash_password(password: str) -> str:
    """Hashea una contraseña usando Argon2."""
    return ph.hash(password)

def verify_password(hash_str: str, password: str) -> bool:
    """Verifica una contraseña contra un hash Argon2."""
    try:
        return ph.verify(hash_str, password)
    except VerifyMismatchError:
        return False

def hash_code(code: str) -> str:
    """Hashea un código de verificación (similar a password)."""
    return ph.hash(code)

def verify_code(hash_str: str, code: str) -> bool:
    """Verifica un código contra su hash."""
    return verify_password(hash_str, code)

