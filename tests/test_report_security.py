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


VALID_REASON = '거래 과정에서 반복적으로 부적절한 행동을 했습니다.'
REPORTER_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'reporter.test'))
OWNER_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'owner.test'))
TARGET_USER_IDS = [
    str(uuid.uuid5(uuid.NAMESPACE_DNS, f'target-{index}.test'))
    for index in range(1, 8)
]
TARGET_PRODUCT_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'target-product.test'))
OWN_PRODUCT_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'own-product.test'))


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

    connection = sqlite3.connect(database_path)
    connection.execute('PRAGMA foreign_keys = ON')
    password_hash = market.DUMMY_PASSWORD_HASH
    users = [
        (REPORTER_ID, 'reporter', password_hash),
        (OWNER_ID, 'product_owner', password_hash),
        *[
            (target_id, f'target_{index}', password_hash)
            for index, target_id in enumerate(TARGET_USER_IDS, start=1)
        ],
    ]
    try:
        connection.executemany(
            'INSERT INTO user (id, username, password) VALUES (?, ?, ?)',
            users,
        )
        connection.execute(
            "UPDATE user SET account_type = 'business' WHERE id = ?",
            (OWNER_ID,),
        )
        connection.executemany(
            '''
            INSERT INTO product (id, title, description, price, seller_id)
            VALUES (?, ?, ?, ?, ?)
            ''',
            [
                (
                    TARGET_PRODUCT_ID,
                    '신고 대상 상품',
                    '다른 사용자가 등록한 상품입니다.',
                    10000,
                    OWNER_ID,
                ),
                (
                    OWN_PRODUCT_ID,
                    '본인 상품',
                    '신고자가 등록한 상품입니다.',
                    20000,
                    REPORTER_ID,
                ),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    with market.app.test_client() as test_client:
        yield test_client


def login_as(client, user_id):
    now = int(time.time())
    with client.session_transaction() as current_session:
        current_session.clear()
        current_session.permanent = True
        current_session['user_id'] = user_id
        current_session['authenticated_at'] = now
        current_session['last_activity'] = now


def get_csrf_token(client, path='/report'):
    response = client.get(path)
    assert response.status_code == 200
    with client.session_transaction() as current_session:
        return current_session[market.CSRF_SESSION_KEY]


def submit_report(
    client,
    target_type='user',
    target_id=TARGET_USER_IDS[0],
    reason=VALID_REASON,
    remote_address='127.0.0.1',
    headers=None,
):
    token = get_csrf_token(client)
    return client.post(
        '/report',
        data={
            'csrf_token': token,
            'target_type': target_type,
            'target_id': target_id,
            'reason': reason,
        },
        environ_overrides={'REMOTE_ADDR': remote_address},
        headers=headers,
    )


def fetch_rows(table):
    connection = sqlite3.connect(market.DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()
    finally:
        connection.close()


def test_report_requires_authenticated_user(client):
    response = client.get('/report')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')

    response = client.post(
        '/report',
        data={
            'target_type': 'user',
            'target_id': TARGET_USER_IDS[0],
            'reason': VALID_REASON,
        },
    )
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
    assert fetch_rows('report') == []


def test_report_submission_requires_csrf(client):
    login_as(client, REPORTER_ID)
    response = client.post(
        '/report',
        data={
            'target_type': 'user',
            'target_id': TARGET_USER_IDS[0],
            'reason': VALID_REASON,
        },
    )
    assert response.status_code == 400
    assert fetch_rows('report') == []
    assert fetch_rows('report_audit_log') == []


def test_valid_user_report_is_normalized_and_audited(client):
    login_as(client, REPORTER_ID)
    response = submit_report(
        client,
        reason='  Ａ사용자가 거래 과정에서 부적절한 행동을 했습니다.  ',
    )
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/dashboard')

    report = fetch_rows('report')[0]
    assert report['reporter_id'] == REPORTER_ID
    assert report['target_type'] == 'user'
    assert report['target_user_id'] == TARGET_USER_IDS[0]
    assert report['target_product_id'] is None
    assert (
        report['reason']
        == 'A사용자가 거래 과정에서 부적절한 행동을 했습니다.'
    )
    assert isinstance(report['created_at'], int)

    audit_log = fetch_rows('report_audit_log')[0]
    assert audit_log['event_type'] == 'report_created'
    assert audit_log['actor_id'] == REPORTER_ID
    assert audit_log['target_type'] == 'user'
    assert audit_log['target_id'] == TARGET_USER_IDS[0]
    assert len(audit_log['source_ip_hash']) == 64
    assert audit_log['source_ip_hash'] != '127.0.0.1'

    connection = sqlite3.connect(market.DATABASE)
    try:
        audit_columns = {
            row[1]
            for row in connection.execute(
                'PRAGMA table_info(report_audit_log)'
            ).fetchall()
        }
    finally:
        connection.close()
    assert 'reason' not in audit_columns


def test_valid_product_report_is_stored_with_product_reference(client):
    login_as(client, REPORTER_ID)
    response = submit_report(
        client,
        target_type='product',
        target_id=TARGET_PRODUCT_ID,
    )
    assert response.status_code == 302

    report = fetch_rows('report')[0]
    assert report['target_type'] == 'product'
    assert report['target_user_id'] is None
    assert report['target_product_id'] == TARGET_PRODUCT_ID


def test_business_cannot_access_or_submit_reports(client):
    login_as(client, OWNER_ID)
    profile = client.get('/profile').get_data(as_text=True)
    assert '신고하기' not in profile
    assert client.get('/report').status_code == 403

    token = get_csrf_token(client, '/profile')
    response = client.post(
        '/report',
        data={
            'csrf_token': token,
            'target_type': 'product',
            'target_id': TARGET_PRODUCT_ID,
            'reason': VALID_REASON,
        },
    )
    assert response.status_code == 403
    assert fetch_rows('report') == []

    connection = sqlite3.connect(market.DATABASE)
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        with pytest.raises(
            sqlite3.IntegrityError,
            match='regular user reporter required',
        ):
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
                    str(uuid.uuid4()),
                    OWNER_ID,
                    TARGET_USER_IDS[0],
                    VALID_REASON,
                    int(time.time()),
                ),
            )
    finally:
        connection.close()


def test_report_audit_log_is_append_only(client):
    login_as(client, REPORTER_ID)
    assert submit_report(client).status_code == 302
    audit_id = fetch_rows('report_audit_log')[0]['id']

    connection = sqlite3.connect(market.DATABASE)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                '''
                UPDATE report_audit_log
                SET event_type = 'report_migrated'
                WHERE id = ?
                ''',
                (audit_id,),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                'DELETE FROM report_audit_log WHERE id = ?',
                (audit_id,),
            )
        connection.rollback()
    finally:
        connection.close()
    assert len(fetch_rows('report_audit_log')) == 1


