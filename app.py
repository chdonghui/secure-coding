import hmac
import os
import re
import secrets
import sqlite3
import time
import unicodedata
import uuid
from datetime import timedelta
from functools import wraps

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from flask_socketio import SocketIO, send


USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 30
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
BIO_MAX_LENGTH = 500
PRODUCT_TITLE_MIN_LENGTH = 1
PRODUCT_TITLE_MAX_LENGTH = 100
PRODUCT_DESCRIPTION_MIN_LENGTH = 1
PRODUCT_DESCRIPTION_MAX_LENGTH = 2000
PRODUCT_MIN_PRICE = 0
PRODUCT_MAX_PRICE = 1_000_000_000
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 15 * 60
SESSION_IDLE_SECONDS = 30 * 60
SESSION_ABSOLUTE_SECONDS = 8 * 60 * 60
CSRF_SESSION_KEY = '_csrf_token'


def get_required_secret_key():
    secret_key = os.environ.get('MARKET_SECRET_KEY', '')
    if len(secret_key) < 32:
        raise RuntimeError(
            'MARKET_SECRET_KEY 환경변수에 32자 이상의 무작위 비밀키를 설정해야 합니다.'
        )
    return secret_key


def get_boolean_env(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    normalized_value = value.strip().lower()
    if normalized_value in {'1', 'true', 'yes', 'on'}:
        return True
    if normalized_value in {'0', 'false', 'no', 'off'}:
        return False
    raise RuntimeError(f'{name} 환경변수는 true 또는 false로 설정해야 합니다.')


app = Flask(__name__)
app.config.update(
    SECRET_KEY=get_required_secret_key(),
    DEBUG=get_boolean_env('MARKET_DEBUG', False),
    MAX_CONTENT_LENGTH=1024 * 1024,
    PERMANENT_SESSION_LIFETIME=timedelta(seconds=SESSION_IDLE_SECONDS),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=get_boolean_env('MARKET_COOKIE_SECURE', True),
)
DATABASE = 'market.db'
socketio = SocketIO(app)
password_hasher = PasswordHasher()
DUMMY_PASSWORD_HASH = password_hasher.hash(
    'This password is used only to equalize failed-login verification time.'
)


# 데이터베이스 연결 관리: 요청마다 연결 생성 후 사용, 종료 시 close
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row  # 결과를 dict처럼 사용하기 위함
        db.execute('PRAGMA foreign_keys = ON')
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def add_user_security_columns(cursor):
    columns = {
        row['name']
        for row in cursor.execute('PRAGMA table_info(user)').fetchall()
    }
    if 'failed_login_attempts' not in columns:
        cursor.execute(
            'ALTER TABLE user ADD COLUMN failed_login_attempts INTEGER NOT NULL DEFAULT 0'
        )
    if 'locked_until' not in columns:
        cursor.execute('ALTER TABLE user ADD COLUMN locked_until INTEGER')


def migrate_plaintext_passwords(cursor):
    users = cursor.execute('SELECT id, password FROM user').fetchall()
    for user in users:
        if not user['password'].startswith('$argon2'):
            cursor.execute(
                'UPDATE user SET password = ? WHERE id = ?',
                (password_hasher.hash(user['password']), user['id']),
            )


def create_product_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS product (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL
                CHECK(length(trim(title)) BETWEEN
                    {PRODUCT_TITLE_MIN_LENGTH} AND {PRODUCT_TITLE_MAX_LENGTH})
                CHECK(instr(title, char(0)) = 0),
            description TEXT NOT NULL
                CHECK(length(trim(description)) BETWEEN
                    {PRODUCT_DESCRIPTION_MIN_LENGTH}
                    AND {PRODUCT_DESCRIPTION_MAX_LENGTH})
                CHECK(instr(description, char(0)) = 0),
            price INTEGER NOT NULL
                CHECK(
                    typeof(price) = 'integer'
                    AND price BETWEEN {PRODUCT_MIN_PRICE} AND {PRODUCT_MAX_PRICE}
                ),
            seller_id TEXT NOT NULL,
            FOREIGN KEY (seller_id) REFERENCES user(id) ON DELETE RESTRICT
        )
    """)


def product_schema_is_current(cursor):
    columns = {
        row['name']: row['type'].upper()
        for row in cursor.execute('PRAGMA table_info(product)').fetchall()
    }
    foreign_keys = cursor.execute('PRAGMA foreign_key_list(product)').fetchall()
    seller_foreign_key_exists = any(
        row['from'] == 'seller_id' and row['table'] == 'user'
        for row in foreign_keys
    )
    schema_row = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'product'"
    ).fetchone()
    normalized_schema = ''.join((schema_row['sql'] if schema_row else '').split()).lower()
    required_constraints = (
        (
            'check(length(trim(title))between'
            f'{PRODUCT_TITLE_MIN_LENGTH}and{PRODUCT_TITLE_MAX_LENGTH})'
        )
        in normalized_schema
        and (
            'check(length(trim(description))between'
            f'{PRODUCT_DESCRIPTION_MIN_LENGTH}and'
            f'{PRODUCT_DESCRIPTION_MAX_LENGTH})'
        )
        in normalized_schema
        and (
            "check(typeof(price)='integer'andpricebetween"
            f'{PRODUCT_MIN_PRICE}and{PRODUCT_MAX_PRICE})'
        )
        in normalized_schema
        and 'check(instr(title,char(0))=0)' in normalized_schema
        and 'check(instr(description,char(0))=0)' in normalized_schema
    )
    return (
        columns.get('price') == 'INTEGER'
        and seller_foreign_key_exists
        and required_constraints
    )


def migrate_product_schema(cursor):
    if product_schema_is_current(cursor):
        return

    products = cursor.execute(
        'SELECT id, title, description, price, seller_id FROM product'
    ).fetchall()
    migrated_products = []
    for product in products:
        title, description, price, validation_error = validate_product_input(
            product['title'],
            product['description'],
            str(product['price']),
        )
        seller_exists = cursor.execute(
            'SELECT 1 FROM user WHERE id = ?',
            (product['seller_id'],),
        ).fetchone()
        if validation_error or seller_exists is None:
            raise RuntimeError(
                f'기존 상품 {product["id"]}을 안전한 스키마로 '
                '변환할 수 없습니다.'
            )
        migrated_products.append(
            (product['id'], title, description, price, product['seller_id'])
        )

    cursor.execute('ALTER TABLE product RENAME TO product_legacy_v1')
    create_product_table(cursor)
    cursor.executemany(
        '''
        INSERT INTO product (id, title, description, price, seller_id)
        VALUES (?, ?, ?, ?, ?)
        ''',
        migrated_products,
    )
    cursor.execute('DROP TABLE product_legacy_v1')


# 테이블 생성 (최초 실행 시에만)
def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        # 사용자 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                bio TEXT,
                failed_login_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until INTEGER
            )
        """)
        # 상품 테이블 생성
        create_product_table(cursor)
        # 신고 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS report (
                id TEXT PRIMARY KEY,
                reporter_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                reason TEXT NOT NULL
            )
        """)
        add_user_security_columns(cursor)
        migrate_plaintext_passwords(cursor)
        migrate_product_schema(cursor)
        db.commit()


def normalize_username(value):
    return unicodedata.normalize('NFKC', value.strip())


def validate_username(username):
    if not USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH:
        return f'사용자명은 {USERNAME_MIN_LENGTH}~{USERNAME_MAX_LENGTH}자여야 합니다.'
    if not all(character.isalnum() or character in '_.-' for character in username):
        return '사용자명에는 문자, 숫자, 밑줄, 마침표, 하이픈만 사용할 수 있습니다.'
    return None


def validate_password(password):
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        return f'비밀번호는 {PASSWORD_MIN_LENGTH}~{PASSWORD_MAX_LENGTH}자여야 합니다.'
    if '\x00' in password or any(character.isspace() for character in password):
        return '비밀번호에는 공백이나 제어 문자를 사용할 수 없습니다.'
    if not any(character.isalpha() for character in password):
        return '비밀번호에는 문자가 하나 이상 포함되어야 합니다.'
    if not any(character.isdigit() for character in password):
        return '비밀번호에는 숫자가 하나 이상 포함되어야 합니다.'
    return None


def validate_bio(bio):
    if len(bio) > BIO_MAX_LENGTH:
        return f'소개글은 {BIO_MAX_LENGTH}자 이하여야 합니다.'
    if '\x00' in bio:
        return '소개글에 허용되지 않는 문자가 포함되어 있습니다.'
    return None


def validate_product_input(raw_title, raw_description, raw_price):
    title = unicodedata.normalize('NFKC', raw_title.strip())
    description = raw_description.strip()
    price_text = raw_price.strip()

    if not PRODUCT_TITLE_MIN_LENGTH <= len(title) <= PRODUCT_TITLE_MAX_LENGTH:
        return None, None, None, (
            f'상품 제목은 {PRODUCT_TITLE_MIN_LENGTH}~'
            f'{PRODUCT_TITLE_MAX_LENGTH}자여야 합니다.'
        )
    if '\x00' in title or any(
        unicodedata.category(character).startswith('C')
        for character in title
    ):
        return (
            None,
            None,
            None,
            '상품 제목에 허용되지 않는 문자가 포함되어 있습니다.',
        )
    if not (
        PRODUCT_DESCRIPTION_MIN_LENGTH
        <= len(description)
        <= PRODUCT_DESCRIPTION_MAX_LENGTH
    ):
        return None, None, None, (
            f'상품 설명은 {PRODUCT_DESCRIPTION_MIN_LENGTH}~'
            f'{PRODUCT_DESCRIPTION_MAX_LENGTH}자여야 합니다.'
        )
    if '\x00' in description:
        return (
            None,
            None,
            None,
            '상품 설명에 허용되지 않는 문자가 포함되어 있습니다.',
        )
    if not re.fullmatch(r'[0-9]+', price_text):
        return None, None, None, '가격은 0 이상의 정수로 입력해야 합니다.'
    if len(price_text) > len(str(PRODUCT_MAX_PRICE)):
        return None, None, None, (
            f'가격은 {PRODUCT_MIN_PRICE:,}원 이상 '
            f'{PRODUCT_MAX_PRICE:,}원 이하여야 합니다.'
        )

    price = int(price_text)
    if not PRODUCT_MIN_PRICE <= price <= PRODUCT_MAX_PRICE:
        return None, None, None, (
            f'가격은 {PRODUCT_MIN_PRICE:,}원 이상 '
            f'{PRODUCT_MAX_PRICE:,}원 이하여야 합니다.'
        )
    return title, description, price, None


def generate_csrf_token():
    token = session.get(CSRF_SESSION_KEY)
    if token is None:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


app.jinja_env.globals['csrf_token'] = generate_csrf_token


def csrf_protected(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        expected_token = session.get(CSRF_SESSION_KEY, '')
        submitted_token = request.form.get('csrf_token', '')
        if (
            not expected_token
            or not submitted_token
            or not hmac.compare_digest(expected_token, submitted_token)
        ):
            abort(400)
        return view(*args, **kwargs)

    return wrapped_view


def verify_password(password_hash, candidate):
    try:
        return password_hasher.verify(password_hash, candidate)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def record_failed_login(cursor, user, now):
    failed_attempts = user['failed_login_attempts'] + 1
    locked_until = None
    if failed_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
        failed_attempts = 0
        locked_until = now + LOGIN_LOCK_SECONDS
    cursor.execute(
        '''
        UPDATE user
        SET failed_login_attempts = ?, locked_until = ?
        WHERE id = ?
        ''',
        (failed_attempts, locked_until, user['id']),
    )


@app.before_request
def load_and_validate_session():
    g.current_user = None
    user_id = session.get('user_id')
    if user_id is None:
        return None

    now = int(time.time())
    authenticated_at = session.get('authenticated_at')
    last_activity = session.get('last_activity')
    session_expired = (
        not isinstance(authenticated_at, int)
        or not isinstance(last_activity, int)
        or now - authenticated_at > SESSION_ABSOLUTE_SECONDS
        or now - last_activity > SESSION_IDLE_SECONDS
    )
    if session_expired:
        session.clear()
        flash('세션이 만료되었습니다. 다시 로그인해주세요.')
        return redirect(url_for('login'))

    db = get_db()
    g.current_user = db.execute(
        'SELECT * FROM user WHERE id = ?',
        (user_id,),
    ).fetchone()
    if g.current_user is None:
        session.clear()
        flash('로그인 정보가 유효하지 않습니다. 다시 로그인해주세요.')
        return redirect(url_for('login'))

    session['last_activity'] = now
    return None


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.current_user is None:
            return redirect(url_for('login'))
        return view(*args, **kwargs)

    return wrapped_view


def get_product_or_404(product_id):
    try:
        normalized_product_id = str(uuid.UUID(product_id))
    except (ValueError, AttributeError):
        abort(404)
    if normalized_product_id != product_id.lower():
        abort(404)

    product = get_db().execute(
        'SELECT * FROM product WHERE id = ?',
        (normalized_product_id,),
    ).fetchone()
    if product is None:
        abort(404)
    return product


def require_product_owner(product):
    if g.current_user is None or product['seller_id'] != g.current_user['id']:
        abort(403)


# 기본 라우트
@app.route('/')
def index():
    if g.current_user is not None:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

# 회원가입
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        return register_post()
    return render_template('register.html')


@csrf_protected
def register_post():
    username = normalize_username(request.form.get('username', ''))
    password = request.form.get('password', '')
    validation_error = validate_username(username) or validate_password(password)
    if validation_error:
        flash(validation_error)
        return redirect(url_for('register'))

    db = get_db()
    cursor = db.cursor()
    password_hash = password_hasher.hash(password)
    cursor.execute('SELECT id FROM user WHERE username = ?', (username,))
    if cursor.fetchone() is not None:
        flash('회원가입 요청을 처리했습니다. 로그인해주세요.')
        return redirect(url_for('login'))

    user_id = str(uuid.uuid4())
    try:
        cursor.execute(
            'INSERT INTO user (id, username, password) VALUES (?, ?, ?)',
            (user_id, username, password_hash),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        flash('회원가입 요청을 처리했습니다. 로그인해주세요.')
        return redirect(url_for('login'))

    flash('회원가입 요청을 처리했습니다. 로그인해주세요.')
    return redirect(url_for('login'))


# 로그인
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        return login_post()
    return render_template('login.html')


@csrf_protected
def login_post():
    username = normalize_username(request.form.get('username', ''))
    password = request.form.get('password', '')
    if len(username) > USERNAME_MAX_LENGTH or len(password) > PASSWORD_MAX_LENGTH:
        flash('아이디 또는 비밀번호가 올바르지 않습니다.')
        return redirect(url_for('login'))

    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM user WHERE username = ?', (username,))
    user = cursor.fetchone()
    now = int(time.time())

    if user is None:
        verify_password(DUMMY_PASSWORD_HASH, password)
        flash('아이디 또는 비밀번호가 올바르지 않습니다.')
        return redirect(url_for('login'))

    if user['locked_until'] is not None and user['locked_until'] > now:
        verify_password(DUMMY_PASSWORD_HASH, password)
        flash('아이디 또는 비밀번호가 올바르지 않습니다.')
        return redirect(url_for('login'))

    if not verify_password(user['password'], password):
        record_failed_login(cursor, user, now)
        db.commit()
        flash('아이디 또는 비밀번호가 올바르지 않습니다.')
        return redirect(url_for('login'))

    if password_hasher.check_needs_rehash(user['password']):
        cursor.execute(
            'UPDATE user SET password = ? WHERE id = ?',
            (password_hasher.hash(password), user['id']),
        )
    cursor.execute(
        '''
        UPDATE user
        SET failed_login_attempts = 0, locked_until = NULL
        WHERE id = ?
        ''',
        (user['id'],),
    )
    db.commit()

    session.clear()
    session.permanent = True
    session['user_id'] = user['id']
    session['authenticated_at'] = now
    session['last_activity'] = now
    flash('로그인 성공!')
    return redirect(url_for('dashboard'))


# 로그아웃
@app.route('/logout', methods=['POST'])
@csrf_protected
def logout():
    session.clear()
    flash('로그아웃되었습니다.')
    return redirect(url_for('index'))

# 대시보드: 사용자 정보와 전체 상품 리스트 표시
@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    cursor = db.cursor()
    # 모든 상품 조회
    cursor.execute("SELECT * FROM product")
    all_products = cursor.fetchall()
    return render_template('dashboard.html', products=all_products, user=g.current_user)

# 프로필 페이지: bio 업데이트 가능
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        return profile_post()
    return render_template('profile.html', user=g.current_user)


@csrf_protected
def profile_post():
    bio = request.form.get('bio', '')
    current_password = request.form.get('current_password', '')
    validation_error = validate_bio(bio)
    if validation_error:
        flash(validation_error)
        return redirect(url_for('profile'))
    if (
        len(current_password) > PASSWORD_MAX_LENGTH
        or not verify_password(g.current_user['password'], current_password)
    ):
        flash('현재 비밀번호가 올바르지 않습니다.')
        return redirect(url_for('profile'))

    db = get_db()
    db.execute(
        'UPDATE user SET bio = ? WHERE id = ?',
        (bio, g.current_user['id']),
    )
    db.commit()
    flash('프로필이 업데이트되었습니다.')
    return redirect(url_for('profile'))

# 상품 등록
@app.route('/product/new', methods=['GET', 'POST'])
@login_required
def new_product():
    if request.method == 'POST':
        return new_product_post()
    return render_template('new_product.html')


@csrf_protected
def new_product_post():
    title, description, price, validation_error = validate_product_input(
        request.form.get('title', ''),
        request.form.get('description', ''),
        request.form.get('price', ''),
    )
    if validation_error:
        flash(validation_error)
        return redirect(url_for('new_product'))

    db = get_db()
    product_id = str(uuid.uuid4())
    try:
        db.execute(
            '''
            INSERT INTO product (id, title, description, price, seller_id)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (product_id, title, description, price, g.current_user['id']),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        abort(400)

    flash('상품이 등록되었습니다.')
    return redirect(url_for('view_product', product_id=product_id))


# 상품 상세보기
@app.route('/product/<product_id>')
def view_product(product_id):
    db = get_db()
    product = get_product_or_404(product_id)
    # 판매자 정보 조회
    seller = db.execute(
        'SELECT * FROM user WHERE id = ?',
        (product['seller_id'],),
    ).fetchone()
    return render_template('view_product.html', product=product, seller=seller)


@app.route('/product/<product_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product = get_product_or_404(product_id)
    require_product_owner(product)
    if request.method == 'POST':
        return edit_product_post(product)
    return render_template('edit_product.html', product=product)


@csrf_protected
def edit_product_post(product):
    title, description, price, validation_error = validate_product_input(
        request.form.get('title', ''),
        request.form.get('description', ''),
        request.form.get('price', ''),
    )
    if validation_error:
        flash(validation_error)
        return redirect(url_for('edit_product', product_id=product['id']))

    db = get_db()
    try:
        cursor = db.execute(
            '''
            UPDATE product
            SET title = ?, description = ?, price = ?
            WHERE id = ? AND seller_id = ?
            ''',
            (
                title,
                description,
                price,
                product['id'],
                g.current_user['id'],
            ),
        )
        if cursor.rowcount != 1:
            db.rollback()
            abort(404)
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        abort(400)

    flash('상품이 수정되었습니다.')
    return redirect(url_for('view_product', product_id=product['id']))


@app.route('/product/<product_id>/delete', methods=['POST'])
@login_required
@csrf_protected
def delete_product(product_id):
    product = get_product_or_404(product_id)
    require_product_owner(product)

    db = get_db()
    cursor = db.execute(
        'DELETE FROM product WHERE id = ? AND seller_id = ?',
        (product['id'], g.current_user['id']),
    )
    if cursor.rowcount != 1:
        db.rollback()
        abort(404)
    db.commit()
    flash('상품이 삭제되었습니다.')
    return redirect(url_for('dashboard'))


# 신고하기
@app.route('/report', methods=['GET', 'POST'])
@login_required
def report():
    if request.method == 'POST':
        target_id = request.form['target_id']
        reason = request.form['reason']
        db = get_db()
        cursor = db.cursor()
        report_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO report (id, reporter_id, target_id, reason) VALUES (?, ?, ?, ?)",
            (report_id, session['user_id'], target_id, reason)
        )
        db.commit()
        flash('신고가 접수되었습니다.')
        return redirect(url_for('dashboard'))
    return render_template('report.html')

# 실시간 채팅: 클라이언트가 메시지를 보내면 전체 브로드캐스트
@socketio.on('send_message')
def handle_send_message_event(data):
    data['message_id'] = str(uuid.uuid4())
    send(data, broadcast=True)


@app.errorhandler(400)
def bad_request(error):
    return render_template(
        'error.html',
        title='잘못된 요청',
        message='요청을 처리할 수 없습니다.',
    ), 400


@app.errorhandler(403)
def forbidden(error):
    return render_template(
        'error.html',
        title='접근 거부',
        message='이 요청을 수행할 권한이 없습니다.',
    ), 403


@app.errorhandler(404)
def not_found(error):
    return render_template(
        'error.html',
        title='페이지 없음',
        message='요청한 페이지를 찾을 수 없습니다.',
    ), 404


@app.errorhandler(429)
def too_many_requests(error):
    return render_template(
        'error.html',
        title='요청 제한',
        message='잠시 후 다시 시도해주세요.',
    ), 429


@app.errorhandler(500)
def internal_server_error(error):
    db = getattr(g, '_database', None)
    if db is not None:
        db.rollback()
    return render_template(
        'error.html',
        title='서버 오류',
        message='요청 처리 중 오류가 발생했습니다.',
    ), 500


if __name__ == '__main__':
    init_db()  # 앱 컨텍스트 내에서 테이블 생성
    socketio.run(app, debug=app.config['DEBUG'])
