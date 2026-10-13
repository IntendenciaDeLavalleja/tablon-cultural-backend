from flask import jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from app.utils.validators import FileValidationError

def register_error_handlers(app):
    from sqlalchemy.exc import SQLAlchemyError
    from app.extensions import db

    @app.errorhandler(SQLAlchemyError)
    def database_unavailable(e):
        db.session.rollback()
        app.logger.error('Database operation failed: %s', type(e).__name__)
        return _format_error(e, 503, message='El servicio no está disponible temporalmente. Intente nuevamente.')

    @app.errorhandler(HTTPException)
    def http_error(e):
        return _format_error(e, e.code)
    
    @app.errorhandler(400)
    def bad_request(e):
        return _format_error(e, 400)

    @app.errorhandler(401)
    def unauthorized(e):
        return _format_error(e, 401)

    @app.errorhandler(403)
    def forbidden(e):
        return _format_error(e, 403)
        
    @app.errorhandler(404)
    def page_not_found(e):
        return _format_error(e, 404)

    @app.errorhandler(429)
    def ratelimit_handler(e):
        return _format_error(e, 429, message="Límite de peticiones excedido. Intente nuevamente más tarde.")

    @app.errorhandler(500)
    def internal_server_error(e):
        return _format_error(e, 500, message="Ocurrió un error interno del servidor.")

    @app.errorhandler(FileValidationError)
    def file_validation_error(e):
        return _format_error(e, 400)

def _format_error(e, status_code, message=None):
    """Retorna JSON para API o HTML para Navegador."""
    # Mensaje default si no se provee
    if not message:
        if status_code == 404:
            message = "Página no encontrada."
        elif status_code == 403:
            message = "Acceso denegado."
        elif status_code == 401:
            message = "No autorizado."
        else:
            message = str(e) if current_is_json() else getattr(e, 'description', str(e))

    if current_is_json():
        return jsonify({
            "error": "Error",
            "message": message,
            "code": status_code
        }), status_code
    
    # Renderizar template para admin/public views
    return render_template('errors.html', error=e, code=status_code, message=message), status_code

def current_is_json():
    """Detecta si la petición espera JSON o es API."""
    return request.is_json or request.path.startswith('/api/')