@pytest.mark.parametrize(
    ('target_type', 'target_id'),
    [
        ('', TARGET_USER_IDS[0]),
        ('admin', TARGET_USER_IDS[0]),
        ('user', ''),
        ('user', 'not-a-uuid'),
        ('user', str(uuid.uuid4())),
        ('product', str(uuid.uuid4())),
        ('user', REPORTER_ID),
        ('product', OWN_PRODUCT_ID),
    ],
)
def test_report_rejects_invalid_missing_or_self_target(
    client,
    target_type,
    target_id,
):
    login_as(client, REPORTER_ID)
    response = submit_report(client, target_type, target_id)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/report')
    assert fetch_rows('report') == []
    audit_logs = fetch_rows('report_audit_log')
    assert len(audit_logs) == 1
    assert audit_logs[0]['event_type'] == 'report_rejected_validation'
    assert audit_logs[0]['target_id'] is None


@pytest.mark.parametrize(
    'reason',
    [
        '',
        '   ',
        '짧은 사유',
        'a' * (market.REPORT_REASON_MAX_LENGTH + 1),
        '정상 길이의 신고 사유입니다.\x00',
        '정상 길이의 신고 사유입니다.\u202e',
    ],
)
def test_report_rejects_invalid_reason(client, reason):
    login_as(client, REPORTER_ID)
    response = submit_report(client, reason=reason)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/report')
    assert fetch_rows('report') == []


