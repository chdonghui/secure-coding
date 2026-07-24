import os
import re
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


SENDER_ID = '00000000-0000-0000-0000-000000000701'
RECIPIENT_ID = '00000000-0000-0000-0000-000000000702'
OUTSIDER_ID = '00000000-0000-0000-0000-000000000703'
ADMIN_ID = '00000000-0000-0000-0000-000000000704'
SENDER_USERNAME = 'transfer_sender'
RECIPIENT_USERNAME = 'transfer_recipient'
OUTSIDER_USERNAME = 'transfer_outsider'
ADMIN_USERNAME = 'transfer_admin'
SENDER_PASSWORD = 'TransferSender123!'
RECIPIENT_PASSWORD = 'TransferRecipient123!'
INITIAL_SENDER_BALANCE = 100_000
INITIAL_RECIPIENT_BALANCE = 1_000


@pytest.fixture
def transfer_database(tmp_path, monkeypatch):
    database_path = tmp_path / 'test-transfer.db'
    monkeypatch.setattr(market, 'DATABASE', str(database_path))
    market.app.config.update(
        DEBUG=False,
        SECRET_KEY='pytest-only-app-secret-key-with-more-than-32-characters',
        SESSION_COOKIE_SECURE=False,
        REQUIRE_HTTPS=False,
        TESTING=True,
    )
    market.init_db()
    connection = sqlite3.connect(database_path)
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        users = (
            (
                SENDER_ID,
                SENDER_USERNAME,
                SENDER_PASSWORD,
            ),
            (
                RECIPIENT_ID,
                RECIPIENT_USERNAME,
                RECIPIENT_PASSWORD,
            ),
            (
                OUTSIDER_ID,
                OUTSIDER_USERNAME,
                'TransferOutsider123!',
            ),
            (
                ADMIN_ID,
                ADMIN_USERNAME,
                'TransferAdmin123!',
            ),
        )
        for user_id, username, password in users:
            connection.execute(
                '''
                INSERT INTO user (id, username, password)
                VALUES (?, ?, ?)
                ''',
                (
                    user_id,
                    username,
                    market.password_hasher.hash(password),
                ),
            )
        connection.execute(
            'UPDATE user SET is_admin = 1 WHERE id = ?',
            (ADMIN_ID,),
        )
        now = int(time.time())
        for user_id, amount in (
            (SENDER_ID, INITIAL_SENDER_BALANCE),
            (RECIPIENT_ID, INITIAL_RECIPIENT_BALANCE),
        ):
            connection.execute(
                '''
                INSERT INTO wallet_adjustment (
                    id,
                    user_id,
                    amount,
                    source_type,
                    created_at
                )
                VALUES (?, ?, ?, 'quickstart_demo_credit', ?)
                ''',
                (str(uuid.uuid4()), user_id, amount, now),
            )
        connection.commit()
    finally:
        connection.close()
    return database_path


def authenticated_client(user_id=SENDER_ID):
    client = market.app.test_client()
    token = f'csrf-{user_id}'
    now = int(time.time())
    with client.session_transaction() as current_session:
        current_session['user_id'] = user_id
        current_session['session_version'] = 0
        current_session['authenticated_at'] = now
        current_session['last_activity'] = now
        current_session[market.CSRF_SESSION_KEY] = token
    return client, token


def transfer_request_id(client):
    page = client.get('/transfers')
    assert page.status_code == 200
    match = re.search(
        r'name="request_id"\s+value="([0-9a-f-]{36})"',
        page.get_data(as_text=True),
    )
    assert match is not None
    return match.group(1)


def send_transfer(
    client,
    csrf_token,
    *,
    recipient_username=RECIPIENT_USERNAME,
    amount='10000',
    memo='학습용 송금',
    current_password=SENDER_PASSWORD,
    request_id=None,
    include_csrf=True,
):
    data = {
        'request_id': request_id or transfer_request_id(client),
        'recipient_username': recipient_username,
        'amount': amount,
        'memo': memo,
        'current_password': current_password,
    }
    if include_csrf:
        data['csrf_token'] = csrf_token
    return client.post('/transfers', data=data)


