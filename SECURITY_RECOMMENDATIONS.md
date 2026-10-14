
## Recomendaciones de Producción (Seguridad)

1.  **Backend (Gunicorn)**:
    - Ejecutar detrás de Nginx/Apache como reverse proxy.
    - Habilitar HTTPS (terminación SSL en proxy). Flask `Talisman` forzará headers seguros.

2.  **Base de Datos**:
    - Usar usuario con privilegios mínimos (CRUD) para la aplicación.
    - Rotar contraseñas periódicamente.
    - Habilitar encriptación en reposo si es posible.

3.  **Rate Limiting**:
    - En `config.py`, cambiar `RATELIMIT_STORAGE_URL` a Redis (`redis://...`) para persistencia distribuida y real.
    - La memoria puede borrarse al reiniciar procesos de Gunicorn workers.

4.  **MinIO / Object Storage**:
    - Usar policies restrictivas (solo lectura pública para buckets públicos, o usar presigned URLs siempre).
    - Habilitar versionado si se requiere auditoría de archivos reemplazados (aunque el sistema usa UUIDs únicos).

5.  **Secret Keys**:
    - `SECRET_KEY` debe ser una cadena larga aleatoria (ej: `openssl rand -hex 32`).
    - `WTF_CSRF_SECRET_KEY` igual de fuerte.

6.  **Admin User**:
    - El primer usuario debe crearse manualmente o via seed script (`manage.py`).
    - Contraseñas deben ser fuertes (Argon2 se encarga de que tardar en crackearse, pero la complejidad ayuda).
