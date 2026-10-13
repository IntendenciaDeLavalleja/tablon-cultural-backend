import os
import magic
from PIL import Image
from werkzeug.datastructures import FileStorage
from flask import current_app

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
MAX_FILE_SIZE_MB = 2
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

class FileValidationError(Exception):
    pass

def validate_upload_file(file: FileStorage) -> None:
    """
    Valida un archivo subido (FileStorage).
    Lanza FileValidationError si no cumple requisitos.
    
    Verificaciones:
    1. Nombre y Extensión.
    2. Tamaño (estimado y real).
    3. Magic bytes (MIME type real).
    4. Integridad de imagen (Pillow).
    """
    if not file or file.filename == '':
        raise FileValidationError("No se proporcionó un archivo válido.")

    # 1. Validar extensión
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError(f"Tipo de archivo no permitido. Permitidos: {', '.join(ALLOWED_EXTENSIONS)}")

    # 2. Validar tamaño
    # (Nota: content_length puede ser spoofeado, pero es primer filtro. 
    # La lectura real es mandatoria para seguridad completa, pero aquí hacemos chequeo stream/chunk).
    # Para simplificar y usar Pillow/Magic, leemos el header o el archivo.
    
    # Check pointer is at start
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    
    if size > MAX_FILE_SIZE_BYTES:
        raise FileValidationError(f"Archivo demasiado grande. El tamaño máximo es {MAX_FILE_SIZE_MB}MB.")
        
    # 3. Validar MIME real (Magic Bytes)
    # Leemos primeros 2KB para magic number
    header = file.read(2048)
    file.seek(0) # Reset pointer
    
    mime_type = magic.from_buffer(header, mime=True)
    
    # Mapeo estricto de extension a mime
    valid_mimes = {
        'jpg': ['image/jpeg'],
        'jpeg': ['image/jpeg'],
        'png': ['image/png'],
        'webp': ['image/webp']
    }
    
    if mime_type not in valid_mimes.get(ext, []):
        raise FileValidationError("El contenido no coincide con la extensión de la imagen.")

    # 4. Validar integridad de imagen con Pillow
    # Esto detecta si es un archivo corrupto o malware disfrazado con cabecera falsa
    try:
        img = Image.open(file)
        if img.width * img.height > 20_000_000:
            raise FileValidationError('La imagen excede los 20 megapíxeles.')
        img.verify() # Verifica integridad sin decodificar toda la imagen
        file.headers['Content-Type'] = mime_type
        
        # Verify resetea puntero en algunos casos, pero mejor asegurar. 
        # Además Image.open puede dejar el archivo abierto.
        # file.seek(0) es necesario si vamos a usar el archivo despues.
    except Exception:
        raise FileValidationError("Archivo de imagen corrupto o inválido.")
    finally:
        file.seek(0) # Siempre resetear puntero para el siguiente consumidor
