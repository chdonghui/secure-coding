import os
import sqlite3
import time

os.environ.setdefault('MARKET_SECRET_KEY', 'pytest-only-market-secret-key-with-more-than-32-characters')
os.environ.setdefault('MARKET_COOKIE_SECURE', 'false')

import app as market


ADMIN_ID = '00000000-0000-0000-0000-000000000901'
USER_ID = '00000000-0000-0000-0000-000000000902'
ADMIN_PASSWORD = 'BusinessAdmin123!'


def test_business_role_blocks_transfers_and_is_a_valid_seller(tmp_path, monkeypatch):
    database_path = tmp_path / 'business.db'
    monkeypatch.setattr(market, 'DATABASE', str(database_path))
    market.app.config.update(
        TESTING=True, SECRET_KEY='pytest-only-app-secret-key-with-more-than-32-characters',
        SESSION_COOKIE_SECURE=False, REQUIRE_HTTPS=False,
    )
    market.init_db()
    connection = sqlite3.connect(database_path)
    connection.execute(
        "INSERT INTO user (id, username, password, is_admin, account_type) VALUES (?, ?, ?, 1, 'user')",
        (ADMIN_ID, 'business_admin', market.password_hasher.hash(ADMIN_PASSWORD)),
    )
    connection.execute(
        "INSERT INTO user (id, username, password, is_admin, account_type) VALUES (?, ?, ?, 0, 'business')",
        (USER_ID, 'business_seller', market.password_hasher.hash('Seller123!')),
    )
    connection.commit(); connection.close()
    client = market.app.test_client()
    now = int(time.time())
    with client.session_transaction() as session:
        session.update(user_id=USER_ID, session_version=0, authenticated_at=now,
                       last_activity=now, csrf_token='business-csrf')
        session[market.CSRF_SESSION_KEY] = 'business-csrf'
    assert client.get('/transfers').status_code == 403
    assert client.get('/orders').status_code == 200