@pytest.mark.parametrize(
    'reason',
    [
        '연락처는 user@example.com이며 신고 사유를 설명합니다.',
        '연락처는 010-1234-5678이며 신고 사유를 설명합니다.',
        '주민등록번호 900101-1234567이 포함된 신고 사유입니다.',
        (
            '연락처는 ０１０－１２３４－５６７８이며 '
            '신고 사유를 설명합니다.'
        ),
    ],
)
def test_report_rejects_sensitive_personal_information(client, reason):
    login_as(client, REPORTER_ID)
    response = submit_report(client, reason=reason)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/report')
    assert fetch_rows('report') == []

    audit_log = fetch_rows('report_audit_log')[0]
    assert audit_log['event_type'] == 'report_rejected_sensitive_data'
    assert 'reason' not in audit_log.keys()
    assert reason not in tuple(audit_log)


def test_report_attempt_limit_is_enforced_per_ip(client, monkeypatch):
    monkeypatch.setattr(market, 'MAX_REPORT_ATTEMPTS_PER_IP', 2)
    login_as(client, REPORTER_ID)

    for _ in range(2):
        response = submit_report(
            client,
            target_type='invalid',
            remote_address='203.0.113.10',
        )
        assert response.status_code == 302

    blocked_response = submit_report(
        client,
        target_type='invalid',
        remote_address='203.0.113.10',
    )
    assert blocked_response.status_code == 429
    assert [
        row['event_type']
        for row in fetch_rows('report_audit_log')
    ].count('report_rejected_ip_rate') == 1

    repeated_block = submit_report(
        client,
        target_type='invalid',
        remote_address='203.0.113.10',
    )
    assert repeated_block.status_code == 429
    assert [
        row['event_type']
        for row in fetch_rows('report_audit_log')
    ].count('report_rejected_ip_rate') == 1

    different_ip_response = submit_report(
        client,
        target_type='invalid',
        remote_address='203.0.113.11',
    )
    assert different_ip_response.status_code == 302


def test_report_attempt_limit_is_enforced_per_user(client, monkeypatch):
    monkeypatch.setattr(market, 'MAX_REPORT_ATTEMPTS_PER_USER', 2)
    login_as(client, REPORTER_ID)

    for index in range(2):
        response = submit_report(
            client,
            target_type='invalid',
            remote_address=f'203.0.113.{20 + index}',
        )
        assert response.status_code == 302

    blocked_response = submit_report(
        client,
        target_type='invalid',
        remote_address='203.0.113.30',
    )
    assert blocked_response.status_code == 429
    assert any(
        row['event_type'] == 'report_rejected_user_rate'
        for row in fetch_rows('report_audit_log')
    )


def test_untrusted_forwarded_address_is_not_used_for_ip_hash(client):
    login_as(client, REPORTER_ID)
    submit_report(
        client,
        remote_address='203.0.113.40',
        headers={'X-Forwarded-For': '198.51.100.99'},
    )
    first_hash = fetch_rows('report_audit_log')[0]['source_ip_hash']

    connection = sqlite3.connect(market.DATABASE)
    try:
        connection.execute('DELETE FROM report_rate_limit')
        connection.commit()
    finally:
        connection.close()

    submit_report(
        client,
        target_type='invalid',
        remote_address='203.0.113.40',
        headers={'X-Forwarded-For': '192.0.2.99'},
    )
    audit_logs = fetch_rows('report_audit_log')
    assert {
        row['source_ip_hash']
        for row in audit_logs
    } == {first_hash}
    assert market.app.config['TRUSTED_PROXY_COUNT'] == 0


def test_ip_hash_normalizes_equivalent_ipv6_addresses():
    with market.app.test_request_context(
        environ_overrides={'REMOTE_ADDR': '2001:0db8:0:0:0:0:0:1'}
    ):
        expanded_hash = market.get_client_ip_hash()
    with market.app.test_request_context(
        environ_overrides={'REMOTE_ADDR': '2001:db8::1'}
    ):
        compressed_hash = market.get_client_ip_hash()
    assert expanded_hash == compressed_hash


