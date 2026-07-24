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
PRODUCT_REPORT_ID = '00000000-0000-0000-0000-000000000606'
USER_REPORT_ID = '00000000-0000-0000-0000-000000000607'
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
                PRODUCT_REPORT_ID,
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
                USER_REPORT_ID,
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


def connect_socket(client, user_id):
    return market.socketio.test_client(
        market.app,
        flask_test_client=client,
        auth={'csrf_token': f'csrf-{user_id}'},
    )


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


def test_admin_account_has_no_chat_or_personal_product_management(
    moderation_database,
):
    client, csrf_token = authenticated_client(ADMIN_ID)

    assert client.get('/chat').status_code == 403
    assert client.get(f'/chat/{TARGET_ID}').status_code == 403
    assert client.get('/products/manage').status_code == 403
    assert client.get('/product/new').status_code == 403
    assert client.get(f'/product/{PRODUCT_ID}/edit').status_code == 403
    assert client.get('/dashboard').get_data(as_text=True).find('실시간 채팅') == -1
    assert '새 상품 등록' not in client.get('/dashboard').get_data(as_text=True)

    report_page = client.get('/report')
    report_html = report_page.get_data(as_text=True)
    assert report_page.status_code == 200
    assert '신고 접수함' in report_html
    assert '상품 사기 의심 정황을 신고합니다.' in report_html
    assert client.post(
        '/report',
        data={'csrf_token': csrf_token},
    ).status_code == 403

    admin_socket = connect_socket(client, ADMIN_ID)
    assert not admin_socket.is_connected()


def test_admin_product_list_requires_reason_and_current_password(
    moderation_database,
):
    client, csrf_token = authenticated_client(ADMIN_ID)
    page = client.get('/admin').get_data(as_text=True)
    assert '불량 상품 관리 삭제' in page
    assert 'name="reason"' in page
    assert 'name="current_password"' in page

    wrong_password = client.post(
        f'/admin/products/{PRODUCT_ID}/remove',
        data={
            'csrf_token': csrf_token,
            'reason': VALID_REASON,
            'current_password': 'WrongAdminPassword123!',
        },
    )
    assert wrong_password.status_code == 302
    assert fetch_count('product_moderation') == 0

    valid_removal = client.post(
        f'/admin/products/{PRODUCT_ID}/remove',
        data={
            'csrf_token': csrf_token,
            'reason': VALID_REASON,
            'current_password': ADMIN_PASSWORD,
        },
    )
    assert valid_removal.status_code == 302
    assert fetch_count('product_moderation') == 1


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
    response = unauthenticated.get('/admin')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')

    member, member_token = authenticated_client(REPORTER_ID)
    assert member.get('/admin').status_code == 403
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

    page = administrator.get('/admin').get_data(as_text=True)
    assert '<h2>관리자 페이지</h2>' in page
    assert '>관리자 페이지</a>' in page
    assert '신고된 불량 상품' in page
    assert 'bad_actor' in page
    assert '신고 수: 1' in page
    assert fetch_one(
        'SELECT password FROM user WHERE id = ?',
        (TARGET_ID,),
    )['password'] not in page


