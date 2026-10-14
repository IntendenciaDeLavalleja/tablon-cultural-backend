import os
import logging
from datetime import date, timedelta
from flask import request, jsonify, abort, send_file, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from app.utils.dates import local_today
from app.services.outbox_service import queue_submission_emails
import hashlib
import json
import re
import io
from marshmallow import ValidationError

from app.extensions import db, limiter, csrf
from app.models.event import CulturalEvent, EventSubmission
from app.models.hero import HeroImage
from app.models.enums import EventStatus, SubmissionStatus
from app.schemas.event import EventSubmissionCreateSchema, ContactMessageCreateSchema
from app.models.contact import ContactMessage
from app.services.minio_service import minio_service
from app.services.mail_service import mail_service
from app.utils.validators import validate_upload_file, FileValidationError
from app.utils.security import generate_submission_code

from . import public_bp

@public_bp.route('/api/events', methods=['GET'])
@limiter.limit("60 per minute")
def list_events():
    today = local_today()
    all_published = request.args.get('all', 'false').lower() == 'true'
    
    query = CulturalEvent.query.filter(
        CulturalEvent.status == EventStatus.PUBLISHED,
        CulturalEvent.event_date >= today
    )

    if not all_published:
        max_date = today + timedelta(days=15)
        query = query.filter(CulturalEvent.event_date <= max_date)
    
    events = query.order_by(CulturalEvent.event_date.asc()).all()
    
    payload = []
    for event in events:
        image_url = None
        if event.image_object_key:
            try:
                image_url = minio_service.get_file_url(event.image_object_key)
            except Exception as e:
                logging.warning(f"Failed to build image URL for event {event.id}: {e}")
        
        # Si no hay object_key o falló, usar el campo estático por si es una URL externa
        if not image_url:
            image_url = event.image_url

        payload.append({
            "id": str(event.id),
            "title": event.title,
            "locality": event.locality,
            "address": event.address,
            "datetime": event.event_date.isoformat() if event.event_date else None,
            "description": event.description,
            "image": image_url,
            "category": event.category
        })

    response = jsonify(payload)
    response.headers['Cache-Control'] = 'no-store'
    return response, 200

@public_bp.route('/api/event-submissions', methods=['POST'])
@limiter.limit("8 per minute")
@csrf.exempt
def create_event_submission():
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form.to_dict()

    if not isinstance(data, dict):
        return jsonify(error='El formulario debe ser un objeto.'), 400
    for alias, canonical in [('eventName', 'event_name'), ('datetime', 'event_date'), ('emailConfirm', 'email_confirm')]:
        if alias in data:
            data.setdefault(canonical, data.pop(alias))

    schema = EventSubmissionCreateSchema()
    try:
        validated_data = schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Error de validación", "details": err.messages}), 400

    file = request.files.get('image') or request.files.get('file')
    key = request.headers.get('Idempotency-Key')
    if key and not re.fullmatch(r'[a-zA-Z0-9-]{16,64}', key):
        return jsonify(error='Identificador de envío inválido.'), 400
    digest = hashlib.sha256(json.dumps(validated_data, sort_keys=True, default=str).encode())
    if file:
        try:
            validate_upload_file(file)
        except FileValidationError as exc:
            return jsonify(error='Archivo inválido', details={'image': [str(exc)]}), 400
        digest.update(file.read())
        file.seek(0)
    request_digest = digest.hexdigest()
    existing = EventSubmission.query.filter_by(idempotency_key=key).first() if key else None
    if existing:
        if existing.request_digest != request_digest:
            return jsonify(error='Este identificador ya fue usado para otro formulario.'), 409
        return submission_response(existing)
    
    try:
        submission_code = generate_submission_code()

        submission = EventSubmission(
            submission_code=submission_code,
            idempotency_key=key,
            request_digest=request_digest,
            full_name=validated_data['full_name'],
            email=validated_data['email'],
            phone=validated_data.get('phone'),
            event_name=validated_data['event_name'],
            locality=validated_data['locality'],
            address=validated_data.get('address'),
            event_date=validated_data['event_date'],
            description=validated_data['description'],
            links=validated_data.get('links'),
            status=SubmissionStatus.NEW,
            ip_address=request.remote_addr,
            user_agent=str(request.user_agent)[:255]
        )

        db.session.add(submission)
        db.session.flush()

        if file:
            try:
                validate_upload_file(file)
                upload_result = minio_service.upload_event_image(file, submission_code)
                submission.image_object_key = upload_result['object_key']
                submission.image_file_name = upload_result['file_name']
                submission.image_content_type = upload_result['content_type']
                submission.image_size_bytes = upload_result['size_bytes']
            except FileValidationError as e:
                db.session.rollback()
                return jsonify({"error": "Archivo inválido", "details": {"image": [str(e)]}}), 400
            except Exception as e:
                db.session.rollback()
                logging.error(f"Error uploading image for submission {submission_code}: {e}")
                return jsonify({"error": "Error del sistema al procesar la imagen"}), 500

        queue_submission_emails(submission)
        db.session.commit()
        return submission_response(submission)

    except IntegrityError:
        db.session.rollback()
        existing = EventSubmission.query.filter_by(idempotency_key=key).first() if key else None
        if existing and existing.request_digest == request_digest:
            return submission_response(existing)
        return jsonify(error='No se pudo guardar la solicitud. Intente nuevamente.'), 409

    except Exception as e:
        db.session.rollback()
        logging.error(f"Unexpected error creating event submission: {e}")
        return jsonify({"error": "Ocurrió un error inesperado."}), 500