@pytest.mark.parametrize('value', ['not-a-number', '-1', '6'])
def test_trusted_proxy_count_rejects_unsafe_values(monkeypatch, value):
    monkeypatch.setenv('MARKET_TRUSTED_PROXY_COUNT', value)
    with pytest.raises(RuntimeError):
        market.get_integer_env('MARKET_TRUSTED_PROXY_COUNT', 0)


def test_report_reason_is_not_reflected_as_executable_html(client):
    login_as(client, REPORTER_ID)
    xss_reason = '<script>alert("report-xss")</script> 신고 사유입니다.'
    response = submit_report(client, reason=xss_reason)
    assert response.status_code == 302
    assert fetch_rows('report')[0]['reason'] == xss_reason

    for path in ['/report', '/dashboard']:
        page = client.get(path).get_data(as_text=True)
        assert xss_reason not in page
        assert '<script>alert("report-xss")</script>' not in page


def test_duplicate_report_is_rate_limited_and_audited(client):
    login_as(client, REPORTER_ID)
    assert submit_report(client).status_code == 302
    duplicate_response = submit_report(client)

    assert duplicate_response.status_code == 429
    assert len(fetch_rows('report')) == 1
    audit_logs = fetch_rows('report_audit_log')
    assert len(audit_logs) == 2
    assert {
        row['event_type']
        for row in audit_logs
    } == {'report_created', 'report_rejected_duplicate'}


def test_report_rate_limit_blocks_sixth_report_within_one_hour(client):
    login_as(client, REPORTER_ID)
    for target_id in TARGET_USER_IDS[:market.MAX_REPORTS_PER_WINDOW]:
        assert submit_report(client, target_id=target_id).status_code == 302

    response = submit_report(
        client,
        target_id=TARGET_USER_IDS[market.MAX_REPORTS_PER_WINDOW],
    )
    assert response.status_code == 429
    assert len(fetch_rows('report')) == market.MAX_REPORTS_PER_WINDOW
    audit_logs = fetch_rows('report_audit_log')
    assert len(audit_logs) == market.MAX_REPORTS_PER_WINDOW + 1
    assert any(
        row['event_type'] == 'report_rejected_user_rate'
        for row in audit_logs
    )


def test_report_and_audit_insert_are_atomic(client, monkeypatch):
    login_as(client, REPORTER_ID)

    def fail_audit_insert(*args, **kwargs):
        raise sqlite3.IntegrityError('simulated audit failure')

    monkeypatch.setattr(market, 'add_report_audit_log', fail_audit_insert)
    response = submit_report(client)
    assert response.status_code == 400
    assert fetch_rows('report') == []
    assert fetch_rows('report_audit_log') == []


