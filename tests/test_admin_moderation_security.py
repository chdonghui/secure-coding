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
from scripts import admin_user


ADMIN_ID = '00000000-0000-0000-0000-000000000601'
TARGET_ID = '00000000-0000-0000-0000-000000000602'
REPORTER_ID = '00000000-0000-0000-0000-000000000603'
SECOND_ADMIN_ID = '00000000-0000-0000-0000-000000000604'
PRODUCT_ID = '00000000-0000-0000-0000-000000000605'
ADMIN_PASSWORD = 'AdminPassword123!'
TARGET_PASSWORD = 'TargetPassword123!'
VALID_REASON = '반복적인 사기 판매 정황이 확인되었습니다.'
REACTIVATION_REASON = '관리자 재검토 결과 정상 사용자로 확인되었습니다.'


@pytest.fixture
def moderation_database(tmp_path, monkeypatch):
    database_path = tmp_path / 'test-moderation.db'
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
            (ADMIN_ID, 'moderation_admin', ADMIN_PASSWORD, 1),
            (TARGET_ID, 'bad_actor', TARGET_PASSWORD, 0),
            (REPORTER_ID, 'moderation_reporter', 'ReporterPassword123!', 0),
            (SECOND_ADMIN_ID, 'second_admin', 'SecondAdminPassword123!', 1),
        )
        for user_id, username, password, is_admin in users:
            connection.execute(
                '''
                INSERT INTO user (id, username, password, is_admin)
                VALUES (?, ?, ?, ?)
                ''',
                (
                    user_id,
                    username,
                    market.password_hasher.hash(password),
                    is_admin,
                ),
            )
        connection.execute(
            '''
            INSERT INTO product (id, title, description, price, seller_id)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (
                PRODUCT_ID,
                '신고된 불량 상품',
                '관리 삭제 후에도 증거는 보존됩니다.',
                50000,
                TARGET_ID,
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
            VALUES (?, ?, 'product', NULL, ?, ?, ?)
            ''',
            (
                '00000000-0000-0000-0000-000000000606',
                REPORTER_ID,
                PRODUCT_ID,
                '상품 사기 의심 정황을 신고합니다.',
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
                '00000000-0000-0000-0000-000000000607',
                REPORTER_ID,
                TARGET_ID,
                '사용자 사기 의심 정황을 신고합니다.',
                2,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return database_path


def authenticated_client(user_id, csrf_token=None):
    client = market.app.test_client()
    now = int(time.time())
    token = csrf_token or f'csrf-{user_id}'
    connection = sqlite3.connect(market.DATABASE)
    try:
        session_version = connection.execute(
            'SELECT session_version FROM user WHERE id = ?',
            (user_id,),
        ).fetchone()[0]
    finally:
        connection.close()
    with client.session_transaction() as current_session:
        current_session['user_id'] = user_id
        current_session['session_version'] = session_version
        current_session['authenticated_at'] = now
        current_session['last_activity'] = now
        current_session[market.CSRF_SESSION_KEY] = token
    return client, token


def fetch_one(query, parameters=()):
    connection = sqlite3.connect(market.DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(query, parameters).fetchone()
    finally:
        connection.close()


def fetch_count(table_name):
    connection = sqlite3.connect(market.DATABASE)
    try:
        return connection.execute(
            f'SELECT COUNT(*) FROM {table_name}'
        ).fetchone()[0]
    finally:
        connection.close()


def login_user(client, username, password):
    response = client.get('/login')
    assert response.status_code == 200
    with client.session_transaction() as current_session:
        token = current_session[market.CSRF_SESSION_KEY]
    return client.post(
        '/login',
        data={
            'csrf_token': token,
            'username': username,
            'password': password,
        },
    )


def test_admin_pages_and_actions_require_role_and_csrf(moderation_database):
    unauthenticated = market.app.test_client()
    response = unauthenticated.get('/admin/moderation')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')

    member, member_token = authenticated_client(REPORTER_ID)
    assert member.get('/admin/moderation').status_code == 403
    assert member.post(
        f'/admin/products/{PRODUCT_ID}/remove',
        data={'csrf_token': member_token, 'reason': VALID_REASON},
    ).status_code == 403

    administrator, _ = authenticated_client(ADMIN_ID)
    assert administrator.post(
        f'/admin/products/{PRODUCT_ID}/remove',
        data={'reason': VALID_REASON},
    ).status_code == 400
    assert fetch_count('product_moderation') == 0

    page = administrator.get('/admin/moderation').get_data(as_text=True)
    assert '신고된 불량 상품' in page
    assert 'bad_actor' in page
    assert '신고 수: 1' in page
    assert fetch_one(
        'SELECT password FROM user WHERE id = ?',
        (TARGET_ID,),
    )['password'] not in page


def test_admin_removal_hides_product_but_preserves_reports_and_audit(
    moderation_database,
):
    administrator, token = authenticated_client(ADMIN_ID)
    reason = '<script>alert("moderation")</script> 불량 상품 확인'
    response = administrator.post(
        f'/admin/products/{PRODUCT_ID}/remove',
        data={'csrf_token': token, 'reason': reason},
    )
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/admin/moderation')

    assert fetch_one(
        'SELECT id FROM product WHERE id = ?',
        (PRODUCT_ID,),
    ) is not None
    moderation = fetch_one(
        'SELECT * FROM product_moderation WHERE product_id = ?',
        (PRODUCT_ID,),
    )
    assert moderation['admin_id'] == ADMIN_ID
    assert moderation['reason'] == reason
    assert fetch_count('report') == 2
    audit = fetch_one(
        '''
        SELECT *
        FROM admin_action_audit
        WHERE action_type = 'product_removed'
        '''
    )
    assert audit['target_product_id'] == PRODUCT_ID
    assert audit['reason'] == reason

    assert '신고된 불량 상품' not in administrator.get(
        '/products'
    ).get_data(as_text=True)
    assert administrator.get(f'/product/{PRODUCT_ID}').status_code == 404
    owner, _ = authenticated_client(TARGET_ID)
    assert '신고된 불량 상품' not in owner.get(
        '/products/manage'
    ).get_data(as_text=True)

    audit_page = administrator.get('/admin/moderation').get_data(as_text=True)
    assert '<script>alert("moderation")</script>' not in audit_page
    assert '&lt;script&gt;alert' in audit_page


def test_user_dormancy_invalidates_sessions_sockets_and_can_be_reactivated(
    moderation_database,
):
    target_client, target_token = authenticated_client(TARGET_ID)
    target_socket = market.socketio.test_client(
        market.app,
        flask_test_client=target_client,
        auth={'csrf_token': target_token},
    )
    assert target_socket.is_connected()

    administrator, admin_token = authenticated_client(ADMIN_ID)
    response = administrator.post(
        f'/admin/users/{TARGET_ID}/dormant',
        data={'csrf_token': admin_token, 'reason': VALID_REASON},
    )
    assert response.status_code == 302
    assert not target_socket.is_connected()

    dormancy = fetch_one(
        'SELECT * FROM user_dormancy WHERE user_id = ?',
        (TARGET_ID,),
    )
    assert dormancy['admin_id'] == ADMIN_ID
    assert dormancy['reason'] == VALID_REASON
    assert fetch_one(
        'SELECT session_version FROM user WHERE id = ?',
        (TARGET_ID,),
    )['session_version'] == 1

    expired_response = target_client.get('/profile')
    assert expired_response.status_code == 302
    assert expired_response.headers['Location'].endswith('/login')
    failed_login = login_user(
        market.app.test_client(),
        'bad_actor',
        TARGET_PASSWORD,
    )
    assert failed_login.status_code == 302
    assert failed_login.headers['Location'].endswith('/login')
    assert '신고된 불량 상품' not in administrator.get(
        '/products'
    ).get_data(as_text=True)

    reporter, _ = authenticated_client(REPORTER_ID)
    assert 'bad_actor' not in reporter.get('/chat').get_data(as_text=True)
    with reporter.session_transaction() as reporter_session:
        reporter_token = reporter_session[market.CSRF_SESSION_KEY]
    report_count = fetch_count('report')
    rejected_report = reporter.post(
        '/report',
        data={
            'csrf_token': reporter_token,
            'target_type': 'user',
            'target_id': TARGET_ID,
            'reason': '휴면 사용자는 신고 대상으로 허용되지 않아야 합니다.',
        },
    )
    assert rejected_report.status_code == 302
    assert fetch_count('report') == report_count

    response = administrator.post(
        f'/admin/users/{TARGET_ID}/reactivate',
        data={
            'csrf_token': admin_token,
            'reason': REACTIVATION_REASON,
        },
    )
    assert response.status_code == 302
    assert fetch_one(
        'SELECT 1 FROM user_dormancy WHERE user_id = ?',
        (TARGET_ID,),
    ) is None
    assert login_user(
        market.app.test_client(),
        'bad_actor',
        TARGET_PASSWORD,
    ).headers['Location'].endswith('/dashboard')
    connection = sqlite3.connect(market.DATABASE)
    try:
        action_types = {
            row[0]
            for row in connection.execute(
                'SELECT action_type FROM admin_action_audit'
            ).fetchall()
        }
    finally:
        connection.close()
    assert {'user_dormant', 'user_reactivated'} <= action_types


def test_admin_cannot_dormant_self_or_another_admin(moderation_database):
    administrator, token = authenticated_client(ADMIN_ID)
    for protected_user_id in (ADMIN_ID, SECOND_ADMIN_ID):
        response = administrator.post(
            f'/admin/users/{protected_user_id}/dormant',
            data={'csrf_token': token, 'reason': VALID_REASON},
        )
        assert response.status_code == 403
    assert fetch_count('user_dormancy') == 0


@pytest.mark.parametrize(
    'reason',
    [
        '',
        '너무 짧음',
        'bad@example.com 개인정보가 포함된 관리 사유입니다.',
        '정상처럼 보이지만\x00제어 문자가 포함된 관리 사유입니다.',
        '가' * (market.MODERATION_REASON_MAX_LENGTH + 1),
    ],
)
def test_moderation_rejects_invalid_reason(moderation_database, reason):
    administrator, token = authenticated_client(ADMIN_ID)
    response = administrator.post(
        f'/admin/products/{PRODUCT_ID}/remove',
        data={'csrf_token': token, 'reason': reason},
    )
    assert response.status_code == 302
    assert fetch_count('product_moderation') == 0
    assert fetch_count('admin_action_audit') == 0


def test_moderation_database_constraints_and_audit_are_enforced(
    moderation_database,
):
    connection = sqlite3.connect(market.DATABASE)
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        with pytest.raises(sqlite3.IntegrityError, match='administrator required'):
            connection.execute(
                '''
                INSERT INTO product_moderation (
                    product_id,
                    admin_id,
                    reason,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                ''',
                (PRODUCT_ID, REPORTER_ID, VALID_REASON, 1),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match='invalid dormancy action'):
            connection.execute(
                '''
                INSERT INTO user_dormancy (
                    user_id,
                    admin_id,
                    reason,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                ''',
                (SECOND_ADMIN_ID, ADMIN_ID, VALID_REASON, 1),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                '''
                INSERT INTO product_moderation (
                    product_id,
                    admin_id,
                    reason,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                ''',
                (PRODUCT_ID, ADMIN_ID, '짧음', 1),
            )
        connection.rollback()
    finally:
        connection.close()

    administrator, token = authenticated_client(ADMIN_ID)
    assert administrator.post(
        f'/admin/products/{PRODUCT_ID}/remove',
        data={'csrf_token': token, 'reason': VALID_REASON},
    ).status_code == 302

    connection = sqlite3.connect(market.DATABASE)
    try:
        with pytest.raises(
            sqlite3.IntegrityError,
            match='product moderation is append-only',
        ):
            connection.execute(
                'DELETE FROM product_moderation WHERE product_id = ?',
                (PRODUCT_ID,),
            )
        connection.rollback()
        with pytest.raises(
            sqlite3.IntegrityError,
            match='admin audit log is append-only',
        ):
            connection.execute(
                'UPDATE admin_action_audit SET reason = ?',
                ('감사 로그 변조 시도 사유입니다.',),
            )
        connection.rollback()
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        connection.close()


def test_admin_role_tool_grants_and_revokes_active_user(
    moderation_database,
):
    connection = admin_user.open_database(moderation_database)
    try:
        granted_user = admin_user.set_admin_role(
            connection,
            'moderation_reporter',
            grant=True,
        )
        assert granted_user['id'] == REPORTER_ID
        assert {
            row['id']
            for row in admin_user.list_admins(connection)
        } >= {ADMIN_ID, REPORTER_ID, SECOND_ADMIN_ID}

        admin_user.set_admin_role(
            connection,
            'moderation_reporter',
            grant=False,
        )
        assert fetch_one(
            'SELECT is_admin FROM user WHERE id = ?',
            (REPORTER_ID,),
        )['is_admin'] == 0
    finally:
        connection.close()


def test_version_21_user_schema_is_extended_for_administration(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / 'version-2-1.db'
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            '''
            CREATE TABLE user (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                bio TEXT,
                failed_login_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until INTEGER,
                session_version INTEGER NOT NULL DEFAULT 0,
                deleted_at INTEGER
            )
            '''
        )
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(market, 'DATABASE', str(database_path))
    market.init_db()
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        user_columns = {
            row['name']
            for row in connection.execute('PRAGMA table_info(user)')
        }
        tables = {
            row['name']
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert 'is_admin' in user_columns
        assert {
            'product_moderation',
            'user_dormancy',
            'admin_action_audit',
        } <= tables
        assert market.moderation_schema_is_current(connection.cursor())
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        connection.close()
