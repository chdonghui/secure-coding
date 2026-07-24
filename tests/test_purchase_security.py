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


BUYER_ID = '00000000-0000-0000-0000-000000000801'
SELLER_ID = '00000000-0000-0000-0000-000000000802'
ADMIN_ID = '00000000-0000-0000-0000-000000000803'
PRODUCT_ID = '00000000-0000-0000-0000-000000000804'
EXPENSIVE_PRODUCT_ID = '00000000-0000-0000-0000-000000000805'
BUYER_USERNAME = 'purchase_buyer'
SELLER_USERNAME = 'purchase_seller'
ADMIN_USERNAME = 'purchase_admin'
BUYER_PASSWORD = 'PurchaseBuyer123!'
SELLER_PASSWORD = 'PurchaseSeller123!'
PRODUCT_PRICE = 15_000


@pytest.fixture
def purchase_database(tmp_path, monkeypatch):
    database_path = tmp_path / 'test-purchase.db'
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
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        users = (
            (BUYER_ID, BUYER_USERNAME, BUYER_PASSWORD, 0),
            (SELLER_ID, SELLER_USERNAME, SELLER_PASSWORD, 0),
            (ADMIN_ID, ADMIN_USERNAME, 'PurchaseAdmin123!', 1),
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
            "UPDATE user SET account_type = 'business' WHERE id = ?",
            (SELLER_ID,),
        )
        now = int(time.time())
        connection.executemany(
            '''
            INSERT INTO wallet_adjustment (
                id, user_id, amount, source_type, created_at
            )
            VALUES (?, ?, ?, 'quickstart_demo_credit', ?)
            ''',
            (
                (str(uuid.uuid4()), BUYER_ID, 100_000, now),
                (str(uuid.uuid4()), SELLER_ID, 1_000, now),
            ),
        )
        connection.execute(
            '''
            INSERT INTO product (id, title, description, price, seller_id)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (
                PRODUCT_ID,
                '사과 한 상자',
                '구매 테스트용 상품입니다.',
                PRODUCT_PRICE,
                SELLER_ID,
            ),
        )
        connection.execute(
            '''
            INSERT INTO product (id, title, description, price, seller_id)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (
                EXPENSIVE_PRODUCT_ID,
                '고가 상품',
                '잔액 부족 테스트용 상품입니다.',
                1_000_000,
                SELLER_ID,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return database_path


def authenticated_client(user_id=BUYER_ID):
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


def purchase_request(client, token, product_id=PRODUCT_ID, **overrides):
    data = {
        'csrf_token': token,
        'current_password': BUYER_PASSWORD,
    }
    data.update(overrides)
    return client.post(
        f'/product/{product_id}/purchase',
        data=data,
    )


def balance(user_id):
    connection = sqlite3.connect(market.DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        return market.get_wallet_balance(connection, user_id)
    finally:
        connection.close()


def count_rows(table_name):
    connection = sqlite3.connect(market.DATABASE)
    try:
        return connection.execute(
            f'SELECT COUNT(*) FROM {table_name}'
        ).fetchone()[0]
    finally:
        connection.close()


def test_purchase_requires_authentication_and_admin_is_blocked(
    purchase_database,
):
    anonymous = market.app.test_client()
    response = anonymous.post(
        f'/product/{PRODUCT_ID}/purchase',
        data={'current_password': BUYER_PASSWORD},
    )
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')

    admin, token = authenticated_client(ADMIN_ID)
    assert admin.get('/orders').status_code == 403
    assert admin.post(
        f'/product/{PRODUCT_ID}/purchase',
        data={'csrf_token': token, 'current_password': 'PurchaseAdmin123!'},
    ).status_code == 403


def test_purchase_moves_wallets_once_and_creates_private_order(
    purchase_database,
):
    buyer, token = authenticated_client()
    product_page = buyer.get(f'/product/{PRODUCT_ID}')
    assert product_page.status_code == 200
    assert '학습용 잔액으로 구매' in product_page.get_data(as_text=True)

    response = purchase_request(buyer, token)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/orders')
    assert balance(BUYER_ID) == 85_000
    assert balance(SELLER_ID) == 16_000
    assert count_rows('purchase_order') == 1
    assert count_rows('money_transfer') == 1

    sold_page = buyer.get(f'/product/{PRODUCT_ID}').get_data(as_text=True)
    assert '판매 완료' in sold_page
    assert '학습용 잔액으로 구매' not in sold_page
    public_products = market.app.test_client().get('/products')
    assert '사과 한 상자' not in public_products.get_data(as_text=True)

    buyer_orders = buyer.get('/orders').get_data(as_text=True)
    assert '구매' in buyer_orders
    assert '사과 한 상자' in buyer_orders
    seller, _ = authenticated_client(SELLER_ID)
    seller_orders = seller.get('/orders').get_data(as_text=True)
    assert '판매' in seller_orders
    assert BUYER_USERNAME in seller_orders
    edit_response = seller.get(f'/product/{PRODUCT_ID}/edit')
    assert edit_response.status_code == 302
    assert edit_response.headers['Location'].endswith(
        f'/product/{PRODUCT_ID}'
    )


def test_purchase_rejects_wrong_password_insufficient_balance_and_replay(
    purchase_database,
):
    buyer, token = authenticated_client()
    response = purchase_request(
        buyer,
        token,
        current_password='WrongPurchasePassword123!',
    )
    assert response.status_code == 302
    assert count_rows('purchase_order') == 0

    response = purchase_request(
        buyer,
        token,
        product_id=EXPENSIVE_PRODUCT_ID,
    )
    assert response.status_code == 302
    assert count_rows('purchase_order') == 0
    assert count_rows('money_transfer') == 0

    assert purchase_request(buyer, token).status_code == 302
    assert purchase_request(buyer, token).status_code == 302
    assert count_rows('purchase_order') == 1
    assert count_rows('money_transfer') == 1


def test_purchase_order_is_append_only_and_database_validates_payment(
    purchase_database,
):
    buyer, token = authenticated_client()
    assert purchase_request(buyer, token).status_code == 302
    connection = sqlite3.connect(market.DATABASE)
    try:
        with pytest.raises(
            sqlite3.IntegrityError,
            match='purchase order is append-only',
        ):
            connection.execute(
                'UPDATE purchase_order SET amount = 1 WHERE product_id = ?',
                (PRODUCT_ID,),
            )
        connection.rollback()
        with pytest.raises(
            sqlite3.IntegrityError,
            match='purchase order is append-only',
        ):
            connection.execute(
                'DELETE FROM purchase_order WHERE product_id = ?',
                (PRODUCT_ID,),
            )
    finally:
        connection.close()
