import time
from app.utils.security import generate_submission_code, hash_code, verify_code
from app.utils.validators import validate_upload_file, MAX_FILE_SIZE_BYTES, FileValidationError
from io import BytesIO
from werkzeug.datastructures import FileStorage
import pytest

def test_submission_code_format():
    code = generate_submission_code()
    assert code.startswith("EVT-")
    assert len(code.split("-")) == 3

def test_submission_code_uniqueness():
    codes = set()
    for _ in range(100):
        code = generate_submission_code()
        assert code not in codes
        codes.add(code)

def test_2fa_hashing():
    code = "123456"
    hashed = hash_code(code)
    assert hashed != code
    assert verify_code(hashed, code) is True
    assert verify_code(hashed, "654321") is False

def test_upload_validation_rejects_large_file():
    # Simulate a file larger than allowed
    large_data = b"0" * (MAX_FILE_SIZE_BYTES + 1024)
    file = FileStorage(
        stream=BytesIO(large_data),
        filename="test.png",
        content_type="image/png",
    )
    with pytest.raises(FileValidationError, match="Archivo demasiado grande"):
        validate_upload_file(file)

def test_upload_validation_rejects_bad_mime():
    # File with correct extension but text content
    bad_data = b"This is not an image"
    file = FileStorage(
        stream=BytesIO(bad_data),
        filename="hacker.jpg",
        content_type="image/jpeg",
    )
    with pytest.raises(FileValidationError):
        validate_upload_file(file)
