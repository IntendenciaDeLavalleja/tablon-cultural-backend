import logging
from flask import render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db
from app.models.hero import HeroImage, DEFAULT_HERO_ALT_TEXT
from app.forms.admin import HeroImageForm
from app.services.minio_service import minio_service, StorageError
from app.utils.validators import FileValidationError
from app.utils.logging_helper import log_activity

from . import admin_bp


def _first_form_error(form):
    return '; '.join(error for errors in form.errors.values() for error in errors)


@admin_bp.route('/hero-images')
@login_required
def hero_images():
    images = HeroImage.query.order_by(HeroImage.sort_order.asc(), HeroImage.id.asc()).all()
    return render_template('admin/hero_images.html', images=images, form=HeroImageForm())


@admin_bp.route('/hero-images/upload', methods=['POST'])
@login_required
def upload_hero_image():
    form = HeroImageForm()
    if not form.validate_on_submit():
        flash('Revisá el formulario: ' + _first_form_error(form), 'error')
        return redirect(url_for('admin.hero_images'))

    try:
        upload = minio_service.upload_hero_image(form.image.data)
    except (StorageError, FileValidationError) as exc:
        logging.error(f'Hero image upload failed: {exc}')
        flash('No se pudo guardar la imagen. Intente nuevamente.', 'error')
        return redirect(url_for('admin.hero_images'))

    try:
        max_order = db.session.query(func.max(HeroImage.sort_order)).scalar() or 0
        image = HeroImage(
            object_key=upload['object_key'],
            file_name=upload['file_name'],
            content_type=upload['content_type'],
            size_bytes=upload['size_bytes'],
            alt_text=form.alt_text.data or DEFAULT_HERO_ALT_TEXT,
            sort_order=max_order + 1,
            is_active=True,
        )
        db.session.add(image)
        db.session.commit()
    except Exception:
        db.session.rollback()
        _delete_object_quietly(upload['object_key'])
        flash('No se pudo registrar la portada. Intente nuevamente.', 'error')
        return redirect(url_for('admin.hero_images'))

    log_activity(
        action='UPLOAD_HERO_IMAGE',
        details=f'Portada #{image.id} subida ({image.file_name})',
        user=current_user
    )
    flash('Portada agregada al carrusel.', 'success')
    return redirect(url_for('admin.hero_images'))


@admin_bp.route('/hero-images/<int:id>/toggle', methods=['POST'])
@login_required
def toggle_hero_image(id):
    image = db.get_or_404(HeroImage, id)
    image.is_active = not image.is_active
    db.session.commit()

    state = 'activada' if image.is_active else 'desactivada'
    log_activity(
        action='TOGGLE_HERO_IMAGE',
        details=f'Portada #{image.id} {state}',
        user=current_user
    )
    flash(f'Portada {state}.', 'success')
    return redirect(url_for('admin.hero_images'))


@admin_bp.route('/hero-images/<int:id>/move/<direction>', methods=['POST'])
@login_required
def move_hero_image(id, direction):
    if direction not in ('up', 'down'):
        abort(404)
    image = db.get_or_404(HeroImage, id)

    images = HeroImage.query.order_by(HeroImage.sort_order.asc(), HeroImage.id.asc()).all()
    index = images.index(image)
    target = index - 1 if direction == 'up' else index + 1
    if 0 <= target < len(images):
        images[index], images[target] = images[target], images[index]
        for position, item in enumerate(images, start=1):
            item.sort_order = position
        db.session.commit()
        log_activity(
            action='MOVE_HERO_IMAGE',
            details=f'Portada #{image.id} movida hacia {"arriba" if direction == "up" else "abajo"}',
            user=current_user
        )
    return redirect(url_for('admin.hero_images'))


@admin_bp.route('/hero-images/<int:id>/delete', methods=['POST'])
@login_required
def delete_hero_image(id):
    image = db.get_or_404(HeroImage, id)
    object_key = image.object_key
    db.session.delete(image)
    db.session.commit()

    storage_ok = _delete_object_quietly(object_key)
    log_activity(
        action='DELETE_HERO_IMAGE',
        details=f'Portada eliminada del carrusel ({object_key})',
        user=current_user
    )
    if storage_ok:
        flash('Portada eliminada.', 'info')
    else:
        flash('La portada se quitó del carrusel, pero no se pudo borrar el archivo del almacenamiento. Revisá la auditoría.', 'warning')
    return redirect(url_for('admin.hero_images'))


def _delete_object_quietly(object_key):
    try:
        minio_service.delete_file(object_key)
        return True
    except StorageError as exc:
        logging.error(f'Could not delete hero image {object_key}: {exc}')
        return False
