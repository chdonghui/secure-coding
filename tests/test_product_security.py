import os
import sqlite3
import uuid

import pytest


os.environ.setdefault(
    'MARKET_SECRET_KEY',
    'pytest-only-market-secret-key-with-more-than-32-characters',
)
os.environ.setdefault('MARKET_COOKIE_SECURE', 'false')

import app as market


OWNER_USERNAME = 'product_owner'
OTHER_USERNAME = 'other_user'
VALID_PASSWORD = 'StrongPassword123!'


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
    with market.app.test_client() as test_client:
        yield test_client


def get_csrf_token(client, path):
    response = client.get(path)
    assert response.status_code == 200
    with client.session_transaction() as current_session:
        return current_session[market.CSRF_SESSION_KEY]


def register_user(client, username):
    token = get_csrf_token(client, '/register')
    response = client.post(
        '/register',
        data={
            'csrf_token': token,
            'username': username,
            'password': VALID_PASSWORD,
        },
    )
    assert response.status_code == 302


def login_user(client, username):
    token = get_csrf_token(client, '/login')
    response = client.post(
        '/login',
        data={
            'csrf_token': token,
            'username': username,
            'password': VALID_PASSWORD,
        },
    )
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/dashboard')


def logout_user(client):
    token = get_csrf_token(client, '/dashboard')
    response = client.post('/logout', data={'csrf_token': token})
    assert response.status_code == 302


