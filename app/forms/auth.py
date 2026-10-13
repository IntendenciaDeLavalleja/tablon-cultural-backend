from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, Length

class LoginForm(FlaskForm):
    email = StringField('Correo Electrónico', validators=[DataRequired(message="Campo obligatorio"), Email(message="Email inválido")])
    password = PasswordField('Contraseña', validators=[DataRequired(message="Campo obligatorio")])
    captcha = StringField('Captcha', validators=[DataRequired(message="Debe resolver el captcha")])
    submit = SubmitField('Ingresar')

class TwoFactorForm(FlaskForm):
    code = StringField('Código de Verificación', validators=[DataRequired(message="Campo obligatorio"), Length(min=6, max=6, message="Debe tener 6 dígitos")])
    submit = SubmitField('Verificar')
