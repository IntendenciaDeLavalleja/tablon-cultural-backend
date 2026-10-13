from app.schemas.event import EventSubmissionCreateSchema
from marshmallow import ValidationError
import pytest

def test_event_submission_schema_valid():
    data = {
        "full_name": "Juan Pérez",
        "email": "juan@example.com",
        "email_confirm": "juan@example.com",
        "phone": "099123456",
        "event_name": "Concierto de Verano",
        "locality": "Minas",
        "address": "Casa de la Cultura",
        "event_date": "2099-12-31",
        "description": "Un concierto abierto para toda la comunidad.",
        "links": "https://ejemplo.com",
        "captcha_question": "Cuanto es 1+3",
        "captcha_answer": "4"
    }
    schema = EventSubmissionCreateSchema()
    result = schema.load(data)
    assert result["email"] == "juan@example.com"

def test_event_submission_schema_bad_email_confirmation():
    data = {
        "full_name": "Ana",
        "email": "ana@example.com",
        "email_confirm": "otro@example.com",
        "event_name": "Taller",
        "locality": "Minas",
        "event_date": "2099-12-31",
        "description": "Descripción válida del evento.",
        "captcha_question": "Cuanto es 2+2",
        "captcha_answer": "4"
    }
    schema = EventSubmissionCreateSchema()
    with pytest.raises(ValidationError) as excinfo:
        schema.load(data)
    assert "email_confirm" in excinfo.value.messages

def test_event_submission_schema_sanitization():
    data = {
        "full_name": "Alert<script>alert(1)</script>",
        "email": "test@test.com",
        "email_confirm": "test@test.com",
        "event_name": "Evento <b>nuevo</b>",
        "locality": "Minas",
        "event_date": "2099-12-31",
        "description": "Texto descriptivo <b>válido</b>",
        "captcha_question": "Cuanto es 1+3",
        "captcha_answer": "4"
    }
    schema = EventSubmissionCreateSchema()
    result = schema.load(data)
    assert "<script>" not in result["full_name"]
    assert "alert(1)" in result["full_name"]
    assert "<b>" not in result["description"]
    assert "Texto" in result["description"]
