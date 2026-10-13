# Tablón Cultural de Lavalleja — Backend

API y administración Flask para recibir y revisar postulaciones, crear eventos y publicar los aprobados. Incluye MariaDB, MinIO existente, límites con Redis, autenticación con 2FA, auditoría y cola persistente de notificaciones. El sitio público está en [tablon-cultural-frontend](https://github.com/IntendenciaDeLavalleja/tablon-cultural-frontend).

## Desarrollo y pruebas

Requiere Python 3.13/3.14; en Linux instalar `libmagic1`. Node 22.12 o superior se utiliza para compilar el CSS del panel. No se necesitan archivos del repositorio del frontend.

```sh
python -m venv venv
# Activar venv: Windows venv/Scripts/activate; Linux source venv/bin/activate
pip install -r requirements.txt
npm ci
npm run build:admin
python -m pytest -q
```

Copiar `.env.example` a `.env` y completar la configuración antes de ejecutar Flask. Si existe una base, revisar su migración y respaldarla antes de actualizarla.

```sh
flask --app wsgi db upgrade
flask --app wsgi init-bucket
flask --app wsgi create-admin USUARIO CORREO CONTRASEÑA true
flask --app wsgi run
# En otra terminal:
flask --app wsgi process-outbox
```

El panel vive en `/admin`; la API en `/api` y las imágenes en `/media`. Las pruebas Python usan una base en memoria y correo suprimido; no trabajan sobre la base de `.env`.

## Docker y Coolify

Seleccionar `/compose.yaml` como aplicación Docker Compose. El Dockerfile compila los estilos del panel y ejecuta Gunicorn con usuario sin privilegios. No requiere construir el frontend.

Completar las variables de `.env.example` en Coolify: `SECRET_KEY` (mínimo 32 caracteres), contraseñas de MariaDB, dominio del frontend en `SITE_URL`, SMTP, remitente y `ADMIN_NOTIFICATION_EMAIL`. Mantener una única instancia de `mail-worker`. El backend aplica migraciones al arrancar; respaldar y ensayar previamente si se utiliza una base existente.

Conectar la aplicación a la misma red predefinida de Coolify que el frontend. El frontend debe usar el nombre real del backend y el puerto 8000 en `BACKEND_URL`. En la conexión interna recomendada no asignar un dominio público ni publicar puertos de MariaDB, Redis o backend. El frontend proporciona el dominio HTTPS y dirige también el panel.

`TRUSTED_PROXY_COUNT=2` corresponde a cliente → proxy Coolify → Nginx del frontend → Flask. Ajustarlo si cambia la topología. Para SMTP con TLS implícito/465 usar `MAIL_USE_SSL=true` y `MAIL_USE_TLS=false`; para STARTTLS/587, lo contrario. No activar ambas opciones.

```sh
docker compose --env-file .env up -d --build --wait
```

## MinIO existente

Configurar `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET_NAME` (también acepta `MINIO_BUCKET`) y `MINIO_SECURE`. Conservar las credenciales y el bucket existentes; el Compose principal no administra MinIO ni monta su almacenamiento.

Cuando Flask corre directamente en el equipo, `localhost:9000` identifica el MinIO publicado localmente. Desde Docker, usar `host.docker.internal:9000` para ese servicio del host; Compose incluye `host-gateway`. Para un recurso MinIO de Coolify utilizar su nombre real en una red compartida. Escribir el endpoint como `host:puerto`, sin esquema ni ruta de bucket. Las imágenes se entregan mediante `/media`, sin depender de `MINIO_PUBLIC_URL` ni de un bucket público.

```sh
python tests/integration/existing_storage.py
```

Esta prueba lee `.env`, usa SQLite aislado y correo suprimido. Crea cuatro imágenes temporales y elimina solo sus claves; verifica que los objetos anteriores conserven tamaño y ETag. No modifica la base configurada, las políticas del bucket ni el contenedor existente. `compose.local-storage.yaml` es opcional, con perfil `local-storage`, para equipos sin almacenamiento previo.

## Entorno aislado para pruebas completas

```sh
python tests/integration/setup_qa.py
docker compose --env-file .env.test -p tablon-qa -f compose.yaml -f deploy/compose.test.yaml up -d --build --wait
docker compose --env-file .env.test -p tablon-qa -f compose.yaml -f deploy/compose.test.yaml exec -T backend flask create-admin qa qa@example.com QA-only-Password-123! true
python tests/integration/migrations.py
```

El backend de QA escucha en `http://localhost:5000`; el buzón SMTP simulado en `http://localhost:8028`. MinIO se construye únicamente como fixture de QA y no publica puertos. El frontend puede conectarse a la red `tablon-qa_default` para sus pruebas de navegador. Después de esas pruebas ejecutar `python tests/integration/recovery.py`; este script detiene servicios exclusivamente del proyecto `tablon-qa` y no debe apuntar a producción.

Para detener QA sin borrar sus volúmenes:

```sh
docker compose --env-file .env.test -p tablon-qa -f compose.yaml -f deploy/compose.test.yaml down
```

Respaldar MariaDB y el almacenamiento MinIO por separado. La aceptación final requiere verificar HTTPS, correo/2FA, publicación y backups en el entorno institucional. Las pruebas funcionales no certifican ausencia de vulnerabilidades en imágenes o servicios externos. IMAP es opcional y requiere `IMAP_SERVER`/`IMAP_PORT` y las credenciales del buzón.

No se incluyen `.env`, entornos virtuales, datos locales, logs ni credenciales reales.