@public_bp.route('/api/contact-messages', methods=['POST'])
@limiter.limit("10 per minute")
@csrf.exempt
def create_contact_message():
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form.to_dict()

    if not isinstance(data, dict):
        return jsonify(error='El formulario debe ser un objeto.'), 400
    if 'description' in data:
        data.setdefault('message', data.pop('description'))

    schema = ContactMessageCreateSchema()
    try:
        validated_data = schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Error de validación", "details": err.messages}), 400

    try:
        message = ContactMessage(
            full_name=validated_data['full_name'],
            email=validated_data['email'],
            subject=validated_data.get('subject'),
            message=validated_data['message'],
            ip_address=request.remote_addr,
            user_agent=str(request.user_agent)[:255]
        )
        db.session.add(message)
        db.session.commit()

        return jsonify({
            "message": "Mensaje enviado correctamente"
        }), 201
    except Exception as e:
        db.session.rollback()
        logging.error(f"Unexpected error creating contact message: {e}")
        return jsonify({"error": "Ocurrió un error inesperado."}), 500



def submission_response(submission):
    return jsonify(message='Postulación enviada correctamente',
                   submission_code=submission.submission_code,
                   status=submission.status.value,
                   created_at=submission.created_at.isoformat()), 201


@public_bp.route('/api/hero-images', methods=['GET'])
@limiter.limit("60 per minute")
def list_hero_images():
    images = (HeroImage.query
              .filter_by(is_active=True)
              .order_by(HeroImage.sort_order.asc(), HeroImage.id.asc())
              .all())
    payload = [{
        "id": str(image.id),
        "url": url_for('public.event_image', object_key=image.object_key),
        "alt": image.alt_text,
    } for image in images]
    response = jsonify(payload)
    response.headers['Cache-Control'] = 'no-store'
    return response, 200


@public_bp.get('/media/<path:object_key>')
def event_image(object_key):
    published = CulturalEvent.query.filter_by(image_object_key=object_key, status=EventStatus.PUBLISHED).first()
    hero = HeroImage.query.filter_by(object_key=object_key, is_active=True).first()
    if not published and not hero and not (current_user.is_authenticated and current_user.is_active):
        abort(404)
    data = minio_service.get_file_content(object_key)
    if data is None:
        abort(503)
    from mimetypes import guess_type
    response = send_file(io.BytesIO(data), mimetype=guess_type(object_key)[0] or 'application/octet-stream')
    response.headers['Cache-Control'] = 'private, max-age=300'
    return response