def fetch_products():
    connection = sqlite3.connect(market.DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute('SELECT * FROM product ORDER BY id').fetchall()
    finally:
        connection.close()


def create_product(
    client,
    title='안전한 상품',
    description='상품 설명',
    price='10000',
):
    token = get_csrf_token(client, '/product/new')
    return client.post(
        '/product/new',
        data={
            'csrf_token': token,
            'title': title,
            'description': description,
            'price': price,
        },
    )


def setup_owner(client):
    register_user(client, OWNER_USERNAME)
    login_user(client, OWNER_USERNAME)


def test_product_management_requires_authenticated_user(client):
    response = client.get('/products/manage')

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')


def test_product_management_only_shows_current_users_products(client):
    setup_owner(client)
    owner_title = '<script>alert("owner-product")</script>'
    create_product(client, title=owner_title)
    owner_product = fetch_products()[0]

    logout_user(client)
    register_user(client, OTHER_USERNAME)
    login_user(client, OTHER_USERNAME)
    create_product(client, title='다른 사용자 상품')
    other_product = next(
        product
        for product in fetch_products()
        if product['seller_id'] != owner_product['seller_id']
    )

    page = client.get('/products/manage').get_data(as_text=True)

    assert '다른 사용자 상품' in page
    assert owner_title not in page
    assert 'owner-product' not in page
    assert owner_product['id'] not in page
    assert other_product['id'] in page
    assert f'/product/{other_product["id"]}/edit' in page
    assert f'/product/{other_product["id"]}/delete' in page
    assert 'name="csrf_token"' in page


def test_product_registration_requires_authenticated_user(client):
    assert client.get('/product/new').headers['Location'].endswith('/login')
    response = client.post(
        '/product/new',
        data={
            'title': '비로그인 상품',
            'description': '등록되면 안 됨',
            'price': '1000',
        },
    )
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
    assert fetch_products() == []


def test_product_catalog_is_public_but_management_requires_login(client):
    setup_owner(client)
    create_product(client)
    product = fetch_products()[0]
    logout_user(client)

    landing = client.get('/')
    catalog_response = client.get('/products')
    catalog = catalog_response.get_data(as_text=True)
    detail = client.get(f'/product/{product["id"]}').get_data(as_text=True)

    assert landing.status_code == 302
    assert landing.headers['Location'].endswith('/products')
    assert catalog_response.status_code == 200
    assert product['title'] in catalog
    assert product['id'] in catalog
    assert OWNER_USERNAME in catalog
    assert '/product/new' not in catalog
    assert '/products/manage' not in catalog
    assert '/chat' not in catalog
    assert product['id'] in detail
    assert client.get('/product/new').headers['Location'].endswith('/login')
    assert client.get('/products/manage').headers['Location'].endswith('/login')
    assert client.get('/chat').headers['Location'].endswith('/login')


def test_product_catalog_search_filters_title_and_description(client):
    setup_owner(client)
    create_product(
        client,
        title='사과 한 상자',
        description='신선한 과일 상품',
    )
    create_product(
        client,
        title='겨울 코트',
        description='따뜻한 의류 상품',
    )

    response = client.get('/products?q=사과')
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert '사과 한 상자' in page
    assert '겨울 코트' not in page

    response = client.get('/products?q=과일')
    assert '사과 한 상자' in response.get_data(as_text=True)

    response = client.get('/products?q=%25')
    page = response.get_data(as_text=True)
    assert '사과 한 상자' not in page
    assert '겨울 코트' not in page


def test_product_state_changes_require_csrf(client):
    setup_owner(client)

    response = client.post(
        '/product/new',
        data={'title': '상품', 'description': '설명', 'price': '1000'},
    )
    assert response.status_code == 400

    create_product(client)
    product_id = fetch_products()[0]['id']
    response = client.post(
        f'/product/{product_id}/edit',
        data={'title': '수정', 'description': '설명', 'price': '2000'},
    )
    assert response.status_code == 400
    assert client.post(f'/product/{product_id}/delete').status_code == 400


def test_valid_product_is_normalized_and_stored_as_integer(client):
    setup_owner(client)
    response = create_product(
        client,
        title='  Ａ급 상품  ',
        description='  설명입니다.  ',
        price='001000',
    )

    assert response.status_code == 302
    product = fetch_products()[0]
    assert product['title'] == 'A급 상품'
    assert product['description'] == '설명입니다.'
    assert product['price'] == 1000

    connection = sqlite3.connect(market.DATABASE)
    try:
        stored_type = connection.execute(
            'SELECT typeof(price) FROM product WHERE id = ?',
            (product['id'],),
        ).fetchone()[0]
    finally:
        connection.close()
    assert stored_type == 'integer'
    assert response.headers['Location'].endswith(f'/product/{product["id"]}')


@pytest.mark.parametrize(
    ('title', 'description', 'price'),
    [
        ('', '설명', '1000'),
        ('   ', '설명', '1000'),
        ('a' * (market.PRODUCT_TITLE_MAX_LENGTH + 1), '설명', '1000'),
        ('제목\x00', '설명', '1000'),
        ('제목\n변조', '설명', '1000'),
        ('제목', '', '1000'),
        ('제목', '   ', '1000'),
        ('제목', 'a' * (market.PRODUCT_DESCRIPTION_MAX_LENGTH + 1), '1000'),
        ('제목', '설명\x00', '1000'),
        ('제목', '방향\u202e제어', '1000'),
        ('제목', '설명', ''),
        ('제목', '설명', '-1'),
        ('제목', '설명', '1.5'),
        ('제목', '설명', '1e3'),
        ('제목', '설명', '１２３'),
        ('제목', '설명', '0' * 11),
        ('제목', '설명', str(market.PRODUCT_MAX_PRICE + 1)),
    ],
)
def test_product_registration_rejects_invalid_input(
    client,
    title,
    description,
    price,
):
    setup_owner(client)
    response = create_product(client, title, description, price)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/product/new')
    assert fetch_products() == []


def test_product_output_escapes_script_markup(client):
    setup_owner(client)
    xss_title = '<script>alert("title-xss")</script>'
    xss_description = '<img src=x onerror=alert("description-xss")>'
    create_product(client, xss_title, xss_description)
    product = fetch_products()[0]

    dashboard = client.get('/dashboard').get_data(as_text=True)
    catalog = client.get('/products').get_data(as_text=True)
    management = client.get('/products/manage').get_data(as_text=True)
    detail = client.get(f'/product/{product["id"]}').get_data(as_text=True)
    edit = client.get(f'/product/{product["id"]}/edit').get_data(as_text=True)
    assert xss_title not in dashboard
    assert xss_title not in catalog
    assert xss_title not in management
    assert xss_title not in detail
    assert xss_title not in edit
    assert xss_description not in management
    assert xss_description not in detail
    assert xss_description not in edit
    assert '&lt;script&gt;alert' in dashboard
    assert '&lt;script&gt;alert' in catalog
    assert '&lt;script&gt;alert' in management
    assert '&lt;script&gt;alert' in detail
    assert '&lt;script&gt;alert' in edit
    assert '&lt;img src=x onerror=alert' in management
    assert '&lt;img src=x onerror=alert' in detail
    assert '&lt;img src=x onerror=alert' in edit


def test_product_creation_is_rate_limited_and_catalog_is_paginated(
    client,
    monkeypatch,
):
    setup_owner(client)
    monkeypatch.setattr(market, 'PRODUCT_CREATE_RATE_LIMIT', 2)
    assert create_product(client, title='제한 상품 1').status_code == 302
    assert create_product(client, title='제한 상품 2').status_code == 302
    assert create_product(client, title='제한 상품 3').status_code == 429

    connection = sqlite3.connect(market.DATABASE)
    try:
        owner_id = connection.execute(
            'SELECT id FROM user WHERE username = ?',
            (OWNER_USERNAME,),
        ).fetchone()[0]
        for number in range(market.PAGE_SIZE):
            connection.execute(
                '''
                INSERT INTO product (
                    id,
                    title,
                    description,
                    price,
                    seller_id
                )
                VALUES (?, ?, '페이지 검증 상품', 1000, ?)
                ''',
                (
                    str(uuid.uuid4()),
                    f'추가 상품 {number:02d}',
                    owner_id,
                ),
            )
        connection.commit()
    finally:
        connection.close()

    first_page = client.get('/products').get_data(as_text=True)
    second_page = client.get('/products?page=2').get_data(as_text=True)
    assert '다음' in first_page
    assert '이전' in second_page
    assert client.get('/products?page=0').status_code == 400
    assert client.get('/products?page=9999').status_code == 404


def test_owner_can_edit_and_delete_product(client):
    setup_owner(client)
    create_product(client)
    product_id = fetch_products()[0]['id']

    token = get_csrf_token(client, f'/product/{product_id}/edit')
    response = client.post(
        f'/product/{product_id}/edit',
        data={
            'csrf_token': token,
            'title': '수정된 상품',
            'description': '수정된 설명',
            'price': '25000',
        },
    )
    assert response.status_code == 302
    product = fetch_products()[0]
    assert product['title'] == '수정된 상품'
    assert product['price'] == 25000

    token = get_csrf_token(client, f'/product/{product_id}')
    response = client.post(
        f'/product/{product_id}/delete',
        data={'csrf_token': token},
    )
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/products/manage')
    assert fetch_products() == []


def test_non_owner_cannot_edit_or_delete_product(client):
    setup_owner(client)
    create_product(client)
    product = fetch_products()[0]
    logout_user(client)
    register_user(client, OTHER_USERNAME)
    login_user(client, OTHER_USERNAME)

    assert client.get(f'/product/{product["id"]}/edit').status_code == 403
    token = get_csrf_token(client, '/dashboard')
    response = client.post(
        f'/product/{product["id"]}/edit',
        data={
            'csrf_token': token,
            'title': '탈취된 상품',
            'description': '권한 우회',
            'price': '1',
        },
    )
    assert response.status_code == 403
    response = client.post(
        f'/product/{product["id"]}/delete',
        data={'csrf_token': token},
    )
    assert response.status_code == 403

    unchanged_product = fetch_products()[0]
    assert unchanged_product['title'] == product['title']
    assert unchanged_product['seller_id'] == product['seller_id']


def test_product_database_constraints_reject_invalid_rows(client):
    setup_owner(client)
    connection = sqlite3.connect(market.DATABASE)
    connection.execute('PRAGMA foreign_keys = ON')
    owner_id = connection.execute(
        'SELECT id FROM user WHERE username = ?',
        (OWNER_USERNAME,),
    ).fetchone()[0]

    invalid_rows = [
        (str(uuid.uuid4()), '   ', '설명', 1000, owner_id),
        (str(uuid.uuid4()), '제목', '   ', 1000, owner_id),
        (str(uuid.uuid4()), '제목', '설명', -1, owner_id),
        (str(uuid.uuid4()), '제목', '설명', market.PRODUCT_MAX_PRICE + 1, owner_id),
        (str(uuid.uuid4()), '제목', '설명', '가격', owner_id),
        (str(uuid.uuid4()), '제목', '설명', 1000, str(uuid.uuid4())),
    ]
    try:
        for row in invalid_rows:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    '''
                    INSERT INTO product (id, title, description, price, seller_id)
                    VALUES (?, ?, ?, ?, ?)
                    ''',
                    row,
                )
            connection.rollback()
    finally:
        connection.close()
    assert fetch_products() == []


