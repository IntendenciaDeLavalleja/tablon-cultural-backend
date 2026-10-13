from datetime import datetime
from io import BytesIO
from unittest.mock import Mock
import importlib
import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage
from app.extensions import db
from app.models.contact import Contact, ReceivedEmail
from app.models.user import User
from app.services.mail_service import mail_service
from app.services.minio_service import minio_service
from app.utils.validators import validate_upload_file, FileValidationError


def test_imap_uses_stable_uids_decodes_and_deduplicates(app, monkeypatch):
    app.config.update(IMAP_SERVER='imap.example.com', MAIL_USERNAME='user', MAIL_PASSWORD='test')
    db.session.add(Contact(name='Actor cultural',email='actor@example.com'))
    db.session.commit()
    messages={b'31':b'From: Actor <actor@example.com>\r\nSubject: Concierto\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nHola cultura',
              b'48':b'From: Actor <actor@example.com>\r\nSubject: Taller\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nOtro evento',
              b'50':b'From: desconocido@example.com\r\nSubject: No agendado\r\n\r\nNo guardar'}
    connection=Mock()
    connection.select.return_value=('OK',[b'3'])
    connection.response.return_value=('UIDVALIDITY',[b'12345'])
    connection.uid.side_effect=lambda operation, *args: ('OK',[b'31 48 50']) if operation == 'search' else ('OK',[(b'meta',messages[args[0]])])
    module=importlib.import_module('app.services.mail_service')
    monkeypatch.setattr(module.imaplib,'IMAP4_SSL',Mock(return_value=connection))
    assert mail_service.fetch_received_emails() == 2
    assert mail_service.fetch_received_emails() == 0
    assert ReceivedEmail.query.count() == 2
    assert ReceivedEmail.query.first().body == 'Hola cultura'
    assert connection.logout.call_count == 2
    assert connection.response.call_count == 2  # once per mailbox selection, not once per email


def test_imap_failure_is_not_reported_as_empty_success(app, monkeypatch):
    app.config.update(IMAP_SERVER='imap.example.com', MAIL_USERNAME='user', MAIL_PASSWORD='test')
    module=importlib.import_module('app.services.mail_service')
    monkeypatch.setattr(module.imaplib,'IMAP4_SSL',Mock(side_effect=OSError('down')))
    with pytest.raises(ValueError,match='No se pudo sincronizar'):
        mail_service.fetch_received_emails()
    assert ReceivedEmail.query.count() == 0


@pytest.mark.parametrize('size,valid',[(1024*1024+10,True),(2*1024*1024,True),(2*1024*1024+1,False)])
def test_image_size_contract(size, valid):
    stream=BytesIO();Image.new('RGB',(2,2)).save(stream,format='PNG')
    raw=stream.getvalue();raw+=b'\0'*(size-len(raw))
    file=FileStorage(stream=BytesIO(raw),filename='photo.png',content_type='application/octet-stream')
    if valid:
        validate_upload_file(file)
        assert file.content_type == 'image/png'
        assert file.tell() == 0
    else:
        with pytest.raises(FileValidationError): validate_upload_file(file)


def test_mismatched_image_extension_is_rejected():
    stream=BytesIO();Image.new('RGB',(2,2)).save(stream,format='PNG');stream.seek(0)
    with pytest.raises(FileValidationError):
        validate_upload_file(FileStorage(stream=stream,filename='photo.jpg',content_type='image/jpeg'))


def test_storage_connections_are_released(monkeypatch):
    response=Mock();response.read.return_value=b'image'
    client=Mock();client.get_object.return_value=response
    monkeypatch.setattr(minio_service,'client',client)
    assert minio_service.get_file_content('events/photo.png') == b'image'
    response.close.assert_called_once()
    response.release_conn.assert_called_once()
