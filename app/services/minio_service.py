import uuid
import logging
from datetime import timedelta
from werkzeug.datastructures import FileStorage
from minio import Minio
from minio.error import S3Error
from flask import current_app

class StorageError(Exception):
    """Excepción base para errores de almacenamiento."""
    pass

class MinioService:
    def __init__(self, app=None):
        self.client = None
        self.bucket_name = None
        self.public_base_url = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        """Inicializa el cliente MinIO con la configuración de la app."""
        self.client = None
        endpoint = app.config.get('MINIO_ENDPOINT')
        access_key = app.config.get('MINIO_ACCESS_KEY')
        secret_key = app.config.get('MINIO_SECRET_KEY')
        secure = app.config.get('MINIO_SECURE', True)
        self.bucket_name = app.config.get('MINIO_BUCKET')
        self.public_base_url = app.config.get('MINIO_PUBLIC_BASE_URL')

        if not all([endpoint, access_key, secret_key, self.bucket_name]):
            logging.warning("MinIO configuration incomplete. Storage service will fail.")
            return

        try:
            self.client = Minio(
                endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
                http_client=__import__('urllib3').PoolManager(timeout=__import__('urllib3').Timeout(connect=3, read=10), retries=False)
            )

        except Exception as e:
            logging.error(f"Failed to initialize MinIO client: {str(e)}")
            # No lanzamos error aquí para no romper el inicio de la app, 
            # pero fallará al intentar usarlo.

    def ensure_bucket_exists(self):
        """Verifica si el bucket existe y lo crea si es necesario."""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logging.info(f"Bucket '{self.bucket_name}' created successfully.")
            else:
                logging.info(f"Bucket '{self.bucket_name}' already exists.")
        except S3Error as e:
            logging.error(f"Error checking/creating bucket: {e}")
            raise StorageError("Could not initialize storage bucket.")

    def upload_file(self, file: FileStorage, tracking_code: str) -> dict:
        """
        Sube un archivo al bucket para tickets legacy.
        Retorna dict con metadata {object_key, file_name, content_type, size_bytes}
        """
        return self._upload_file(file, f"tickets/{tracking_code}")

    def upload_event_image(self, file: FileStorage, submission_code: str) -> dict:
        """
        Sube una imagen al bucket para postulaciones de eventos.
        Retorna dict con metadata {object_key, file_name, content_type, size_bytes}
        """
        return self._upload_file(file, f"event-submissions/{submission_code}")

    def upload_cultural_event_image(self, file: FileStorage) -> dict:
        """
        Sube una imagen para un evento cultural creado por admin.
        Genera un object_key bajo 'events/'.
        """
        return self._upload_file(file, "events")

    def upload_hero_image(self, file: FileStorage) -> dict:
        """
        Sube una portada WEBP para el carrusel del encabezado.
        Genera un object_key bajo 'hero/'.
        """
        from app.utils.validators import validate_webp_upload
        validate_webp_upload(file)
        return self._upload_file(file, "hero")

    def _upload_file(self, file: FileStorage, object_prefix: str) -> dict:
        """
        Método interno de subida.
        """
        from app.utils.validators import validate_upload_file
        validate_upload_file(file)
        if not self.client:
            raise StorageError("Storage service not initialized.")

        size = 0
        try:
            # Obtener extensión y generar key único
            ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'bin'
            object_prefix = object_prefix.strip('/')
            object_name = f"{object_prefix}/{uuid.uuid4()}.{ext}"
            
            # Preparar archivo para lectura
            file.seek(0, 2)
            size = file.tell()
            file.seek(0)

            # Subir
            self.client.put_object(
                self.bucket_name,
                object_name,
                file,
                size,
                content_type=file.content_type
            )
            
            logging.info(f"File uploaded: {object_name}")
            
            return {
                "object_key": object_name,
                "file_name": file.filename[:255],
                "content_type": file.content_type,
                "size_bytes": size
            }

        except S3Error as e:
            logging.error(f"MinIO Upload Error: {e}")
            raise StorageError("Failed to upload file to storage.")
        except Exception as e:
            logging.error(f"Unexpected Upload Error: {e}")
            raise StorageError("An unexpected error occurred during file upload.")

    def get_file_url(self, object_key: str, expires_in_hours: int = 24) -> str:
        """
        Genera una URL para acceder al archivo.
        Si MINIO_PUBLIC_BASE_URL está configurado, retorna URL directa.
        Si no, genera una URL pres firmada.
        """
        if not self.client:
            raise StorageError("Storage service not initialized.")

        from flask import url_for
        return url_for('public.event_image', object_key=object_key)

    def delete_file(self, object_key: str):
        """Borra un objeto del bucket."""
        if not self.client:
            raise StorageError("Storage service not initialized.")
            
        try:
            self.client.remove_object(self.bucket_name, object_key)
            logging.info(f"File deleted: {object_key}")
        except S3Error as e:
            logging.error(f"MinIO Delete Error: {e}")
            raise StorageError("Failed to delete file from storage.")

    def get_file_content(self, object_key: str):
        """
        Obtiene el contenido binario de un archivo en MinIO.
        """
        if not self.client:
            raise StorageError("Storage service not initialized.")
            
        try:
            response = self.client.get_object(self.bucket_name, object_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception as e:
            logging.error(f"MinIO Get Error: {e}")
            return None

# Instancia global (se inicializará en create_app)
minio_service = MinioService()
