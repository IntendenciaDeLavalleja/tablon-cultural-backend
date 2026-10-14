from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import SelectField, TextAreaField, SubmitField, StringField, DateField
from wtforms.validators import DataRequired, Length, Email, ValidationError
from app.models.enums import SubmissionStatus
from app.schemas.event import LOCALITY_CHOICES
from app.utils.validators import validate_upload_file, validate_webp_upload, FileValidationError
from app.utils.dates import local_today

class UpdateSubmissionStatusForm(FlaskForm):
    status = SelectField('Estado', choices=[(s.value, s.label) for s in SubmissionStatus], validators=[DataRequired(message="Campo obligatorio")])
    note = TextAreaField('Nota Interna', validators=[Length(max=500, message="Máximo 500 caracteres")])
    submit = SubmitField('Actualizar Estado')

class CleanForm(FlaskForm):
    def validate(self, extra_validators=None):
        for field in self:
            if isinstance(field.data, str):
                field.data = field.data.strip()
        if hasattr(self, 'email') and self.email.data:
            self.email.data = self.email.data.lower()
        return super().validate(extra_validators=extra_validators)

class CulturalEventForm(CleanForm):
    title = StringField('Título', validators=[DataRequired(message="Campo obligatorio"), Length(min=3, max=200)])
    locality = SelectField('Localidad', choices=[(name, name) for name in LOCALITY_CHOICES], validators=[DataRequired()])
    address = StringField('Dirección', validators=[Length(max=255)])
    event_date = DateField('Fecha del Evento', validators=[DataRequired(message="Campo obligatorio")], format='%Y-%m-%d')
    description = TextAreaField('Descripción', validators=[DataRequired(message="Campo obligatorio"), Length(min=10, max=5000)])
    category = StringField('Categoría', validators=[Length(max=100)])
    image = FileField('Imagen del Evento', validators=[
        FileAllowed(['jpg', 'jpeg', 'png', 'webp'], message="Solo imágenes (jpg, png, webp)")
    ])
    submit = SubmitField('Guardar Evento')

    def validate_image(self, field):
        if field.data:
            try:
                validate_upload_file(field.data)
            except FileValidationError as exc:
                raise ValidationError(str(exc)) from exc

    def validate_event_date(self, field):
        if field.data and field.data < local_today():
            raise ValidationError('La fecha no puede ser anterior a hoy.')

class HeroImageForm(CleanForm):
    image = FileField('Imagen de portada (WEBP)', validators=[
        FileRequired(message="Seleccioná una imagen WEBP"),
        FileAllowed(['webp'], message="Solo se permiten imágenes WEBP")
    ])
    alt_text = StringField('Texto alternativo', validators=[Length(max=200, message="Máximo 200 caracteres")])
    submit = SubmitField('Subir portada')

    def validate_image(self, field):
        if field.data:
            try:
                validate_webp_upload(field.data)
            except FileValidationError as exc:
                raise ValidationError(str(exc)) from exc

class ContactForm(CleanForm):
    def validate_name(self, field):
        from app.models.contact import Contact
        if Contact.query.filter_by(name=field.data.strip()).first():
            raise ValidationError('Ya existe un contacto con ese nombre.')

    name = StringField('Nombre del Contacto', validators=[DataRequired(message="Campo obligatorio"), Length(max=100)])
    email = StringField('Correo Electrónico', validators=[DataRequired(message="Campo obligatorio"), Email(message="Email inválido"), Length(max=255)])
    submit = SubmitField('Guardar en Agenda')

class SendEmailForm(CleanForm):
    contact_id = SelectField('Destinatario (Agenda)', coerce=int, validators=[DataRequired(message="Debe seleccionar un destinatario")])
    subject = StringField('Asunto', validators=[DataRequired(message="Campo obligatorio"), Length(max=255)])
    message = TextAreaField('Mensaje / Cuerpo del Correo', validators=[DataRequired(message="Campo obligatorio")])
    submit = SubmitField('Enviar Correo')

class ReplyEmailForm(CleanForm):
    subject = StringField('Asunto', validators=[DataRequired(message="Campo obligatorio"), Length(max=255)])
    message = TextAreaField('Respuesta', validators=[DataRequired(message="Campo obligatorio")])
    submit = SubmitField('Enviar Respuesta')
