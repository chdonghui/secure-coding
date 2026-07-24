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


SENDER_ID = '00000000-0000-0000-0000-000000000401'
RECIPIENT_ID = '00000000-0000-0000-0000-000000000402'
OUTSIDER_ID = '00000000-0000-0000-0000-000000000403'
UNKNOWN_ID = '00000000-0000-0000-0000-000000000404'
USERS = (
    (SENDER_ID, 'direct_sender', 'sender-private-bio'),
    (RECIPIENT_ID, 'direct_recipient', 'recipient-private-bio'),
    (OUTSIDER_ID, 'direct_outsider', 'outsider-private-bio'),
)


@pytest.fixture
def direct_chat_database(tmp_path, monkeypatch):
    database_path = tmp_path / 'test-direct-chat.db'
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
    try:
        for user_id, username, bio in USERS:
            connection.execute(
                '''
                INSERT INTO user (id, username, password, bio)
                VALUES (?, ?, ?, ?)
                ''',
                (
                    user_id,
                    username,
                    market.password_hasher.hash('DirectChatPassword123!'),
                    bio,
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return database_path


def authenticated_client(user_id):
    client = market.app.test_client()
    now = int(time.time())
    with client.session_transaction() as current_session:
        current_session['user_id'] = user_id
        current_session['session_version'] = 0
        current_session['authenticated_at'] = now
        current_session['last_activity'] = now
        current_session[market.CSRF_SESSION_KEY] = f'csrf-{user_id}'
    return client


def connect_socket(client, user_id):
    return market.socketio.test_client(
        market.app,
        flask_test_client=client,
        auth={'csrf_token': f'csrf-{user_id}'},
    )


def received_event(socket_client, event_name):
    return [
        event
        for event in socket_client.get_received()
        if event['name'] == event_name
    ]


def event_payload(event):
    arguments = event['args']
    if isinstance(arguments, list):
        return arguments[0]
    return arguments


def fetch_direct_messages():
    connection = sqlite3.connect(market.DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(
            'SELECT * FROM direct_message ORDER BY created_at, id'
        ).fetchall()
    finally:
        connection.close()


def insert_direct_message(
    sender_id,
    recipient_id,
    message,
    created_at,
):
    connection = sqlite3.connect(market.DATABASE)
    connection.execute('PRAGMA foreign_keys = ON')
    try:
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
                str(uuid.uuid4()),
                sender_id,
                recipient_id,
                message,
                created_at,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_direct_chat_pages_require_authentication(direct_chat_database):
    client = market.app.test_client()

    user_list = client.get('/chat')
    conversation = client.get(f'/chat/{RECIPIENT_ID}')

    assert user_list.status_code == 302
    assert user_list.headers['Location'].endswith('/login')
    assert conversation.status_code == 302
    assert conversation.headers['Location'].endswith('/login')


def test_user_list_exposes_only_other_users_public_names(
    direct_chat_database,
):
    client = authenticated_client(SENDER_ID)

    page = client.get('/chat').get_data(as_text=True)

    assert 'direct_recipient' in page
    assert 'direct_outsider' in page
    assert 'direct_sender' not in page
    assert 'private-bio' not in page
    assert '$argon2' not in page
    assert RECIPIENT_ID in page
    assert OUTSIDER_ID in page


@pytest.mark.parametrize(
    'recipient_id',
    [
        'not-a-uuid',
        UNKNOWN_ID,
        SENDER_ID,
    ],
)
def test_invalid_unknown_or_self_conversation_returns_generic_404(
    direct_chat_database,
    recipient_id,
):
    client = authenticated_client(SENDER_ID)

    response = client.get(f'/chat/{recipient_id}')
    page = response.get_data(as_text=True)

    assert response.status_code == 404
    assert 'Traceback' not in page
    assert 'sqlite3' not in page


def test_history_only_contains_messages_between_current_participants(
    direct_chat_database,
):
    xss_message = '<img src=x onerror=alert("direct-history-xss")>'
    insert_direct_message(SENDER_ID, RECIPIENT_ID, xss_message, 1)
    insert_direct_message(RECIPIENT_ID, SENDER_ID, '수신 메시지', 2)
    insert_direct_message(OUTSIDER_ID, SENDER_ID, '외부 사용자 메시지', 3)
    insert_direct_message(RECIPIENT_ID, OUTSIDER_ID, '다른 대화 메시지', 4)
    client = authenticated_client(SENDER_ID)

    page = client.get(f'/chat/{RECIPIENT_ID}').get_data(as_text=True)

    assert xss_message not in page
    assert '&lt;img src=x onerror=alert' in page
    assert '수신 메시지' in page
    assert '외부 사용자 메시지' not in page
    assert '다른 대화 메시지' not in page


def test_history_is_bounded_to_latest_messages(
    direct_chat_database,
    monkeypatch,
):
    monkeypatch.setattr(market, 'DIRECT_CHAT_HISTORY_LIMIT', 2)
    insert_direct_message(SENDER_ID, RECIPIENT_ID, '가장 오래된 메시지', 1)
    insert_direct_message(RECIPIENT_ID, SENDER_ID, '중간 메시지', 2)
    insert_direct_message(SENDER_ID, RECIPIENT_ID, '최신 메시지', 3)
    client = authenticated_client(SENDER_ID)

    page = client.get(f'/chat/{RECIPIENT_ID}').get_data(as_text=True)

    assert '가장 오래된 메시지' not in page
    assert page.index('중간 메시지') < page.index('최신 메시지')


def test_direct_message_is_persisted_and_delivered_only_to_participants(
    direct_chat_database,
):
    sender_http = authenticated_client(SENDER_ID)
    recipient_http = authenticated_client(RECIPIENT_ID)
    outsider_http = authenticated_client(OUTSIDER_ID)
    sender_socket = connect_socket(sender_http, SENDER_ID)
    recipient_socket = connect_socket(recipient_http, RECIPIENT_ID)
    outsider_socket = connect_socket(outsider_http, OUTSIDER_ID)

    acknowledgement = sender_socket.emit(
        'send_direct_message',
        {
            'recipient_id': RECIPIENT_ID,
            'message': '  비공개 메시지！  ',
        },
        callback=True,
    )

    assert acknowledgement['ok'] is True
    sender_events = received_event(sender_socket, 'direct_message')
    recipient_events = received_event(recipient_socket, 'direct_message')
    outsider_events = received_event(outsider_socket, 'direct_message')
    assert len(sender_events) == 1
    assert len(recipient_events) == 1
    assert outsider_events == []

    payload = event_payload(recipient_events[0])
    assert set(payload) == {
        'message_id',
        'sender_id',
        'sender_username',
        'recipient_id',
        'message',
        'sent_at',
    }
    assert payload['message_id'] == acknowledgement['message_id']
    assert payload['sender_id'] == SENDER_ID
    assert payload['sender_username'] == 'direct_sender'
    assert payload['recipient_id'] == RECIPIENT_ID
    assert payload['message'] == '비공개 메시지!'
    assert isinstance(payload['sent_at'], int)

    stored_messages = fetch_direct_messages()
    assert len(stored_messages) == 1
    assert stored_messages[0]['id'] == payload['message_id']
    assert stored_messages[0]['sender_id'] == SENDER_ID
    assert stored_messages[0]['recipient_id'] == RECIPIENT_ID
    assert stored_messages[0]['message'] == '비공개 메시지!'

    sender_socket.disconnect()
    recipient_socket.disconnect()
    outsider_socket.disconnect()


def test_user_can_block_and_unblock_direct_messages(
    direct_chat_database,
):
    sender_http = authenticated_client(SENDER_ID)
    sender_socket = connect_socket(sender_http, SENDER_ID)

    block_response = sender_http.post(
        f'/chat/{RECIPIENT_ID}/block',
        data={'csrf_token': f'csrf-{SENDER_ID}'},
    )
    assert block_response.status_code == 302
    blocked_result = sender_socket.emit(
        'send_direct_message',
        {'recipient_id': RECIPIENT_ID, 'message': '차단 중 전송 시도'},
        callback=True,
    )
    assert blocked_result == {
        'ok': False,
        'error': 'recipient_blocked',
    }
    assert fetch_direct_messages() == []
    assert '차단 상태' in sender_http.get('/chat').get_data(as_text=True)

    unblock_response = sender_http.post(
        f'/chat/{RECIPIENT_ID}/unblock',
        data={'csrf_token': f'csrf-{SENDER_ID}'},
    )
    assert unblock_response.status_code == 302
    allowed_result = sender_socket.emit(
        'send_direct_message',
        {'recipient_id': RECIPIENT_ID, 'message': '차단 해제 후 전송'},
        callback=True,
    )
    assert allowed_result['ok'] is True
    assert len(fetch_direct_messages()) == 1
    sender_socket.disconnect()


@pytest.mark.parametrize(
    'payload',
    [
        None,
        'not-an-object',
        {},
        {'recipient_id': RECIPIENT_ID},
        {'recipient_id': RECIPIENT_ID, 'message': 123},
        {'recipient_id': RECIPIENT_ID, 'message': ''},
        {'recipient_id': RECIPIENT_ID, 'message': '방향\u202e제어'},
        {
            'recipient_id': RECIPIENT_ID,
            'message': '발신자 위조',
            'sender_id': OUTSIDER_ID,
        },
        {
            'recipient_id': RECIPIENT_ID,
            'message': '방 지정 위조',
            'room': market.direct_chat_room(OUTSIDER_ID),
        },
        {'recipient_id': 'invalid-id', 'message': '잘못된 대상'},
        {'recipient_id': SENDER_ID, 'message': '자기 자신에게 전송'},
    ],
)
def test_invalid_or_spoofed_direct_messages_are_rejected(
    direct_chat_database,
    payload,
):
    sender_http = authenticated_client(SENDER_ID)
    sender_socket = connect_socket(sender_http, SENDER_ID)

    acknowledgement = sender_socket.emit(
        'send_direct_message',
        payload,
        callback=True,
    )

    assert acknowledgement == {'ok': False, 'error': 'invalid_message'}
    error = event_payload(
        received_event(sender_socket, 'direct_chat_error')[0]
    )
    assert error['code'] == 'invalid_message'
    assert fetch_direct_messages() == []
    sender_socket.disconnect()


def test_unknown_recipient_is_rejected_without_storage(
    direct_chat_database,
):
    sender_http = authenticated_client(SENDER_ID)
    sender_socket = connect_socket(sender_http, SENDER_ID)

    acknowledgement = sender_socket.emit(
        'send_direct_message',
        {'recipient_id': UNKNOWN_ID, 'message': '존재하지 않는 대상'},
        callback=True,
    )

    assert acknowledgement == {
        'ok': False,
        'error': 'invalid_recipient',
    }
    assert fetch_direct_messages() == []
    sender_socket.disconnect()


def test_direct_message_xss_is_rendered_as_plain_text(
    direct_chat_database,
):
    sender_http = authenticated_client(SENDER_ID)
    sender_socket = connect_socket(sender_http, SENDER_ID)
    xss_message = '<svg onload=alert("direct-live-xss")>'

    acknowledgement = sender_socket.emit(
        'send_direct_message',
        {'recipient_id': RECIPIENT_ID, 'message': xss_message},
        callback=True,
    )

    assert acknowledgement['ok'] is True
    payload = event_payload(
        received_event(sender_socket, 'direct_message')[0]
    )
    assert payload['message'] == xss_message

    page = sender_http.get(f'/chat/{RECIPIENT_ID}').get_data(as_text=True)
    assert xss_message not in page
    assert '&lt;svg onload=alert' in page
    assert 'content.textContent = data.message' in page
    assert 'content.innerHTML' not in page
    sender_socket.disconnect()


def test_global_and_direct_chat_share_rate_limit(
    direct_chat_database,
    monkeypatch,
):
    monkeypatch.setattr(market, 'CHAT_USER_RATE_LIMIT', 1)
    monkeypatch.setattr(market, 'CHAT_IP_RATE_LIMIT', 10)
    sender_http = authenticated_client(SENDER_ID)
    sender_socket = connect_socket(sender_http, SENDER_ID)

    global_result = sender_socket.emit(
        'send_message',
        {'message': '전체 채팅 메시지'},
        callback=True,
    )
    direct_result = sender_socket.emit(
        'send_direct_message',
        {'recipient_id': RECIPIENT_ID, 'message': '우회 시도'},
        callback=True,
    )

    assert global_result['ok'] is True
    assert direct_result == {'ok': False, 'error': 'rate_limited'}
    assert event_payload(
        received_event(sender_socket, 'direct_chat_error')[0]
    )['code'] == 'rate_limited'
    assert fetch_direct_messages() == []
    sender_socket.disconnect()


def test_duplicate_direct_message_is_rejected(
    direct_chat_database,
):
    sender_http = authenticated_client(SENDER_ID)
    sender_socket = connect_socket(sender_http, SENDER_ID)
    payload = {
        'recipient_id': RECIPIENT_ID,
        'message': '반복되는 비공개 메시지',
    }

    first = sender_socket.emit(
        'send_direct_message',
        payload,
        callback=True,
    )
    duplicate = sender_socket.emit(
        'send_direct_message',
        payload,
        callback=True,
    )

    assert first['ok'] is True
    assert duplicate == {'ok': False, 'error': 'duplicate_message'}
    assert len(fetch_direct_messages()) == 1
    sender_socket.disconnect()


def test_direct_event_rechecks_session_expiration(
    direct_chat_database,
    monkeypatch,
):
    sender_http = authenticated_client(SENDER_ID)
    sender_socket = connect_socket(sender_http, SENDER_ID)
    future = int(time.time()) + market.SESSION_IDLE_SECONDS + 1
    monkeypatch.setattr(market.time, 'time', lambda: future)

    acknowledgement = sender_socket.emit(
        'send_direct_message',
        {'recipient_id': RECIPIENT_ID, 'message': '만료 후 전송'},
        callback=True,
    )

    assert acknowledgement == {
        'ok': False,
        'error': 'authentication_required',
    }
    assert not sender_socket.is_connected()
    assert fetch_direct_messages() == []


def test_direct_message_database_constraints_and_indexes(
    direct_chat_database,
):
    connection = sqlite3.connect(market.DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        columns = {
            row['name']
            for row in connection.execute(
                'PRAGMA table_info(direct_message)'
            ).fetchall()
        }
        foreign_keys = {
            (row['from'], row['table'])
            for row in connection.execute(
                'PRAGMA foreign_key_list(direct_message)'
            ).fetchall()
        }
        indexes = {
            row['name']
            for row in connection.execute(
                'PRAGMA index_list(direct_message)'
            ).fetchall()
        }
        assert {
            'id',
            'sender_id',
            'recipient_id',
            'message',
            'created_at',
        } <= columns
        assert {
            ('sender_id', 'user'),
            ('recipient_id', 'user'),
        } <= foreign_keys
        assert 'direct_message_sender_recipient_created' in indexes
        assert 'direct_message_recipient_sender_created' in indexes

        invalid_rows = [
            (SENDER_ID, SENDER_ID, '자기 자신', 1),
            (SENDER_ID, UNKNOWN_ID, '없는 사용자', 1),
            (SENDER_ID, RECIPIENT_ID, '', 1),
            (
                SENDER_ID,
                RECIPIENT_ID,
                'a' * (market.CHAT_MESSAGE_MAX_LENGTH + 1),
                1,
            ),
            (SENDER_ID, RECIPIENT_ID, 'NUL\x00포함', 1),
            (SENDER_ID, RECIPIENT_ID, '시간 오류', -1),
        ]
        for sender_id, recipient_id, message, created_at in invalid_rows:
            with pytest.raises(sqlite3.IntegrityError):
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
                        str(uuid.uuid4()),
                        sender_id,
                        recipient_id,
                        message,
                        created_at,
                    ),
                )
            connection.rollback()
    finally:
        connection.close()


def test_incompatible_existing_direct_message_schema_stops_migration(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / 'incompatible-direct-chat.db'
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
            CREATE TABLE direct_message (
                id TEXT PRIMARY KEY,
                sender_id TEXT,
                recipient_id TEXT,
                message TEXT
            )
            '''
        )
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(market, 'DATABASE', str(database_path))

    with pytest.raises(RuntimeError, match='1대1 채팅 스키마'):
        market.init_db()
