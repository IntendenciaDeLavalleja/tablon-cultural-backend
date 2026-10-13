from marshmallow import fields, validate, pre_load, validates, ValidationError
from app.extensions import ma
from app.utils.security import sanitize_text

# Constantes de validación
CATEGORY_CHOICES = ["alumbrado", "limpieza", "seguridad", "tránsito", "otros"]
MUNICIPALITY_MAX_LEN = 100
NAME_MAX_LEN = 100
DESC_MAX_LEN = 5000

class TicketCreateSchema(ma.Schema):
    municipality_or_destination = fields.Str(
        required=True, 
        validate=validate.Length(min=3, max=MUNICIPALITY_MAX_LEN, error="La longitud debe ser de al menos {min} caracteres."),
        error_messages={"required": "El municipio o destino es obligatorio."}
    )
    
    category = fields.Str(
        required=True,
        validate=validate.OneOf(CATEGORY_CHOICES, error="Categoría no válida."),
        error_messages={"required": "La categoría es obligatoria."}
    )
    
    full_name = fields.Str(
        required=True, 
        validate=validate.Length(min=3, max=NAME_MAX_LEN, error="El nombre debe tener entre {min} y {max} caracteres."),
        error_messages={"required": "El nombre completo es obligatorio."}
    )
    
    email = fields.Email(
        required=True, 
        validate=validate.Length(max=255),
        error_messages={"required": "El correo electrónico es obligatorio.", "invalid": "Correo electrónico inválido."}
    )
    
    description = fields.Str(
        required=True, 
        validate=validate.Length(min=10, max=DESC_MAX_LEN, error="La descripción debe tener al menos {min} caracteres."),
        error_messages={"required": "La descripción es obligatoria."}
    )

    @pre_load
    def sanitize_inputs(self, data, **kwargs):
        """Sanitiza campos de texto antes de validar."""
        if not data:
            return data
            
        # Campos a sanitizar
        fields_to_sanitize = ['municipality_or_destination', 'description', 'full_name']
        
        for field in fields_to_sanitize:
            if field in data and isinstance(data[field], str):
                # Sanitización HTML estricta
                data[field] = sanitize_text(data[field])
                # Trim whitespace
                data[field] = data[field].strip()
                
        return data

class TicketTrackingQuerySchema(ma.Schema):
    tracking_code = fields.Str(
        required=True,
        validate=validate.Regexp(
            r'^BUZ-\d{4}-[A-Z0-9]{8}$', 
            error="Formato de código inválido. Formato esperado: BUZ-YYYY-XXXXXXXX"
        ),
        error_messages={"required": "El código de seguimiento es obligatorio."}
    )
