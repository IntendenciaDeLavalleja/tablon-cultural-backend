from io import BytesIO
from unittest.mock import Mock
from PIL import Image
import pytest
from app.extensions import db
from app.models.hero import HeroImage
from app.models.user import User
from app.services.minio_service import minio_service, StorageError
from app.utils.security import hash_password


@pytest.fixture
def admin(client):
    user = User(username='admin', email='admin@example.com', password_hash=hash_password('Password-123'), is_active=True, is_superuser=True)
    db.session.add(user)
    db.session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    return user


def webp():
    stream = BytesIO()
    Image.new('RGB', (20, 20), 'blue').save(stream, format='WEBP')
    stream.seek(0)
    return stream


def png():
    stream = BytesIO()
    Image.new('RGB', (20, 20), 'red').save(stream, format='PNG')
    stream.seek(0)
    return stream


def hero(key, order, active=True):
    value = HeroImage(object_key=key, file_name=key.split('/')[-1], content_type='image/webp', size_bytes=10,
                      alt_text=f'Portada {order}', sort_order=order, is_active=active)
    db.session.add(value)
    db.session.commit()
    return value


def fake_upload(file):
    return {'object_key': 'hero/nueva.webp', 'file_name': 'nueva.webp', 'content_type': 'image/webp', 'size_bytes': 123}


def test_upload_accepts_webp_and_appends_to_order(client, admin, monkeypatch):
    hero('hero/a.webp', 1)
    monkeypatch.setattr(minio_service, 'upload_hero_image', Mock(side_effect=fake_upload))
    response = client.post('/admin/hero-images/upload',
                           data={'image': (webp(), 'portada.webp'), 'alt_text': 'Vista de Minas'},
                           content_type='multipart/form-data', follow_redirects=True)
    assert response.status_code == 200
    created = HeroImage.query.filter_by(object_key='hero/nueva.webp').one()
    assert created.sort_order == 2
    assert created.alt_text == 'Vista de Minas'
    assert created.is_active is True


def test_upload_rejects_non_webp_without_storing(client, admin, monkeypatch):
    upload = Mock(side_effect=fake_upload)
    monkeypatch.setattr(minio_service, 'upload_hero_image', upload)
    response = client.post('/admin/hero-images/upload',
                           data={'image': (png(), 'portada.png')},
                           content_type='multipart/form-data', follow_redirects=True)
    assert response.status_code == 200
    assert upload.call_count == 0
    assert HeroImage.query.count() == 0


def test_upload_storage_failure_keeps_database_clean(client, admin, monkeypatch):
    monkeypatch.setattr(minio_service, 'upload_hero_image', Mock(side_effect=StorageError('down')))
    response = client.post('/admin/hero-images/upload',
                           data={'image': (webp(), 'portada.webp')},
                           content_type='multipart/form-data', follow_redirects=True)
    assert response.status_code == 200
    assert 'No se pudo guardar' in response.text
    assert HeroImage.query.count() == 0


def test_public_list_returns_only_active_images_in_order(client):
    hero('hero/b.webp', 2)
    hero('hero/a.webp', 1)
    hero('hero/oculta.webp', 3, active=False)
    response = client.get('/api/hero-images')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    items = response.json
    assert [item['alt'] for item in items] == ['Portada 1', 'Portada 2']
    assert all(item['url'].startswith('/media/hero/') for item in items)


def test_media_serves_active_hero_and_hides_inactive(client, monkeypatch):
    monkeypatch.setattr(minio_service, 'get_file_content', Mock(return_value=webp().getvalue()))
    hero('hero/visible.webp', 1)
    hero('hero/oculta.webp', 2, active=False)
    assert client.get('/media/hero/visible.webp').status_code == 200
    assert client.get('/media/hero/oculta.webp').status_code == 404


def test_toggle_hides_image_from_public_list(client, admin):
    image = hero('hero/a.webp', 1)
    assert client.post(f'/admin/hero-images/{image.id}/toggle').status_code == 302
    db.session.refresh(image)
    assert image.is_active is False
    assert client.get('/api/hero-images').json == []


def test_move_swaps_order_and_normalizes_positions(client, admin):
    first = hero('hero/a.webp', 1)
    second = hero('hero/b.webp', 2)
    third = hero('hero/c.webp', 5)
    client.post(f'/admin/hero-images/{second.id}/move/up')
    for value in (first, second, third):
        db.session.refresh(value)
    assert (second.sort_order, first.sort_order, third.sort_order) == (1, 2, 3)


def test_move_at_edges_is_a_no_op(client, admin):
    first = hero('hero/a.webp', 1)
    second = hero('hero/b.webp', 2)
    client.post(f'/admin/hero-images/{first.id}/move/up')
    client.post(f'/admin/hero-images/{second.id}/move/down')
    db.session.refresh(first)
    db.session.refresh(second)
    assert (first.sort_order, second.sort_order) == (1, 2)


def test_move_rejects_unknown_direction(client, admin):
    image = hero('hero/a.webp', 1)
    assert client.post(f'/admin/hero-images/{image.id}/move/left').status_code == 404


def test_delete_removes_row_and_object(client, admin, monkeypatch):
    image = hero('hero/a.webp', 1)
    delete = Mock()
    monkeypatch.setattr(minio_service, 'delete_file', delete)
    response = client.post(f'/admin/hero-images/{image.id}/delete', follow_redirects=True)
    assert response.status_code == 200
    assert HeroImage.query.count() == 0
    delete.assert_called_once_with('hero/a.webp')
    assert 'Portada eliminada' in response.text


def test_delete_reports_storage_failure_after_removing_row(client, admin, monkeypatch):
    image = hero('hero/a.webp', 1)
    monkeypatch.setattr(minio_service, 'delete_file', Mock(side_effect=StorageError('down')))
    response = client.post(f'/admin/hero-images/{image.id}/delete', follow_redirects=True)
    assert HeroImage.query.count() == 0
    assert 'no se pudo borrar el archivo' in response.text


def test_admin_page_requires_login(client):
    assert client.get('/admin/hero-images').status_code == 302
    assert client.post('/admin/hero-images/upload').status_code == 302


def test_admin_page_renders_images_and_nav(client, admin):
    hero('hero/a.webp', 1)
    response = client.get('/admin/hero-images')
    assert response.status_code == 200
    assert 'Portada del Carrusel' in response.text
    assert 'Portada 1' in response.text
    assert '/media/hero/a.webp' in response.text
    assert 'href="/admin/hero-images"' in response.text