def test_database_constraints_reject_invalid_reports(client):
    connection = sqlite3.connect(market.DATABASE)
    connection.execute('PRAGMA foreign_keys = ON')
    now = int(time.time())

    invalid_rows = [
        (
            str(uuid.uuid4()),
            str(uuid.uuid4()),
            'user',
            TARGET_USER_IDS[0],
            None,
            VALID_REASON,
            now,
        ),
        (
            str(uuid.uuid4()),
            REPORTER_ID,
            'user',
            str(uuid.uuid4()),
            None,
            VALID_REASON,
            now,
        ),
        (
            str(uuid.uuid4()),
            REPORTER_ID,
            'product',
            None,
            str(uuid.uuid4()),
            VALID_REASON,
            now,
        ),
        (
            str(uuid.uuid4()),
            REPORTER_ID,
            'user',
            REPORTER_ID,
            None,
            VALID_REASON,
            now,
        ),
        (
            str(uuid.uuid4()),
            REPORTER_ID,
            'product',
            None,
            OWN_PRODUCT_ID,
            VALID_REASON,
            now,
        ),
        (
            str(uuid.uuid4()),
            REPORTER_ID,
            'user',
            TARGET_USER_IDS[0],
            None,
            '짧음',
            now,
        ),
        (
            str(uuid.uuid4()),
            REPORTER_ID,
            'product',
            TARGET_USER_IDS[0],
            TARGET_PRODUCT_ID,
            VALID_REASON,
            now,
        ),
    ]
    try:
        for row in invalid_rows:
            with pytest.raises(sqlite3.IntegrityError):
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
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''',
                    row,
                )
            connection.rollback()

        valid_row = (
            str(uuid.uuid4()),
            REPORTER_ID,
            'user',
            TARGET_USER_IDS[0],
            None,
            VALID_REASON,
            now,
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
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            valid_row,
        )
        connection.commit()
        duplicate_row = (str(uuid.uuid4()), *valid_row[1:])
        with pytest.raises(sqlite3.IntegrityError):
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
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                duplicate_row,
            )
        connection.rollback()

        for target_id in TARGET_USER_IDS[1:market.MAX_REPORTS_PER_WINDOW]:
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
                    str(uuid.uuid4()),
                    REPORTER_ID,
                    target_id,
                    VALID_REASON,
                    now,
                ),
            )
        connection.commit()
        with pytest.raises(
            sqlite3.IntegrityError,
            match='report rate limit exceeded',
        ):
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
                    str(uuid.uuid4()),
                    REPORTER_ID,
                    TARGET_USER_IDS[market.MAX_REPORTS_PER_WINDOW],
                    VALID_REASON,
                    now,
                ),
            )
        connection.rollback()
    finally:
        connection.close()


def test_reported_product_cannot_be_deleted_and_evidence_is_preserved(client):
    login_as(client, REPORTER_ID)
    assert submit_report(
        client,
        target_type='product',
        target_id=TARGET_PRODUCT_ID,
    ).status_code == 302

    login_as(client, OWNER_ID)
    token = get_csrf_token(client, f'/product/{TARGET_PRODUCT_ID}')
    response = client.post(
        f'/product/{TARGET_PRODUCT_ID}/delete',
        data={'csrf_token': token},
    )
    assert response.status_code == 302
    assert response.headers['Location'].endswith(f'/product/{TARGET_PRODUCT_ID}')

    connection = sqlite3.connect(market.DATABASE)
    try:
        product_exists = connection.execute(
            'SELECT 1 FROM product WHERE id = ?',
            (TARGET_PRODUCT_ID,),
        ).fetchone()
    finally:
        connection.close()
    assert product_exists is not None
    assert len(fetch_rows('report')) == 1


def test_version_13_audit_schema_is_migrated_without_losing_events(client):
    legacy_audit_id = str(uuid.uuid4())
    connection = sqlite3.connect(market.DATABASE)
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        connection.execute(
            'DROP TRIGGER IF EXISTS prevent_report_audit_log_update'
        )
        connection.execute(
            'DROP TRIGGER IF EXISTS prevent_report_audit_log_delete'
        )
        connection.execute('DROP TABLE report_audit_log')
        connection.execute(
            '''
            CREATE TABLE report_audit_log (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL
                    CHECK(event_type IN ('report_created', 'report_migrated')),
                actor_id TEXT NOT NULL,
                target_type TEXT NOT NULL
                    CHECK(target_type IN ('user', 'product')),
                target_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (actor_id) REFERENCES user(id) ON DELETE RESTRICT
            )
            '''
        )
        connection.execute(
            '''
            INSERT INTO report_audit_log (
                id,
                event_type,
                actor_id,
                target_type,
                target_id,
                created_at
            )
            VALUES (?, 'report_created', ?, 'user', ?, ?)
            ''',
            (
                legacy_audit_id,
                REPORTER_ID,
                TARGET_USER_IDS[0],
                int(time.time()),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    market.init_db()

    connection = sqlite3.connect(market.DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        migrated_log = connection.execute(
            'SELECT * FROM report_audit_log WHERE id = ?',
            (legacy_audit_id,),
        ).fetchone()
        audit_columns = {
            row['name']
            for row in connection.execute(
                'PRAGMA table_info(report_audit_log)'
            ).fetchall()
        }
    finally:
        connection.close()

    assert migrated_log['event_type'] == 'report_created'
    assert migrated_log['source_ip_hash'] is None
    assert 'source_ip_hash' in audit_columns


def test_legacy_report_schema_is_migrated_and_audited(tmp_path, monkeypatch):
    database_path = tmp_path / 'legacy-report.db'
    reporter_id = str(uuid.uuid4())
    target_user_id = str(uuid.uuid4())
    owner_id = str(uuid.uuid4())
    product_id = str(uuid.uuid4())
    user_report_id = str(uuid.uuid4())
    product_report_id = str(uuid.uuid4())
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
            CREATE TABLE product (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                price TEXT NOT NULL,
                seller_id TEXT NOT NULL
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE report (
                id TEXT PRIMARY KEY,
                reporter_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                reason TEXT NOT NULL
            )
            '''
        )
        connection.executemany(
            'INSERT INTO user (id, username, password) VALUES (?, ?, ?)',
            [
                (reporter_id, 'legacy_reporter', 'StrongPassword123!'),
                (target_user_id, 'legacy_target', 'StrongPassword123!'),
                (owner_id, 'legacy_owner', 'StrongPassword123!'),
            ],
        )
        connection.execute(
            '''
            INSERT INTO product (id, title, description, price, seller_id)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (product_id, '기존 상품', '기존 상품 설명', '10000', owner_id),
        )
        connection.executemany(
            '''
            INSERT INTO report (id, reporter_id, target_id, reason)
            VALUES (?, ?, ?, ?)
            ''',
            [
                (
                    user_report_id,
                    reporter_id,
                    target_user_id,
                    '기존 사용자 신고 사유입니다.',
                ),
                (
                    product_report_id,
                    reporter_id,
                    product_id,
                    '기존 상품 신고 사유입니다.',
                ),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(market, 'DATABASE', str(database_path))
    market.init_db()

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        reports = connection.execute(
            'SELECT * FROM report ORDER BY target_type'
        ).fetchall()
        audit_logs = connection.execute(
            'SELECT * FROM report_audit_log ORDER BY target_type'
        ).fetchall()
        foreign_key_issues = connection.execute(
            'PRAGMA foreign_key_check'
        ).fetchall()
        report_columns = {
            row['name']
            for row in connection.execute('PRAGMA table_info(report)').fetchall()
        }
    finally:
        connection.close()

    assert len(reports) == 2
    assert {row['target_type'] for row in reports} == {'user', 'product'}
    assert all(isinstance(row['created_at'], int) for row in reports)
    assert len(audit_logs) == 2
    assert {row['event_type'] for row in audit_logs} == {'report_migrated'}
    assert foreign_key_issues == []
    assert {
        'target_type',
        'target_user_id',
        'target_product_id',
        'created_at',
    } <= report_columns


def test_invalid_legacy_report_aborts_migration_without_data_loss(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / 'invalid-legacy-report.db'
    reporter_id = str(uuid.uuid4())
    report_id = str(uuid.uuid4())
    invalid_target_id = str(uuid.uuid4())
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
            (reporter_id, 'legacy_reporter', 'StrongPassword123!'),
        )
        connection.execute(
            '''
            CREATE TABLE report (
                id TEXT PRIMARY KEY,
                reporter_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                reason TEXT NOT NULL
            )
            '''
        )
        connection.execute(
            '''
            INSERT INTO report (id, reporter_id, target_id, reason)
            VALUES (?, ?, ?, ?)
            ''',
            (report_id, reporter_id, invalid_target_id, VALID_REASON),
        )
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(market, 'DATABASE', str(database_path))
    with pytest.raises(RuntimeError):
        market.init_db()

    connection = sqlite3.connect(database_path)
    try:
        stored_report = connection.execute(
            'SELECT id, reporter_id, target_id, reason FROM report'
        ).fetchone()
    finally:
        connection.close()
    assert stored_report == (
        report_id,
        reporter_id,
        invalid_target_id,
        VALID_REASON,
    )
