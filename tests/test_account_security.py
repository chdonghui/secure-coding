import os
import sqlite3
import time

import pytest


os.environ.setdefault(
    'MARKET_SECRET_KEY',
    'pytest-only-market-secret-key-with-more-than-32-characters',
)
os.environ.setdefault('MARKET_COOKIE_SECURE', 'false')

import app as market


VALID_USERNAME = 'security_user'
VALID_PASSWORD = 'StrongPassword123!'


@pytest.fixture
def client(tmp_path, monkeypatch):
    database_path = tmp_path / 'test-market.db'
    monkeypatch.setattr(market, 'DATABASE', str(database_path))
    market.app.config.update(
        DEBUG=False,
        SECRET_KEY='pytest-only-app-secret-key-with-more-than-32-characters',
        SESSION_COOKIE_SECURE=False,
        TESTING=True,
    )
    market.init_db()
    with market.app.test_client() as test_client:
        yield test_client


def get_csrf_token(client, path):
    response = client.get(path)
    assert response.status_code == 200
    with client.session_transaction() as current_session:
        return current_session[market.CSRF_SESSION_KEY]


def register_user(client, username=VALID_USERNAME, password=VALID_PASSWORD):
    token = get_csrf_token(client, '/register')
    return client.post(
        '/register',
        data={
            'csrf_token': token,
            'username': username,
            'password': password,
        },
    )


def login_user(client, username=VALID_USERNAME, password=VALID_PASSWORD):
    token = get_csrf_token(client, '/login')
    return client.post(
        '/login',
        data={
            'csrf_token': token,
            'username': username,
            'password': password,
        },
    )