def fetch_balance(user_id):
    connection = sqlite3.connect(market.DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        return market.get_wallet_balance(connection, user_id)
    finally:
        connection.close()


def fetch_transfer_count():
    connection = sqlite3.connect(market.DATABASE)
    try:
        return connection.execute(
            'SELECT COUNT(*) FROM money_transfer'
        ).fetchone()[0]
    finally:
        connection.close()


def test_transfer_page_requires_login_and_lists_only_active_counterparties(
    transfer_database,
):
    unauthenticated = market.app.test_client()
    response = unauthenticated.get('/transfers')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')

    client, _ = authenticated_client()
    page = client.get('/transfers').get_data(as_text=True)
    assert '현재 학습용 잔액: 100000원' in page
    assert f'value="{RECIPIENT_USERNAME}"' in page
    assert f'value="{OUTSIDER_USERNAME}"' in page
    assert f'value="{SENDER_USERNAME}"' not in page
    assert SENDER_PASSWORD not in page

    admin, _ = authenticated_client(ADMIN_ID)
    assert admin.get('/transfers').status_code == 403
    assert 'href="/transfers"' not in admin.get('/products').get_data(
        as_text=True
    )


def test_newly_registered_user_gets_an_empty_wallet(transfer_database):
    client = market.app.test_client()
    client.get('/register')
    with client.session_transaction() as current_session:
        csrf_token = current_session[market.CSRF_SESSION_KEY]
    response = client.post(
        '/register',
        data={
            'csrf_token': csrf_token,
            'username': 'new_wallet_user',
            'password': 'NewWalletPassword123!',
        },
    )
    assert response.status_code == 302

    connection = sqlite3.connect(market.DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        user = connection.execute(
            'SELECT id FROM user WHERE username = ?',
            ('new_wallet_user',),
        ).fetchone()
        assert user is not None
        assert connection.execute(
            'SELECT user_id FROM wallet_account WHERE user_id = ?',
            (user['id'],),
        ).fetchone()['user_id'] == user['id']
        assert market.get_wallet_balance(connection, user['id']) == 0
    finally:
        connection.close()


def test_transfer_is_atomic_and_history_is_private_and_minimal(
    transfer_database,
):
    sender, sender_token = authenticated_client()
    memo = '<script>alert("transfer")</script>'
    response = send_transfer(
        sender,
        sender_token,
        amount='12500',
        memo=memo,
    )
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/transfers')
    assert fetch_balance(SENDER_ID) == 87_500
    assert fetch_balance(RECIPIENT_ID) == 13_500
    assert fetch_transfer_count() == 1

    sender_page = sender.get('/transfers').get_data(as_text=True)
    assert memo not in sender_page
    assert '&lt;script&gt;alert' not in sender_page
    assert '금액: 12500원' in sender_page
    assert '받는 사용자: transfer_recipient' not in sender_page

    recipient, _ = authenticated_client(RECIPIENT_ID)
    recipient_page = recipient.get('/transfers').get_data(as_text=True)
    assert '금액: 12500원' in recipient_page
    assert '보낸 사용자: transfer_sender' not in recipient_page

    outsider, _ = authenticated_client(OUTSIDER_ID)
    outsider_page = outsider.get('/transfers').get_data(as_text=True)
    assert '금액: 12500원' not in outsider_page
    assert memo not in outsider_page


def test_regular_users_can_transfer_in_both_directions(transfer_database):
    sender, sender_token = authenticated_client(SENDER_ID)
    send_transfer(sender, sender_token, amount='10000')

    recipient, recipient_token = authenticated_client(RECIPIENT_ID)
    send_transfer(
        recipient,
        recipient_token,
        recipient_username=SENDER_USERNAME,
        amount='3000',
        current_password=RECIPIENT_PASSWORD,
    )

    assert fetch_balance(SENDER_ID) == 93_000
    assert fetch_balance(RECIPIENT_ID) == 8_000
    assert fetch_transfer_count() == 2


def test_transfer_requires_csrf_and_current_password(transfer_database):
    client, token = authenticated_client()
    response = send_transfer(client, token, include_csrf=False)
    assert response.status_code == 400
    assert fetch_transfer_count() == 0

    response = send_transfer(
        client,
        token,
        current_password='WrongTransferPassword123!',
    )
    assert response.status_code == 302
    assert fetch_transfer_count() == 0
    assert fetch_balance(SENDER_ID) == INITIAL_SENDER_BALANCE


@pytest.mark.parametrize(
    'overrides',
    [
        {'recipient_username': SENDER_USERNAME},
        {'recipient_username': 'missing_user'},
        {'amount': '0'},
        {'amount': '-1'},
        {'amount': '1.5'},
        {'amount': str(market.TRANSFER_MAX_AMOUNT + 1)},
        {'memo': 'a' * (market.TRANSFER_MEMO_MAX_LENGTH + 1)},
        {'memo': '010-1234-5678'},
    ],
)
def test_transfer_rejects_invalid_targets_amounts_and_memos(
    transfer_database,
    overrides,
):
    client, token = authenticated_client()
    response = send_transfer(client, token, **overrides)
    assert response.status_code == 302
    assert fetch_transfer_count() == 0
    assert fetch_balance(SENDER_ID) == INITIAL_SENDER_BALANCE
    assert fetch_balance(RECIPIENT_ID) == INITIAL_RECIPIENT_BALANCE


def test_transfer_rejects_deleted_recipient_and_insufficient_balance(
    transfer_database,
):
    client, token = authenticated_client()
    connection = sqlite3.connect(market.DATABASE)
    try:
        connection.execute(
            'UPDATE user SET deleted_at = 1 WHERE id = ?',
            (RECIPIENT_ID,),
        )
        connection.commit()
    finally:
        connection.close()
    response = send_transfer(client, token)
    assert response.status_code == 302
    assert fetch_transfer_count() == 0

    connection = sqlite3.connect(market.DATABASE)
    try:
        connection.execute(
            'UPDATE user SET deleted_at = NULL WHERE id = ?',
            (RECIPIENT_ID,),
        )
        connection.commit()
    finally:
        connection.close()
    response = send_transfer(
        client,
        token,
        amount=str(INITIAL_SENDER_BALANCE + 1),
    )
    assert response.status_code == 302
    assert fetch_transfer_count() == 0
    assert fetch_balance(SENDER_ID) == INITIAL_SENDER_BALANCE


def test_replayed_request_id_does_not_transfer_twice(transfer_database):
    client, token = authenticated_client()
    request_id = transfer_request_id(client)
    first_response = send_transfer(
        client,
        token,
        request_id=request_id,
    )
    second_response = send_transfer(
        client,
        token,
        request_id=request_id,
    )
    assert first_response.status_code == 302
    assert second_response.status_code == 302
    assert fetch_transfer_count() == 1
    assert fetch_balance(SENDER_ID) == 90_000
    assert fetch_balance(RECIPIENT_ID) == 11_000


def test_transfer_rate_limit_blocks_repeated_actions(
    transfer_database,
    monkeypatch,
):
    monkeypatch.setattr(market, 'TRANSFER_USER_RATE_LIMIT', 1)
    client, token = authenticated_client()
    assert send_transfer(client, token, amount='1').status_code == 302
    response = send_transfer(client, token, amount='1')
    assert response.status_code == 429
    assert fetch_transfer_count() == 1


def test_database_prevents_overdraft_tampering_and_history_changes(
    transfer_database,
):
    connection = sqlite3.connect(market.DATABASE)
    connection.execute('PRAGMA foreign_keys = ON')
    valid_values = (
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        SENDER_ID,
        RECIPIENT_ID,
        1,
        'DB 무결성 테스트',
        SENDER_USERNAME,
        RECIPIENT_USERNAME,
        int(time.time()),
    )
    try:
        with pytest.raises(
            sqlite3.IntegrityError,
            match='insufficient wallet balance',
        ):
            connection.execute(
                '''
                INSERT INTO money_transfer (
                    id,
                    request_id,
                    sender_id,
                    recipient_id,
                    amount,
                    memo,
                    sender_username_snapshot,
                    recipient_username_snapshot,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    valid_values[0],
                    valid_values[1],
                    SENDER_ID,
                    RECIPIENT_ID,
                    INITIAL_SENDER_BALANCE + 1,
                    *valid_values[5:],
                ),
            )
        connection.rollback()

        connection.execute(
            '''
            INSERT INTO money_transfer (
                id,
                request_id,
                sender_id,
                recipient_id,
                amount,
                memo,
                sender_username_snapshot,
                recipient_username_snapshot,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            valid_values,
        )
        connection.commit()
        with pytest.raises(
            sqlite3.IntegrityError,
            match='invalid transfer participant',
        ):
            connection.execute(
                '''
                INSERT INTO money_transfer (
                    id,
                    request_id,
                    sender_id,
                    recipient_id,
                    amount,
                    memo,
                    sender_username_snapshot,
                    recipient_username_snapshot,
                    created_at
                )
                VALUES (?, ?, ?, ?, 1, '', ?, ?, ?)
                ''',
                (
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                    SENDER_ID,
                    RECIPIENT_ID,
                    'forged_sender',
                    RECIPIENT_USERNAME,
                    int(time.time()),
                ),
            )
        connection.rollback()

        connection.execute(
            '''
            INSERT INTO wallet_adjustment (
                id,
                user_id,
                amount,
                source_type,
                created_at
            )
            VALUES (?, ?, ?, 'quickstart_demo_credit', ?)
            ''',
            (
                str(uuid.uuid4()),
                RECIPIENT_ID,
                (
                    market.WALLET_MAX_BALANCE
                    - INITIAL_RECIPIENT_BALANCE
                    - 1
                ),
                int(time.time()),
            ),
        )
        connection.commit()
        with pytest.raises(
            sqlite3.IntegrityError,
            match='wallet balance limit exceeded',
        ):
            connection.execute(
                '''
                INSERT INTO money_transfer (
                    id,
                    request_id,
                    sender_id,
                    recipient_id,
                    amount,
                    memo,
                    sender_username_snapshot,
                    recipient_username_snapshot,
                    created_at
                )
                VALUES (?, ?, ?, ?, 1, '', ?, ?, ?)
                ''',
                (
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                    SENDER_ID,
                    RECIPIENT_ID,
                    SENDER_USERNAME,
                    RECIPIENT_USERNAME,
                    int(time.time()),
                ),
            )
        connection.rollback()

        with pytest.raises(
            sqlite3.IntegrityError,
            match='money transfer is append-only',
        ):
            connection.execute(
                'UPDATE money_transfer SET amount = 2 WHERE id = ?',
                (valid_values[0],),
            )
        connection.rollback()
        with pytest.raises(
            sqlite3.IntegrityError,
            match='money transfer is append-only',
        ):
            connection.execute(
                'DELETE FROM money_transfer WHERE id = ?',
                (valid_values[0],),
            )
        connection.rollback()
        with pytest.raises(
            sqlite3.IntegrityError,
            match='wallet adjustment is append-only',
        ):
            connection.execute(
                'DELETE FROM wallet_adjustment WHERE user_id = ?',
                (SENDER_ID,),
            )
    finally:
        connection.close()


def test_nonzero_wallet_balance_blocks_account_deletion(transfer_database):
    client, token = authenticated_client()
    response = client.post(
        '/profile/delete',
        data={
            'csrf_token': token,
            'current_password': SENDER_PASSWORD,
            'confirmation': market.ACCOUNT_DELETION_CONFIRMATION,
        },
    )
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/profile')
    connection = sqlite3.connect(market.DATABASE)
    try:
        deleted_at = connection.execute(
            'SELECT deleted_at FROM user WHERE id = ?',
            (SENDER_ID,),
        ).fetchone()[0]
        assert deleted_at is None
    finally:
        connection.close()


def test_init_db_backfills_wallets_for_existing_users(tmp_path, monkeypatch):
    database_path = tmp_path / 'legacy-transfer.db'
    monkeypatch.setattr(market, 'DATABASE', str(database_path))
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
            (
                SENDER_ID,
                SENDER_USERNAME,
                market.password_hasher.hash(SENDER_PASSWORD),
            ),
        )
        connection.execute(
            '''
            CREATE TABLE security_rate_limit (
                scope_type TEXT NOT NULL
                    CHECK(
                        scope_type IN (
                            'register_ip',
                            'login_ip',
                            'reauth_user',
                            'reauth_ip',
                            'admin_user',
                            'product_user',
                            'socket_ip'
                        )
                    ),
                scope_key TEXT NOT NULL,
                window_started_at INTEGER NOT NULL,
                attempt_count INTEGER NOT NULL,
                PRIMARY KEY (scope_type, scope_key)
            )
            '''
        )
        connection.execute(
            '''
            INSERT INTO security_rate_limit (
                scope_type,
                scope_key,
                window_started_at,
                attempt_count
            )
            VALUES ('register_ip', 'legacy-key', 1, 2)
            '''
        )
        connection.commit()
    finally:
        connection.close()

    market.init_db()

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        assert connection.execute(
            'SELECT user_id FROM wallet_account WHERE user_id = ?',
            (SENDER_ID,),
        ).fetchone()['user_id'] == SENDER_ID
        assert market.get_wallet_balance(connection, SENDER_ID) == 0
        assert connection.execute(
            '''
            SELECT attempt_count
            FROM security_rate_limit
            WHERE scope_type = 'register_ip' AND scope_key = 'legacy-key'
            '''
        ).fetchone()['attempt_count'] == 2
        connection.execute(
            '''
            INSERT INTO security_rate_limit (
                scope_type,
                scope_key,
                window_started_at,
                attempt_count
            )
            VALUES ('transfer_user', 'new-key', 1, 1)
            '''
        )
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        connection.close()
