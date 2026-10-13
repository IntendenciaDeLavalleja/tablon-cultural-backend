from marshmallow import fields, validate, pre_load, validates_schema, ValidationError
from app.extensions import ma
from app.utils.security import sanitize_text
from app.utils.dates import local_today
from app.utils.captcha import validate_captcha_answer

NAME_MAX_LEN = 120
EMAIL_MAX_LEN = 255
TEXT_MAX_LEN = 5000
LINKS_MAX_LEN = 1000

LOCALITY_CHOICES = [
    "Minas",
    "José Pedro Varela",
    "Solís de Mataojo",
    "José Batlle y Ordóñez",
    "Mariscala",
    "Pirarajá",
    "Zapicán",
    "Villa del Rosario"
]

class EventSubmissionCreateSchema(ma.Schema):
    full_name = fields.Str(
        required=True,
        validate=validate.Length(min=3, max=NAME_MAX_LEN),
        error_messages={"required": "El nombre completo es obligatorio."}
    )
    email = fields.Email(
        required=True,
        validate=validate.Length(max=EMAIL_MAX_LEN),
        error_messages={"required": "El correo es obligatorio.", "invalid": "Correo inválido."}
    )
    email_confirm = fields.Email(
        required=True,
        validate=validate.Length(max=EMAIL_MAX_LEN),
        error_messages={"required": "Debe repetir el correo.", "invalid": "Correo inválido."}
    )
    phone = fields.Str(
        required=False,
        validate=validate.Length(max=50)
    )
    event_name = fields.Str(
        required=True,
        validate=validate.Length(min=3, max=200),
        error_messages={"required": "El nombre del evento es obligatorio."}
    )
    locality = fields.Str(
        required=True,
        validate=validate.OneOf(LOCALITY_CHOICES, error="Localidad inválida."),
        error_messages={"required": "La localidad es obligatoria."}
    )
    address = fields.Str(
        required=False,
        validate=validate.Length(max=255)
    )
    event_date = fields.Date(
        required=True,
        error_messages={"required": "La fecha es obligatoria."}
    )
    description = fields.Str(
        required=True,
        validate=validate.Length(min=10, max=TEXT_MAX_LEN),
        error_messages={"required": "La descripción es obligatoria."}
    )
    links = fields.Str(
        required=False,
        validate=validate.Length(max=LINKS_MAX_LEN)
    )
    captcha_question = fields.Str(
        required=True,
        validate=validate.Length(min=3, max=100),
        error_messages={"required": "El captcha es obligatorio."}
    )
    captcha_answer = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=5),
        error_messages={"required": "Debe responder el captcha."}
    )

    @pre_load
    def sanitize_inputs(self, data, **kwargs):
        if not isinstance(data, dict):
            return data

        fields_to_sanitize = [
            'full_name',
            'event_name',
            'locality',
            'address',
            'description',
            'links',
            'captcha_question'
        ]

        for field in fields_to_sanitize:
            if field in data and isinstance(data[field], str):
                data[field] = sanitize_text(data[field]).strip()
        for field in ('email', 'email_confirm'):
            if isinstance(data.get(field), str):
                data[field] = data[field].strip().lower()
        return data

    @validates_schema
    def validate_confirmations(self, data, **kwargs):
        if data.get('event_date') and data['event_date'] < local_today():
            raise ValidationError({'event_date': ['La fecha no puede ser anterior a hoy.']})
        if data.get('email') and data.get('email_confirm'):
            if data['email'].lower().strip() != data['email_confirm'].lower().strip():
                raise ValidationError({"email_confirm": ["Los correos no coinciden."]})

        if data.get('captcha_question') and data.get('captcha_answer'):
            if not validate_captcha_answer(data['captcha_question'], data['captcha_answer']):
                raise ValidationError({"captcha_answer": ["Captcha inválido."]})

class ContactMessageCreateSchema(ma.Schema):
    full_name = fields.Str(
        required=True,
        validate=validate.Length(min=3, max=NAME_MAX_LEN),
        error_messages={"required": "El nombre completo es obligatorio."}
    )
    email = fields.Email(
        required=True,
        validate=validate.Length(max=EMAIL_MAX_LEN),
        error_messages={"required": "El correo es obligatorio.", "invalid": "Correo inválido."}
    )
    subject = fields.Str(
        required=False,
        validate=validate.Length(max=255)
    )
    message = fields.Str(
        required=True,
        validate=validate.Length(min=10, max=TEXT_MAX_LEN),
        error_messages={"required": "El mensaje es obligatorio."}
    )

    @pre_load
    def sanitize_inputs(self, data, **kwargs):
        if not isinstance(data, dict):
            return data

        fields_to_sanitize = ['full_name', 'subject', 'message']
        for field in fields_to_sanitize:
            if field in data and isinstance(data[field], str):
                data[field] = sanitize_text(data[field]).strip()
        return data
