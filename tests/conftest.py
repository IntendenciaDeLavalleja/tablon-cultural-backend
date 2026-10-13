import pytest
from app import create_app, db



@pytest.fixture(autouse=True)
def app():
    app = create_app('testing', {'MAIL_USE_TLS':False, 'MAIL_USE_SSL':False})
    # The fixture keeps a DB app context, so clear Flask-Login's context cache per request.
    @app.before_request
    def reset_login_cache():
        from flask import g
        g.pop('_login_user', None)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def runner(app):
    return app.test_cli_runner()
