import os
import re
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
NEW_PASSWORD = 'NewStrongPassword456!'


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
    yield market.app.test_client()


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


def test_registration_rejects_existing_quickstart_demo_accounts(client):
    connection = sqlite3.connect(market.DATABASE)
    try:
        for index, username in enumerate(
            ('quick_admin', 'user1', 'user2', 'business_demo'),
            start=1,
        ):
            connection.execute(
                '''
                INSERT INTO user (id, username, password, is_admin, account_type)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (
                    f'00000000-0000-0000-0000-0000000009{index:02d}',
                    username,
                    market.password_hasher.hash(VALID_PASSWORD),
                    1 if username == 'quick_admin' else 0,
                    'business' if username == 'business_demo' else 'user',
                ),
            )
        connection.commit()
    finally:
        connection.close()

    for username in ('quick_admin', 'user1', 'user2', 'business_demo'):
        response = register_user(client, username, 'DifferentPassword456!')
        assert response.status_code == 302
        assert response.headers['Location'].endswith('/login')

    connection = sqlite3.connect(market.DATABASE)
    try:
        assert connection.execute('SELECT COUNT(*) FROM user').fetchone()[0] == 4
    finally:
        connection.close()


@pytest.mark.parametrize(
    ('username', 'password'),
    [
        ('ab', VALID_PASSWORD),
        ('invalid<script', VALID_PASSWORD),
        ('한글사용자', VALID_PASSWORD),
        ('valid_user', 'short1'),
        ('valid_user', '123456789012'),
        ('valid_user', 'abcdefghijkl'),
        ('valid_user', 'Password1234'),
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
    response = client.post(
        '/profile/password',
        data={
            'current_password': VALID_PASSWORD,
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        },
    )
    assert response.status_code == 400
    assert client.post('/logout').status_code == 400


def test_mypage_requires_login_and_only_shows_current_user(client):
    response = client.get('/profile')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')

    register_user(client)
    register_user(client, 'another_user', VALID_PASSWORD)
    login_user(client)
    response = client.get('/profile')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert VALID_USERNAME in page
    assert 'another_user' not in page
    assert fetch_user()['password'] not in page


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


def change_password(
    client,
    current_password=VALID_PASSWORD,
    new_password=NEW_PASSWORD,
    confirm_password=NEW_PASSWORD,
):
    token = get_csrf_token(client, '/profile')
    return client.post(
        '/profile/password',
        data={
            'csrf_token': token,
            'current_password': current_password,
            'new_password': new_password,
            'confirm_password': confirm_password,
        },
    )


def test_password_change_rehashes_and_invalidates_existing_sessions(client):
    register_user(client)
    login_user(client)
    original_user = fetch_user()
    original_hash = original_user['password']
    original_session_version = original_user['session_version']

    second_client = market.app.test_client()
    assert login_user(second_client).status_code == 302
    socket_csrf_token = get_csrf_token(second_client, '/profile')
    second_socket = market.socketio.test_client(
        market.app,
        flask_test_client=second_client,
        auth={'csrf_token': socket_csrf_token},
    )
    assert second_socket.is_connected()

    response = change_password(client)
    changed_user = fetch_user()
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
    assert changed_user['password'] != original_hash
    assert changed_user['password'].startswith('$argon2')
    assert market.password_hasher.verify(
        changed_user['password'],
        NEW_PASSWORD,
    )
    assert changed_user['session_version'] == original_session_version + 1

    with client.session_transaction() as current_session:
        assert 'user_id' not in current_session
    invalidated_response = second_client.get('/dashboard')
    assert invalidated_response.status_code == 302
    assert invalidated_response.headers['Location'].endswith('/login')
    socket_response = second_socket.emit(
        'send_message',
        {'message': '무효화되어야 하는 기존 세션'},
        callback=True,
    )
    assert socket_response == {
        'ok': False,
        'error': 'authentication_required',
    }
    assert not second_socket.is_connected()

    assert login_user(client).headers['Location'].endswith('/login')
    assert login_user(
        client,
        password=NEW_PASSWORD,
    ).headers['Location'].endswith('/dashboard')


@pytest.mark.parametrize(
    ('current_password', 'new_password', 'confirm_password'),
    [
        ('WrongPassword123!', NEW_PASSWORD, NEW_PASSWORD),
        (VALID_PASSWORD, 'short1', 'short1'),
        (VALID_PASSWORD, '123456789012', '123456789012'),
        (VALID_PASSWORD, 'abcdefghijkl', 'abcdefghijkl'),
        (VALID_PASSWORD, 'Invalid Password123', 'Invalid Password123'),
        (VALID_PASSWORD, NEW_PASSWORD, 'DifferentPassword789!'),
        (VALID_PASSWORD, VALID_PASSWORD, VALID_PASSWORD),
    ],
)
def test_password_change_rejects_invalid_input_without_modifying_hash(
    client,
    current_password,
    new_password,
    confirm_password,
):
    register_user(client)
    login_user(client)
    original_user = fetch_user()

    response = change_password(
        client,
        current_password,
        new_password,
        confirm_password,
    )
    unchanged_user = fetch_user()
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/profile')
    assert unchanged_user['password'] == original_user['password']
    assert (
        unchanged_user['session_version']
        == original_user['session_version']
    )
    with client.session_transaction() as current_session:
        assert current_session['user_id'] == original_user['id']


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


def test_correct_password_recovers_temporarily_locked_account(client):
    register_user(client)
    for _ in range(market.MAX_FAILED_LOGIN_ATTEMPTS):
        response = login_user(client, password='WrongPassword123!')
        assert response.status_code == 302

    locked_user = fetch_user()
    assert locked_user['failed_login_attempts'] == 0
    assert locked_user['locked_until'] > int(time.time())

    response = login_user(client)
    assert response.headers['Location'].endswith('/dashboard')
    with client.session_transaction() as current_session:
        assert current_session['user_id'] == fetch_user()['id']
    recovered_user = fetch_user()
    assert recovered_user['failed_login_attempts'] == 0
    assert recovered_user['locked_until'] is None


def test_registration_and_login_attempts_are_rate_limited_by_ip(
    client,
    monkeypatch,
):
    monkeypatch.setattr(market, 'REGISTER_IP_RATE_LIMIT', 2)
    assert register_user(client, 'first_user').status_code == 302
    assert register_user(client, 'second_user').status_code == 302
    assert register_user(client, 'third_user').status_code == 429

    monkeypatch.setattr(market, 'LOGIN_IP_RATE_LIMIT', 2)
    for _ in range(2):
        assert login_user(
            client,
            username='unknown_user',
            password='WrongPassword123!',
        ).status_code == 302
    assert login_user(
        client,
        username='unknown_user',
        password='WrongPassword123!',
    ).status_code == 429


def test_successful_login_does_not_reset_ip_attempt_limit(
    client,
    monkeypatch,
):
    register_user(client)
    monkeypatch.setattr(market, 'LOGIN_IP_RATE_LIMIT', 3)

    assert login_user(
        client,
        username='unknown_user',
        password='WrongPassword123!',
    ).status_code == 302
    assert login_user(client).headers['Location'].endswith('/dashboard')
    assert login_user(
        client,
        username='unknown_user',
        password='WrongPassword123!',
    ).status_code == 302
    assert login_user(
        client,
        username='unknown_user',
        password='WrongPassword123!',
    ).status_code == 429


def test_sensitive_reauthentication_is_rate_limited(client, monkeypatch):
    register_user(client)
    login_user(client)
    monkeypatch.setattr(market, 'REAUTH_RATE_LIMIT', 2)

    for _ in range(2):
        token = get_csrf_token(client, '/profile')
        response = client.post(
            '/profile',
            data={
                'csrf_token': token,
                'bio': '변경되면 안 되는 소개글',
                'current_password': 'WrongPassword123!',
            },
        )
        assert response.status_code == 302

    token = get_csrf_token(client, '/profile')
    response = client.post(
        '/profile',
        data={
            'csrf_token': token,
            'bio': '제한 후 소개글',
            'current_password': 'WrongPassword123!',
        },
    )
    assert response.status_code == 429
    assert fetch_user()['bio'] is None


def test_security_headers_trusted_host_and_database_permissions(client):
    response = client.get('/products')
    csp = response.headers['Content-Security-Policy']
    nonce_match = re.search(r"script-src[^;]*'nonce-([^']+)'", csp)

    assert nonce_match is not None
    assert f'nonce="{nonce_match.group(1)}"' in response.get_data(as_text=True)
    assert "frame-ancestors 'none'" in csp
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['Referrer-Policy'] == (
        'strict-origin-when-cross-origin'
    )
    assert response.headers['Permissions-Policy'] == (
        'camera=(), microphone=(), geolocation=()'
    )
    assert response.headers['Cache-Control'] == 'no-store, max-age=0'
    assert 'sha384-ZCmVL/dTQHh41JxtZe73klDRFSJ/' in response.get_data(
        as_text=True
    )

    secure_response = client.get('/products', base_url='https://localhost')
    assert secure_response.headers['Strict-Transport-Security'] == (
        'max-age=31536000; includeSubDomains'
    )
    assert client.get(
        '/products',
        base_url='http://attacker.example',
    ).status_code == 400
    assert os.stat(market.DATABASE).st_mode & 0o777 == 0o600


def test_trusted_host_environment_validation(monkeypatch):
    monkeypatch.setenv(
        'MARKET_TRUSTED_HOSTS',
        'market.example, localhost',
    )
    assert market.get_trusted_hosts() == ['market.example', 'localhost']

    monkeypatch.setenv('MARKET_TRUSTED_HOSTS', 'https://market.example/path')
    with pytest.raises(RuntimeError):
        market.get_trusted_hosts()


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

    assert {
        'failed_login_attempts',
        'locked_until',
        'session_version',
    } <= columns
    assert migrated_user['password'].startswith('$argon2')
    assert migrated_user['session_version'] == 0
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
