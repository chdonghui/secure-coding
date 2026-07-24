import os
import sqlite3
import time
import uuid

import pytest


os.environ.setdefault(
    'MARKET_SECRET_KEY',
    'pytest-only-market-secret-key-with-more-than-32-characters',
)
os.environ.setdefault('MARKET_COOKIE_SECURE', 'false')

import app as market


MEMBER_ID = '00000000-0000-0000-0000-000000000501'
RECIPIENT_ID = '00000000-0000-0000-0000-000000000502'
REPORTER_ID = '00000000-0000-0000-0000-000000000503'
PRODUCT_ID = '00000000-0000-0000-0000-000000000504'
MESSAGE_ID = '00000000-0000-0000-0000-000000000505'
REPORT_ID = '00000000-0000-0000-0000-000000000506'
AUDIT_ID = '00000000-0000-0000-0000-000000000507'
MEMBER_USERNAME = 'deleting_member'
MEMBER_PASSWORD = 'DeletingPassword123!'


@pytest.fixture
def account_deletion_database(tmp_path, monkeypatch):
    database_path = tmp_path / 'test-account-deletion.db'
    monkeypatch.setattr(market, 'DATABASE', str(database_path))
    market.app.config.update(
        DEBUG=False,
        SECRET_KEY='pytest-only-app-secret-key-with-more-than-32-characters',
        SESSION_COOKIE_SECURE=False,
        REQUIRE_HTTPS=False,
        TESTING=True,
    )
    with market.chat_rate_limit_lock:
        market.chat_rate_limit_state['user'].clear()
        market.chat_rate_limit_state['ip'].clear()
        market.chat_duplicate_state.clear()

    market.init_db()
    connection = sqlite3.connect(database_path)
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        users = (
            (
                MEMBER_ID,
                MEMBER_USERNAME,
                MEMBER_PASSWORD,
                '삭제될 소개글',
            ),
            (
                RECIPIENT_ID,
                'deletion_recipient',
                'RecipientPassword123!',
                None,
            ),
            (
                REPORTER_ID,
                'deletion_reporter',
                'ReporterPassword123!',
                None,
            ),
        )
        for user_id, username, password, bio in users:
            connection.execute(
                '''
                INSERT INTO user (id, username, password, bio)
                VALUES (?, ?, ?, ?)
                ''',
                (
                    user_id,
                    username,
                    market.password_hasher.hash(password),
                    bio,
                ),
            )
        connection.execute(
            '''
            INSERT INTO product (id, title, description, price, seller_id)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (
                PRODUCT_ID,
                '탈퇴 회원 상품',
                '탈퇴 후 공개되지 않아야 합니다.',
                10000,
                MEMBER_ID,
            ),
        )
        connection.execute(
            '''
            INSERT INTO direct_message (
                id,
                sender_id,
                recipient_id,
                message,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            ''',
            (
                MESSAGE_ID,
                MEMBER_ID,
                RECIPIENT_ID,
                '보존되는 대화',
                1,
            ),
        )
        connection.execute(
            '''
            INSERT INTO report (
                id,
                reporter_id,
                target_type,
                target_user_id,
                target_product_id,
                reason,
                created_at
            )
            VALUES (?, ?, 'user', ?, NULL, ?, ?)
            ''',
            (
                REPORT_ID,
                REPORTER_ID,
                MEMBER_ID,
                '탈퇴 이후에도 보존되는 신고입니다.',
                1,
            ),
        )
        connection.execute(
            '''
            INSERT INTO report_audit_log (
                id,
                event_type,
                actor_id,
                target_type,
                target_id,
                source_ip_hash,
                created_at
            )
            VALUES (?, 'report_created', ?, 'user', ?, NULL, ?)
            ''',
            (AUDIT_ID, REPORTER_ID, MEMBER_ID, 1),
        )
        connection.commit()
    finally:
        connection.close()
    return database_path


def authenticated_client(user_id=MEMBER_ID):
    client = market.app.test_client()
    now = int(time.time())
    with client.session_transaction() as current_session:
        current_session['user_id'] = user_id
        current_session['session_version'] = 0
        current_session['authenticated_at'] = now
        current_session['last_activity'] = now
        current_session[market.CSRF_SESSION_KEY] = f'csrf-{user_id}'
    return client


def delete_account(
    client,
    password=MEMBER_PASSWORD,
    confirmation=market.ACCOUNT_DELETION_CONFIRMATION,
    include_csrf=True,
):
    data = {
        'current_password': password,
        'confirmation': confirmation,
    }
    if include_csrf:
        data['csrf_token'] = f'csrf-{MEMBER_ID}'
    return client.post('/profile/delete', data=data)


def fetch_member():
    connection = sqlite3.connect(market.DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(
            'SELECT * FROM user WHERE id = ?',
            (MEMBER_ID,),
        ).fetchone()
    finally:
        connection.close()


def test_account_deletion_requires_authentication_and_csrf(
    account_deletion_database,
):
    unauthenticated = market.app.test_client()
    response = unauthenticated.post('/profile/delete')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')

    client = authenticated_client()
    response = delete_account(client, include_csrf=False)
    assert response.status_code == 400
    assert fetch_member()['deleted_at'] is None


@pytest.mark.parametrize(
    ('password', 'confirmation'),
    [
        ('WrongPassword123!', market.ACCOUNT_DELETION_CONFIRMATION),
        (MEMBER_PASSWORD, '탈퇴안함'),
        ('a' * (market.PASSWORD_MAX_LENGTH + 1), '탈퇴안함'),
    ],
)
def test_account_deletion_rejects_failed_reauthentication_or_confirmation(
    account_deletion_database,
    password,
    confirmation,
):
    client = authenticated_client()

    response = delete_account(client, password, confirmation)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/profile')
    member = fetch_member()
    assert member['username'] == MEMBER_USERNAME
    assert member['deleted_at'] is None
    assert member['session_version'] == 0


def test_account_deletion_anonymizes_account_and_preserves_references(
    account_deletion_database,
):
    client = authenticated_client()
    original_password_hash = fetch_member()['password']

    response = delete_account(client)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/products')
    member = fetch_member()
    assert member is not None
    assert member['username'] == f'deleted-{MEMBER_ID}'
    assert member['bio'] is None
    assert isinstance(member['deleted_at'], int)
    assert member['session_version'] == 1
    assert member['failed_login_attempts'] == 0
    assert member['locked_until'] is None
    assert member['password'] != original_password_hash
    assert not market.verify_password(member['password'], MEMBER_PASSWORD)

    with client.session_transaction() as current_session:
        assert 'user_id' not in current_session

    connection = sqlite3.connect(market.DATABASE)
    try:
        assert connection.execute(
            'SELECT COUNT(*) FROM product WHERE seller_id = ?',
            (MEMBER_ID,),
        ).fetchone()[0] == 1
        assert connection.execute(
            '''
            SELECT COUNT(*)
            FROM direct_message
            WHERE sender_id = ? OR recipient_id = ?
            ''',
            (MEMBER_ID, MEMBER_ID),
        ).fetchone()[0] == 1
        assert connection.execute(
            'SELECT COUNT(*) FROM report WHERE target_user_id = ?',
            (MEMBER_ID,),
        ).fetchone()[0] == 1
        assert connection.execute(
            'SELECT COUNT(*) FROM report_audit_log WHERE target_id = ?',
            (MEMBER_ID,),
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_account_deletion_invalidates_other_http_and_socket_sessions(
    account_deletion_database,
):
    deleting_client = authenticated_client()
    other_http_session = authenticated_client()
    socket_client = market.socketio.test_client(
        market.app,
        flask_test_client=other_http_session,
        auth={'csrf_token': f'csrf-{MEMBER_ID}'},
    )
    assert socket_client.is_connected()

    response = delete_account(deleting_client)

    assert response.status_code == 302
    assert not socket_client.is_connected()
    rejected_session = other_http_session.get('/profile')
    assert rejected_session.status_code == 302
    assert rejected_session.headers['Location'].endswith('/login')


def test_deleted_account_and_products_are_hidden_from_public_features(
    account_deletion_database,
):
    deleting_client = authenticated_client()
    delete_account(deleting_client)
    public_client = market.app.test_client()
    recipient_client = authenticated_client(RECIPIENT_ID)

    catalog = public_client.get('/products').get_data(as_text=True)
    detail = public_client.get(f'/product/{PRODUCT_ID}')
    chat_users = recipient_client.get('/chat').get_data(as_text=True)

    assert '탈퇴 회원 상품' not in catalog
    assert PRODUCT_ID not in catalog
    assert detail.status_code == 404
    assert MEMBER_USERNAME not in chat_users
    assert f'deleted-{MEMBER_ID}' not in chat_users


def test_deleted_username_can_be_registered_again(
    account_deletion_database,
):
    deleting_client = authenticated_client()
    delete_account(deleting_client)
    new_client = market.app.test_client()
    new_client.get('/register')
    with new_client.session_transaction() as current_session:
        csrf_token = current_session[market.CSRF_SESSION_KEY]

    response = new_client.post(
        '/register',
        data={
            'csrf_token': csrf_token,
            'username': MEMBER_USERNAME,
            'password': 'ReplacementPassword123!',
        },
    )

    assert response.status_code == 302
    connection = sqlite3.connect(market.DATABASE)
    try:
        replacement = connection.execute(
            '''
            SELECT id, deleted_at
            FROM user
            WHERE username = ?
            ''',
            (MEMBER_USERNAME,),
        ).fetchone()
    finally:
        connection.close()
    assert replacement is not None
    assert replacement[0] != MEMBER_ID
    assert replacement[1] is None


def test_legacy_user_schema_adds_account_deletion_column(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / 'legacy-account-deletion.db'
    user_id = str(uuid.uuid4())
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
            '''
            INSERT INTO user (id, username, password, bio)
            VALUES (?, ?, ?, NULL)
            ''',
            (
                user_id,
                'legacy_deletion_user',
                'LegacyPassword123!',
            ),
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
            'SELECT deleted_at FROM user WHERE id = ?',
            (user_id,),
        ).fetchone()
        assert 'deleted_at' in columns
        assert migrated_user['deleted_at'] is None

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                'UPDATE user SET deleted_at = -1 WHERE id = ?',
                (user_id,),
            )
    finally:
        connection.close()