def test_legacy_admin_path_preserves_access_control_and_redirects(
    moderation_database,
):
    unauthenticated = market.app.test_client()
    response = unauthenticated.get('/admin/moderation')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')

    member, _ = authenticated_client(REPORTER_ID)
    assert member.get('/admin/moderation').status_code == 403

    administrator, _ = authenticated_client(ADMIN_ID)
    response = administrator.get('/admin/moderation')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/admin')


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
    assert response.headers['Location'].endswith('/admin')

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
    assert moderation['title_snapshot'] == '신고된 불량 상품'
    assert moderation['description_snapshot'] == (
        '관리 삭제 후에도 증거는 보존됩니다.'
    )
    assert moderation['price_snapshot'] == 50000
    assert moderation['seller_id_snapshot'] == TARGET_ID
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
    assert audit['admin_username_snapshot'] == 'moderation_admin'
    assert audit['target_label_snapshot'] == '신고된 불량 상품'

    assert '신고된 불량 상품' not in administrator.get(
        '/products'
    ).get_data(as_text=True)
    assert administrator.get(f'/product/{PRODUCT_ID}').status_code == 404
    owner, _ = authenticated_client(TARGET_ID)
    assert '신고된 불량 상품' not in owner.get(
        '/products/manage'
    ).get_data(as_text=True)

    audit_page = administrator.get('/admin').get_data(as_text=True)
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
                    created_at,
                    title_snapshot,
                    description_snapshot,
                    price_snapshot,
                    seller_id_snapshot
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    PRODUCT_ID,
                    REPORTER_ID,
                    VALID_REASON,
                    1,
                    '신고된 불량 상품',
                    '관리 삭제 후에도 증거는 보존됩니다.',
                    50000,
                    TARGET_ID,
                ),
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
                    created_at,
                    title_snapshot,
                    description_snapshot,
                    price_snapshot,
                    seller_id_snapshot
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    PRODUCT_ID,
                    ADMIN_ID,
                    '짧음',
                    1,
                    '신고된 불량 상품',
                    '관리 삭제 후에도 증거는 보존됩니다.',
                    50000,
                    TARGET_ID,
                ),
            )
        connection.rollback()
        with pytest.raises(
            sqlite3.IntegrityError,
            match='invalid product moderation snapshot',
        ):
            connection.execute(
                '''
                INSERT INTO product_moderation (
                    product_id,
                    admin_id,
                    reason,
                    created_at,
                    title_snapshot,
                    description_snapshot,
                    price_snapshot,
                    seller_id_snapshot
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    PRODUCT_ID,
                    ADMIN_ID,
                    VALID_REASON,
                    1,
                    '위조된 상품 제목',
                    '관리 삭제 후에도 증거는 보존됩니다.',
                    50000,
                    TARGET_ID,
                ),
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
        with pytest.raises(
            sqlite3.IntegrityError,
            match='invalid admin audit snapshot',
        ):
            connection.execute(
                '''
                INSERT INTO admin_action_audit (
                    id,
                    admin_id,
                    action_type,
                    target_user_id,
                    target_product_id,
                    reason,
                    admin_username_snapshot,
                    target_label_snapshot,
                    created_at
                )
                VALUES (?, ?, 'user_dormant', ?, NULL, ?, ?, ?, ?)
                ''',
                (
                    '00000000-0000-0000-0000-000000000698',
                    ADMIN_ID,
                    TARGET_ID,
                    VALID_REASON,
                    '위조된 관리자',
                    'bad_actor',
                    2,
                ),
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
        original_session_version = fetch_one(
            'SELECT session_version FROM user WHERE id = ?',
            (REPORTER_ID,),
        )['session_version']
        granted_user = admin_user.set_admin_role(
            connection,
            'moderation_reporter',
            grant=True,
            operator_name='security-operator',
            reason='보안 운영 담당자 승인으로 관리자 권한을 부여합니다.',
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
            operator_name='security-operator',
            reason='관리자 업무 종료에 따라 관리자 권한을 해제합니다.',
        )
        role_state = fetch_one(
            '''
            SELECT is_admin, session_version
            FROM user
            WHERE id = ?
            ''',
            (REPORTER_ID,),
        )
        assert role_state['is_admin'] == 0
        assert role_state['session_version'] == original_session_version + 2
        assert fetch_count('admin_role_audit') == 2
        role_audit = fetch_one(
            '''
            SELECT *
            FROM admin_role_audit
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            '''
        )
        assert role_audit['operator_name'] == 'security-operator'
        assert role_audit['target_username_snapshot'] == (
            'moderation_reporter'
        )

        with pytest.raises(
            sqlite3.IntegrityError,
            match='admin role audit log is append-only',
        ):
            connection.execute(
                'DELETE FROM admin_role_audit WHERE id = ?',
                (role_audit['id'],),
            )
        connection.rollback()
        with pytest.raises(
            sqlite3.IntegrityError,
            match='invalid admin role audit snapshot',
        ):
            connection.execute(
                '''
                INSERT INTO admin_role_audit (
                    id,
                    operator_name,
                    target_user_id,
                    target_username_snapshot,
                    action_type,
                    reason,
                    created_at
                )
                VALUES (?, ?, ?, ?, 'admin_revoked', ?, ?)
                ''',
                (
                    '00000000-0000-0000-0000-000000000699',
                    'security-operator',
                    REPORTER_ID,
                    '위조된 사용자명',
                    '관리자 역할 감사 Snapshot 변조를 차단합니다.',
                    3,
                ),
            )
        connection.rollback()
    finally:
        connection.close()


def test_report_review_requires_recent_auth_and_is_append_only(
    moderation_database,
):
    administrator, token = authenticated_client(ADMIN_ID)
    with administrator.session_transaction() as current_session:
        current_session['authenticated_at'] = (
            int(time.time()) - market.ADMIN_RECENT_AUTH_SECONDS - 1
        )
        current_session['last_activity'] = int(time.time())

    response = administrator.post(
        f'/admin/reports/{PRODUCT_REPORT_ID}/review',
        data={
            'csrf_token': token,
            'status': 'resolved',
            'reason': '신고 내용과 상품 증거를 확인하여 처리 완료했습니다.',
        },
    )
    assert response.status_code == 302
    assert fetch_count('report_review') == 0

    response = administrator.post(
        f'/admin/reports/{PRODUCT_REPORT_ID}/review',
        data={
            'csrf_token': token,
            'status': 'resolved',
            'reason': '신고 내용과 상품 증거를 확인하여 처리 완료했습니다.',
            'current_password': ADMIN_PASSWORD,
        },
    )
    assert response.status_code == 302
    review = fetch_one(
        'SELECT * FROM report_review WHERE report_id = ?',
        (PRODUCT_REPORT_ID,),
    )
    assert review['admin_id'] == ADMIN_ID
    assert review['admin_username_snapshot'] == 'moderation_admin'
    assert review['status'] == 'resolved'

    xss_reason = '<script>alert("report-review-xss")</script> 신고 사유'
    connection = sqlite3.connect(market.DATABASE)
    try:
        connection.execute(
            'UPDATE report SET reason = ? WHERE id = ?',
            (xss_reason, PRODUCT_REPORT_ID),
        )
        connection.commit()
    finally:
        connection.close()
    page = administrator.get('/admin').get_data(as_text=True)
    assert xss_reason not in page
    assert '&lt;script&gt;alert' in page
    assert '처리 완료' in page

    connection = sqlite3.connect(market.DATABASE)
    try:
        with pytest.raises(
            sqlite3.IntegrityError,
            match='invalid report review snapshot',
        ):
            connection.execute(
                '''
                INSERT INTO report_review (
                    report_id,
                    admin_id,
                    admin_username_snapshot,
                    status,
                    note,
                    reviewed_at
                )
                VALUES (?, ?, ?, 'dismissed', ?, ?)
                ''',
                (
                    USER_REPORT_ID,
                    ADMIN_ID,
                    '위조된 관리자',
                    '신고 검토자 Snapshot 변조를 차단하기 위한 사유입니다.',
                    3,
                ),
            )
        connection.rollback()
        with pytest.raises(
            sqlite3.IntegrityError,
            match='report review is append-only',
        ):
            connection.execute(
                'UPDATE report_review SET status = ? WHERE report_id = ?',
                ('dismissed', PRODUCT_REPORT_ID),
            )
        connection.rollback()
    finally:
        connection.close()


def test_admin_actions_are_rate_limited(moderation_database, monkeypatch):
    monkeypatch.setattr(market, 'ADMIN_ACTION_RATE_LIMIT', 1)
    administrator, token = authenticated_client(ADMIN_ID)

    first_response = administrator.post(
        f'/admin/reports/{PRODUCT_REPORT_ID}/review',
        data={
            'csrf_token': token,
            'status': 'resolved',
            'reason': '첫 번째 신고를 확인하여 정상적으로 처리 완료했습니다.',
        },
    )
    second_response = administrator.post(
        f'/admin/reports/{USER_REPORT_ID}/review',
        data={
            'csrf_token': token,
            'status': 'dismissed',
            'reason': '두 번째 신고에 대한 반복 처리 제한을 검증합니다.',
        },
    )

    assert first_response.status_code == 302
    assert second_response.status_code == 429
    assert fetch_count('report_review') == 1


def test_version_30_moderation_rows_receive_safe_snapshots(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / 'version-3-0.db'
    connection = sqlite3.connect(database_path)
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        connection.executescript(
            '''
            CREATE TABLE user (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                bio TEXT,
                failed_login_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until INTEGER,
                session_version INTEGER NOT NULL DEFAULT 0,
                is_admin INTEGER NOT NULL DEFAULT 0
                    CHECK(is_admin IN (0, 1)),
                deleted_at INTEGER
            );
            CREATE TABLE product (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL
                    CHECK(length(trim(title)) BETWEEN 1 AND 100)
                    CHECK(instr(title, char(0)) = 0),
                description TEXT NOT NULL
                    CHECK(length(trim(description)) BETWEEN 1 AND 2000)
                    CHECK(instr(description, char(0)) = 0),
                price INTEGER NOT NULL
                    CHECK(
                        typeof(price) = 'integer'
                        AND price BETWEEN 0 AND 1000000000
                    ),
                seller_id TEXT NOT NULL,
                FOREIGN KEY (seller_id) REFERENCES user(id) ON DELETE RESTRICT
            );
            CREATE TABLE product_moderation (
                product_id TEXT PRIMARY KEY,
                admin_id TEXT NOT NULL,
                reason TEXT NOT NULL
                    CHECK(length(trim(reason)) BETWEEN 10 AND 500)
                    CHECK(instr(reason, char(0)) = 0),
                created_at INTEGER NOT NULL
                    CHECK(typeof(created_at) = 'integer' AND created_at >= 0),
                FOREIGN KEY (product_id)
                    REFERENCES product(id) ON DELETE RESTRICT,
                FOREIGN KEY (admin_id) REFERENCES user(id) ON DELETE RESTRICT
            );
            CREATE TABLE admin_action_audit (
                id TEXT PRIMARY KEY,
                admin_id TEXT NOT NULL,
                action_type TEXT NOT NULL
                    CHECK(
                        action_type IN (
                            'product_removed',
                            'user_dormant',
                            'user_reactivated'
                        )
                    ),
                target_user_id TEXT,
                target_product_id TEXT,
                reason TEXT NOT NULL
                    CHECK(length(trim(reason)) BETWEEN 10 AND 500)
                    CHECK(instr(reason, char(0)) = 0),
                created_at INTEGER NOT NULL
                    CHECK(typeof(created_at) = 'integer' AND created_at >= 0),
                CHECK(
                    (
                        action_type = 'product_removed'
                        AND target_product_id IS NOT NULL
                        AND target_user_id IS NULL
                    )
                    OR
                    (
                        action_type IN ('user_dormant', 'user_reactivated')
                        AND target_user_id IS NOT NULL
                        AND target_product_id IS NULL
                    )
                ),
                FOREIGN KEY (admin_id) REFERENCES user(id) ON DELETE RESTRICT,
                FOREIGN KEY (target_user_id)
                    REFERENCES user(id) ON DELETE RESTRICT,
                FOREIGN KEY (target_product_id)
                    REFERENCES product(id) ON DELETE RESTRICT
            );
            '''
        )
        for user_id, username, is_admin in (
            (ADMIN_ID, 'moderation_admin', 1),
            (TARGET_ID, 'bad_actor', 0),
        ):
            connection.execute(
                '''
                INSERT INTO user (id, username, password, is_admin)
                VALUES (?, ?, ?, ?)
                ''',
                (
                    user_id,
                    username,
                    market.password_hasher.hash(ADMIN_PASSWORD),
                    is_admin,
                ),
            )
        connection.execute(
            '''
            INSERT INTO product (id, title, description, price, seller_id)
            VALUES (?, '기존 제재 상품', '기존 제재 설명', 7000, ?)
            ''',
            (PRODUCT_ID, TARGET_ID),
        )
        connection.execute(
            '''
            INSERT INTO product_moderation (
                product_id,
                admin_id,
                reason,
                created_at
            )
            VALUES (?, ?, ?, 1)
            ''',
            (PRODUCT_ID, ADMIN_ID, VALID_REASON),
        )
        connection.execute(
            '''
            INSERT INTO admin_action_audit (
                id,
                admin_id,
                action_type,
                target_user_id,
                target_product_id,
                reason,
                created_at
            )
            VALUES (?, ?, 'product_removed', NULL, ?, ?, 1)
            ''',
            (
                '00000000-0000-0000-0000-000000000697',
                ADMIN_ID,
                PRODUCT_ID,
                VALID_REASON,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(market, 'DATABASE', str(database_path))
    market.init_db()

    product_snapshot = fetch_one(
        'SELECT * FROM product_moderation WHERE product_id = ?',
        (PRODUCT_ID,),
    )
    audit_snapshot = fetch_one(
        '''
        SELECT *
        FROM admin_action_audit
        WHERE target_product_id = ?
        ''',
        (PRODUCT_ID,),
    )
    assert product_snapshot['title_snapshot'] == '기존 제재 상품'
    assert product_snapshot['description_snapshot'] == '기존 제재 설명'
    assert product_snapshot['price_snapshot'] == 7000
    assert product_snapshot['seller_id_snapshot'] == TARGET_ID
    assert audit_snapshot['admin_username_snapshot'] == 'moderation_admin'
    assert audit_snapshot['target_label_snapshot'] == '기존 제재 상품'


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
