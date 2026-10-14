FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FLASK_APP=wsgi:app
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m pip uninstall -y pip setuptools
COPY app ./app
COPY migrations ./migrations
COPY wsgi.py entrypoint.sh ./
RUN useradd --create-home app && chmod +x entrypoint.sh && chown -R app:app /app
USER app
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=2", "--threads=4", "--timeout=60", "--access-logfile=-", "--error-logfile=-", "wsgi:app"]
