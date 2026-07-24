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


USER_ID = '00000000-0000-0000-0000-000000000301'
USERNAME = 'chat_user'


@pytest.fixture
def flask_client(tmp_path, monkeypatch):
    database_path = tmp_path / 'test-chat.db'
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
        connection.execute(
            '''
            INSERT INTO user (
                id,
                username,
                password,
                bio,
                failed_login_attempts,
                locked_until
            )
            VALUES (?, ?, ?, NULL, 0, NULL)
            ''',
            (
                USER_ID,
                USERNAME,
                market.password_hasher.hash('ChatPassword123!'),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    with market.app.test_client() as client:
        yield client


def authenticate_http_client(client):
    now = int(time.time())
    with client.session_transaction() as current_session:
        current_session['user_id'] = USER_ID
        current_session['authenticated_at'] = now
        current_session['last_activity'] = now
        current_session[market.CSRF_SESSION_KEY] = 'chat-csrf-token'


def connect_socket(client, csrf_token='chat-csrf-token'):
    return market.socketio.test_client(
        market.app,
        flask_test_client=client,
        auth={'csrf_token': csrf_token},
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


def test_socket_connection_requires_authenticated_session_and_csrf(
    flask_client,
):
    unauthenticated = connect_socket(flask_client)
    assert not unauthenticated.is_connected()

    authenticate_http_client(flask_client)
    wrong_csrf = connect_socket(flask_client, 'wrong-token')
    assert not wrong_csrf.is_connected()

    authenticated = connect_socket(flask_client)
    assert authenticated.is_connected()
    authenticated.disconnect()


def test_server_validates_message_and_generates_sender_metadata(flask_client):
    authenticate_http_client(flask_client)
    socket_client = connect_socket(flask_client)

    acknowledgement = socket_client.emit(
        'send_message',
        {'message': '  안녕하세요！  '},
        callback=True,
    )
    assert acknowledgement['ok'] is True

    messages = received_event(socket_client, 'message')
    assert len(messages) == 1
    payload = event_payload(messages[0])
    assert set(payload) == {
        'message_id',
        'username',
        'message',
        'sent_at',
    }
    assert str(uuid.UUID(payload['message_id'])) == payload['message_id']
    assert payload['username'] == USERNAME
    assert payload['message'] == '안녕하세요!'
    assert isinstance(payload['sent_at'], int)
    socket_client.disconnect()


@pytest.mark.parametrize(
    'payload',
    [
        None,
        'not-an-object',
        {},
        {'message': 123},
        {'message': ''},
        {'message': '   '},
        {'message': '정상 메시지', 'username': 'spoofed-user'},
        {'message': 'a' * 501},
        {'message': '제어문자\x00포함'},
        {'message': '방향제어\u202e포함'},
    ],
)
def test_invalid_or_spoofed_messages_are_not_broadcast(
    flask_client,
    payload,
):
    authenticate_http_client(flask_client)
    socket_client = connect_socket(flask_client)

    acknowledgement = socket_client.emit(
        'send_message',
        payload,
        callback=True,
    )
    assert acknowledgement == {
        'ok': False,
        'error': 'invalid_message',
    }
    events = socket_client.get_received()
    assert [
        event
        for event in events
        if event['name'] == 'message'
    ] == []
    errors = [
        event
        for event in events
        if event['name'] == 'chat_error'
    ]
    assert event_payload(errors[0])['code'] == 'invalid_message'
    socket_client.disconnect()


def test_xss_message_is_only_sent_as_plain_text(flask_client):
    authenticate_http_client(flask_client)
    socket_client = connect_socket(flask_client)
    xss_message = '<img src=x onerror=alert("chat-xss")>'

    acknowledgement = socket_client.emit(
        'send_message',
        {'message': xss_message},
        callback=True,
    )
    assert acknowledgement['ok'] is True
    payload = event_payload(received_event(socket_client, 'message')[0])
    assert payload['message'] == xss_message

    dashboard = flask_client.get('/dashboard').get_data(as_text=True)
    assert 'item.textContent' in dashboard
    assert 'item.innerHTML' not in dashboard
    socket_client.disconnect()


def test_user_message_rate_limit_blocks_excess_events(
    flask_client,
    monkeypatch,
):
    monkeypatch.setattr(market, 'CHAT_USER_RATE_LIMIT', 2)
    monkeypatch.setattr(market, 'CHAT_IP_RATE_LIMIT', 10)
    authenticate_http_client(flask_client)
    socket_client = connect_socket(flask_client)

    for index in range(2):
        acknowledgement = socket_client.emit(
            'send_message',
            {'message': f'메시지 {index}'},
            callback=True,
        )
        assert acknowledgement['ok'] is True

    blocked = socket_client.emit(
        'send_message',
        {'message': '차단되는 메시지'},
        callback=True,
    )
    assert blocked == {'ok': False, 'error': 'rate_limited'}
    assert event_payload(
        received_event(socket_client, 'chat_error')[0]
    )['code'] == 'rate_limited'
    socket_client.disconnect()


def test_ip_message_rate_limit_blocks_excess_events(
    flask_client,
    monkeypatch,
):
    monkeypatch.setattr(market, 'CHAT_USER_RATE_LIMIT', 10)
    monkeypatch.setattr(market, 'CHAT_IP_RATE_LIMIT', 1)
    authenticate_http_client(flask_client)
    socket_client = connect_socket(flask_client)

    first = socket_client.emit(
        'send_message',
        {'message': '첫 번째 메시지'},
        callback=True,
    )
    second = socket_client.emit(
        'send_message',
        {'message': '두 번째 메시지'},
        callback=True,
    )
    assert first['ok'] is True
    assert second == {'ok': False, 'error': 'rate_limited'}
    socket_client.disconnect()


def test_duplicate_message_is_rejected(flask_client):
    authenticate_http_client(flask_client)
    socket_client = connect_socket(flask_client)

    first = socket_client.emit(
        'send_message',
        {'message': '반복 메시지'},
        callback=True,
    )
    duplicate = socket_client.emit(
        'send_message',
        {'message': '반복 메시지'},
        callback=True,
    )
    assert first['ok'] is True
    assert duplicate == {'ok': False, 'error': 'duplicate_message'}
    socket_client.disconnect()


def test_message_event_rechecks_session_expiration(
    flask_client,
    monkeypatch,
):
    authenticate_http_client(flask_client)
    socket_client = connect_socket(flask_client)
    future = int(time.time()) + market.SESSION_IDLE_SECONDS + 1
    monkeypatch.setattr(market.time, 'time', lambda: future)

    acknowledgement = socket_client.emit(
        'send_message',
        {'message': '만료 후 메시지'},
        callback=True,
    )
    assert acknowledgement == {
        'ok': False,
        'error': 'authentication_required',
    }
    assert not socket_client.is_connected()


def test_message_event_rechecks_that_user_still_exists(flask_client):
    authenticate_http_client(flask_client)
    socket_client = connect_socket(flask_client)
    connection = sqlite3.connect(market.DATABASE)
    try:
        connection.execute('DELETE FROM user WHERE id = ?', (USER_ID,))
        connection.commit()
    finally:
        connection.close()

    acknowledgement = socket_client.emit(
        'send_message',
        {'message': '삭제된 사용자 메시지'},
        callback=True,
    )
    assert acknowledgement == {
        'ok': False,
        'error': 'authentication_required',
    }
    assert not socket_client.is_connected()


def test_socket_origin_and_payload_size_are_restricted(flask_client):
    response = flask_client.get(
        '/socket.io/?EIO=4&transport=polling',
        headers={
            'Origin': 'https://attacker.example',
            'X-Forwarded-Host': 'attacker.example',
        },
    )
    assert response.status_code == 400
    assert (
        market.socketio.server.eio.max_http_buffer_size
        == market.CHAT_MAX_PAYLOAD_BYTES
    )


def test_https_can_be_required_for_http_and_socket_handshakes(
    flask_client,
    monkeypatch,
):
    monkeypatch.setitem(market.app.config, 'REQUIRE_HTTPS', True)
    insecure_response = flask_client.get('/login')
    assert insecure_response.status_code == 400
    forged_proxy_response = flask_client.get(
        '/login',
        headers={'X-Forwarded-Proto': 'https'},
    )
    assert forged_proxy_response.status_code == 400
    insecure_socket_response = flask_client.get(
        '/socket.io/?EIO=4&transport=polling',
    )
    assert insecure_socket_response.status_code == 400

    secure_response = flask_client.get(
        '/login',
        base_url='https://localhost',
    )
    assert secure_response.status_code == 200