def test_legacy_product_schema_is_migrated(tmp_path, monkeypatch):
    database_path = tmp_path / 'legacy-product.db'
    seller_id = str(uuid.uuid4())
    product_id = str(uuid.uuid4())
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
            'INSERT INTO user (id, username, password) VALUES (?, ?, ?)',
            (seller_id, OWNER_USERNAME, VALID_PASSWORD),
        )
        connection.execute(
            '''
            INSERT INTO product (id, title, description, price, seller_id)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (product_id, '  기존 상품  ', '  기존 설명  ', '12000', seller_id),
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
        product = connection.execute(
            'SELECT *, typeof(price) AS price_type FROM product WHERE id = ?',
            (product_id,),
        ).fetchone()
        product_columns = {
            row['name']: row['type']
            for row in connection.execute('PRAGMA table_info(product)').fetchall()
        }
        foreign_keys = connection.execute(
            'PRAGMA foreign_key_list(product)'
        ).fetchall()
        integrity_issues = connection.execute('PRAGMA foreign_key_check').fetchall()
    finally:
        connection.close()

    assert product['title'] == '기존 상품'
    assert product['description'] == '기존 설명'
    assert product['price'] == 12000
    assert product['price_type'] == 'integer'
    assert product_columns['price'].upper() == 'INTEGER'
    assert any(row['from'] == 'seller_id' and row['table'] == 'user' for row in foreign_keys)
    assert integrity_issues == []


@pytest.mark.parametrize(
    'product_id',
    [
        'not-a-uuid',
        str(uuid.uuid4()).upper(),
        str(uuid.uuid4()),
    ],
)
def test_invalid_or_unknown_product_identifier_returns_generic_404(
    client,
    product_id,
):
    response = client.get(f'/product/{product_id}')
    page = response.get_data(as_text=True)
    assert response.status_code == 404
    assert 'Traceback' not in page
    assert 'sqlite3' not in page
