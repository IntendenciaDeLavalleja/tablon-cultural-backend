# Backend del Tablón Cultural

Flask con MariaDB/PyMySQL, SQLAlchemy, Marshmallow, WTForms y MinIO. Rutas activas: `app/routes/public/routes.py` y `app/routes/admin/tablon_routes.py`.

La imagen Docker incluye un `HEALTHCHECK` que consulta `/healthz` y comprueba la conexión a la base de datos.

## Desarrollo local

```sh
python -m venv venv
# Windows: venv/Scripts/activate
# Linux: source venv/bin/activate
pip install -r requirements.txt
```

Copiar `.env.example` a `.env` dentro de `backend` y completar los valores. En Linux se requiere `libmagic1`. No usar credenciales institucionales para pruebas.

Si `.env` ya existe, revisar sus valores antes de iniciar servicios. En esta estación ya existe el contenedor `minio`, accesible en `localhost:9000`, y el bucket `tablon-cultural-uploads`; no se necesita otro contenedor de almacenamiento. `MINIO_BUCKET_NAME` y `MINIO_BUCKET` son compatibles. Las imágenes se sirven mediante `/media`, por lo que no dependen de `MINIO_PUBLIC_URL`. `compose.local-storage.yaml` es un bootstrap opcional con perfil `local-storage`, exclusivamente para equipos sin almacenamiento existente.

```sh
flask --app wsgi db upgrade
flask --app wsgi init-bucket
flask --app wsgi create-admin USUARIO CORREO CONTRASEÑA true
flask --app wsgi run
# En otra terminal, con el mismo entorno:
flask --app wsgi process-outbox
```

El frontend en desarrollo dirige `/api` y `/media` hacia `http://127.0.0.1:5000`. En Docker, Nginx sirve el sitio y el panel bajo un único origen.

Desde la raíz del repositorio:

```sh
python -m pytest -q
npm run build:admin
```

`backend/admin.css` se compila a `app/static/admin.css`; regenerarlo si se cambian clases de las plantillas. El CSS compilado se incluye en el contenedor para que el panel no dependa de servicios CDN.

El comando `process-outbox --once` procesa un lote y termina. En producción mantener el worker permanente definido en Compose. Los endpoints públicos devuelven errores JSON y el panel protege sus mutaciones con CSRF.

Ver [despliegue y operación](../docs/DEPLOYMENT.md) y [evidencia de pruebas](../docs/VERIFICATION.md).