def fetch_user(username=VALID_USERNAME):
    connection = sqlite3.connect(market.DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(
            'SELECT * FROM user WHERE username = ?',
            (username,),
        ).fetchone()
    finally:
        connection.close()


def test_registration_stores_unique_argon2_hashes(client):
    response = register_user(client)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')

    first_user = fetch_user()
    assert first_user['password'] != VALID_PASSWORD
    assert first_user['password'].startswith('$argon2')
    assert market.password_hasher.verify(first_user['password'], VALID_PASSWORD)

    register_user(client, 'second_user', VALID_PASSWORD)
    second_user = fetch_user('second_user')
    assert second_user['password'] != first_user['password']


def test_duplicate_registration_does_not_reveal_or_replace_account(client):
    register_user(client)
    original_hash = fetch_user()['password']

    duplicate_response = register_user(
        client,
        password='DifferentPassword456!',
    )
    assert duplicate_response.status_code == 302
    assert duplicate_response.headers['Location'].endswith('/login')
    assert fetch_user()['password'] == original_hash


@pytest.mark.parametrize(
    ('username', 'password'),
    [
        ('ab', VALID_PASSWORD),
        ('invalid<script', VALID_PASSWORD),
        ('valid_user', 'short1'),
        ('valid_user', '123456789012'),
        ('valid_user', 'abcdefghijkl'),
        ('valid_user', 'Invalid Password123'),
    ],
)
def test_registration_rejects_invalid_input(client, username, password):
    response = register_user(client, username, password)
    assert response.status_code == 302

    connection = sqlite3.connect(market.DATABASE)
    try:
        user_count = connection.execute('SELECT COUNT(*) FROM user').fetchone()[0]
    finally:
        connection.close()
    assert user_count == 0


def test_membership_state_changes_require_csrf(client):
    response = client.post(
        '/register',
        data={'username': VALID_USERNAME, 'password': VALID_PASSWORD},
    )
    assert response.status_code == 400

    register_user(client)
    response = client.post(
        '/login',
        data={'username': VALID_USERNAME, 'password': VALID_PASSWORD},
    )
    assert response.status_code == 400

    login_user(client)
    response = client.post(
        '/profile',
        data={'bio': 'new bio', 'current_password': VALID_PASSWORD},
    )
    assert response.status_code == 400
    assert client.post('/logout').status_code == 400


def test_profile_requires_password_and_escapes_xss(client):
    register_user(client)
    assert login_user(client).status_code == 302

    token = get_csrf_token(client, '/profile')
    response = client.post(
        '/profile',
        data={
            'csrf_token': token,
            'bio': 'unauthorized change',
            'current_password': 'WrongPassword123!',
        },
    )
    assert response.status_code == 302
    assert fetch_user()['bio'] is None

    xss_payload = '<script>alert("profile-xss")</script>'
    token = get_csrf_token(client, '/profile')
    response = client.post(
        '/profile',
        data={
            'csrf_token': token,
            'bio': xss_payload,
            'current_password': VALID_PASSWORD,
        },
    )
    assert response.status_code == 302
    assert fetch_user()['bio'] == xss_payload

    rendered_profile = client.get('/profile').get_data(as_text=True)
    assert xss_payload not in rendered_profile
    assert '&lt;script&gt;alert' in rendered_profile


def test_profile_rejects_oversized_bio(client):
    register_user(client)
    login_user(client)
    token = get_csrf_token(client, '/profile')
    response = client.post(
        '/profile',
        data={
            'csrf_token': token,
            'bio': 'a' * (market.BIO_MAX_LENGTH + 1),
            'current_password': VALID_PASSWORD,
        },
    )
    assert response.status_code == 302
    assert fetch_user()['bio'] is None


def test_login_sets_protected_session_cookie(client):
    register_user(client)
    market.app.config['SESSION_COOKIE_SECURE'] = True
    response = login_user(client)
    cookie = response.headers['Set-Cookie']

    assert 'HttpOnly' in cookie
    assert 'Secure' in cookie
    assert 'SameSite=Lax' in cookie


@pytest.mark.parametrize(
    ('session_field', 'elapsed_seconds'),
    [
        ('last_activity', market.SESSION_IDLE_SECONDS + 1),
        ('authenticated_at', market.SESSION_ABSOLUTE_SECONDS + 1),
    ],
)
def test_session_has_idle_and_absolute_expiration(
    client,
    session_field,
    elapsed_seconds,
):
    register_user(client)
    login_user(client)
    with client.session_transaction() as current_session:
        assert current_session.permanent is True
        assert isinstance(current_session['authenticated_at'], int)
        current_session[session_field] = int(time.time()) - elapsed_seconds

    response = client.get('/dashboard')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
    with client.session_transaction() as current_session:
        assert 'user_id' not in current_session


def test_account_is_temporarily_locked_after_repeated_failures(client):
    register_user(client)
    for _ in range(market.MAX_FAILED_LOGIN_ATTEMPTS):
        response = login_user(client, password='WrongPassword123!')
        assert response.status_code == 302

    locked_user = fetch_user()
    assert locked_user['failed_login_attempts'] == 0
    assert locked_user['locked_until'] > int(time.time())

    login_user(client)
    with client.session_transaction() as current_session:
        assert 'user_id' not in current_session

    connection = sqlite3.connect(market.DATABASE)
    try:
        connection.execute(
            'UPDATE user SET locked_until = ? WHERE username = ?',
            (int(time.time()) - 1, VALID_USERNAME),
        )
        connection.commit()
    finally:
        connection.close()

    response = login_user(client)
    assert response.headers['Location'].endswith('/dashboard')
    with client.session_transaction() as current_session:
        assert current_session['user_id'] == fetch_user()['id']


def test_legacy_database_passwords_and_columns_are_migrated(tmp_path, monkeypatch):
    database_path = tmp_path / 'legacy-market.db'
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            '''
            CREATE TABLE user (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                bio TEXT
            )
            '''
        )
        connection.execute(
            'INSERT INTO user (id, username, password) VALUES (?, ?, ?)',
            ('legacy-id', 'legacy_user', VALID_PASSWORD),
        )
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(market, 'DATABASE', str(database_path))
    market.init_db()

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        columns = {
            row['name']
            for row in connection.execute('PRAGMA table_info(user)').fetchall()
        }
        migrated_user = connection.execute(
            'SELECT * FROM user WHERE id = ?',
            ('legacy-id',),
        ).fetchone()
    finally:
        connection.close()

    assert {'failed_login_attempts', 'locked_until'} <= columns
    assert migrated_user['password'].startswith('$argon2')
    assert market.password_hasher.verify(
        migrated_user['password'],
        VALID_PASSWORD,
    )


def test_secret_key_is_required_and_debug_is_disabled(monkeypatch):
    assert market.app.config['DEBUG'] is False

    monkeypatch.delenv('MARKET_SECRET_KEY')
    with pytest.raises(RuntimeError):
        market.get_required_secret_key()

    monkeypatch.setenv('MARKET_SECRET_KEY', 'too-short')
    with pytest.raises(RuntimeError):
        market.get_required_secret_key()


def test_generic_error_page_does_not_expose_internal_details(client):
    response = client.get('/path-that-does-not-exist')
    page = response.get_data(as_text=True)

    assert response.status_code == 404
    assert 'Traceback' not in page
    assert 'sqlite3' not in page
