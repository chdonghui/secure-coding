import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import uuid
from collections import deque
from datetime import timedelta
from functools import wraps

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from flask_socketio import SocketIO, disconnect, emit, join_room, send
from werkzeug.exceptions import SecurityError
from werkzeug.middleware.proxy_fix import ProxyFix


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
REPORT_REASON_MIN_LENGTH = 10
REPORT_REASON_MAX_LENGTH = 1000
MODERATION_REASON_MIN_LENGTH = 10
MODERATION_REASON_MAX_LENGTH = 500
MAX_REPORTS_PER_WINDOW = 5
REPORT_RATE_WINDOW_SECONDS = 60 * 60
MAX_REPORT_ATTEMPTS_PER_USER = 10
MAX_REPORT_ATTEMPTS_PER_IP = 20
REPORT_ATTEMPT_WINDOW_SECONDS = 60 * 60
CHAT_MESSAGE_MIN_LENGTH = 1
CHAT_MESSAGE_MAX_LENGTH = 500
CHAT_MAX_PAYLOAD_BYTES = 16 * 1024
CHAT_USER_RATE_LIMIT = 5
CHAT_USER_RATE_WINDOW_SECONDS = 10
CHAT_IP_RATE_LIMIT = 30
CHAT_IP_RATE_WINDOW_SECONDS = 60
CHAT_DUPLICATE_WINDOW_SECONDS = 5
DIRECT_CHAT_USER_LIST_LIMIT = 100
DIRECT_CHAT_HISTORY_LIMIT = 100
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 15 * 60
REGISTER_IP_RATE_LIMIT = 5
REGISTER_RATE_WINDOW_SECONDS = 60 * 60
LOGIN_IP_RATE_LIMIT = 20
LOGIN_RATE_WINDOW_SECONDS = 15 * 60
REAUTH_RATE_LIMIT = 10
REAUTH_RATE_WINDOW_SECONDS = 15 * 60
ADMIN_ACTION_RATE_LIMIT = 20
ADMIN_ACTION_RATE_WINDOW_SECONDS = 10 * 60
ADMIN_RECENT_AUTH_SECONDS = 5 * 60
PRODUCT_CREATE_RATE_LIMIT = 10
PRODUCT_CREATE_RATE_WINDOW_SECONDS = 60 * 60
MAX_PRODUCTS_PER_USER = 100
PRODUCT_SEARCH_MAX_LENGTH = 100
TRANSFER_MIN_AMOUNT = 1
TRANSFER_MAX_AMOUNT = 10_000_000
WALLET_MAX_BALANCE = 1_000_000_000_000
TRANSFER_MEMO_MAX_LENGTH = 100
TRANSFER_USER_RATE_LIMIT = 10
TRANSFER_IP_RATE_LIMIT = 30
TRANSFER_RATE_WINDOW_SECONDS = 10 * 60
TRANSFER_RECIPIENT_LIMIT = 100
ORDER_HISTORY_LIMIT = 100
SOCKET_CONNECT_IP_RATE_LIMIT = 20
SOCKET_CONNECT_RATE_WINDOW_SECONDS = 60
SOCKET_MAX_CONNECTIONS_PER_USER = 5
RATE_LIMIT_RETENTION_SECONDS = 24 * 60 * 60
PAGE_SIZE = 20
MAX_PAGE_NUMBER = 10_000
SESSION_IDLE_SECONDS = 30 * 60
SESSION_ABSOLUTE_SECONDS = 8 * 60 * 60
CSRF_SESSION_KEY = '_csrf_token'
ACCOUNT_DELETION_CONFIRMATION = '회원탈퇴'
COMMON_PASSWORDS = {
    '123456789012',
    'Password1234',
    'Qwerty123456',
    'Welcome12345',
    'Admin1234567',
}
REPORT_SENSITIVE_DATA_ERROR = (
    '신고 사유에 이메일, 전화번호 또는 '
    '주민등록번호를 입력할 수 없습니다.'
)
REPORT_EMAIL_PATTERN = re.compile(
    r'(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])',
    re.IGNORECASE,
)
REPORT_PHONE_PATTERN = re.compile(
    r'(?<!\d)(?:(?:\+?82[-.\s]?)?0?1[016789])'
    r'[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)'
)
REPORT_RESIDENT_ID_PATTERN = re.compile(
    r'(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)'
)


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


def get_integer_env(name, default, minimum=0, maximum=5):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed_value = int(value)
    except ValueError:
        raise RuntimeError(f'{name} 환경변수는 정수여야 합니다.') from None
    if not minimum <= parsed_value <= maximum:
        raise RuntimeError(
            f'{name} 환경변수는 {minimum}~{maximum} 범위여야 합니다.'
        )
    return parsed_value


def get_trusted_hosts():
    value = os.environ.get('MARKET_TRUSTED_HOSTS')
    if value is None:
        return ['localhost', '127.0.0.1', '[::1]']
    hosts = [host.strip().lower() for host in value.split(',') if host.strip()]
    if not hosts or any(
        '/' in host
        or '\\' in host
        or any(character.isspace() for character in host)
        for host in hosts
    ):
        raise RuntimeError(
            'MARKET_TRUSTED_HOSTS에는 쉼표로 구분한 Host 이름만 설정해야 합니다.'
        )
    return hosts


def socket_origin_is_allowed(origin, environ):
    if origin is None:
        return False
    if not isinstance(origin, str):
        return False
    scheme = environ.get('wsgi.url_scheme')
    host = environ.get('HTTP_HOST')
    if scheme not in {'http', 'https'} or not host:
        return False
    expected_origin = f'{scheme}://{host}'
    return hmac.compare_digest(
        origin.rstrip('/'),
        expected_origin.rstrip('/'),
    )


class RequireHttpsMiddleware:
    def __init__(self, wsgi_app, config):
        self.wsgi_app = wsgi_app
        self.config = config

    def __call__(self, environ, start_response):
        if (
            self.config['REQUIRE_HTTPS']
            and environ.get('wsgi.url_scheme') != 'https'
        ):
            response_body = b'Bad Request'
            start_response(
                '400 Bad Request',
                [
                    ('Content-Type', 'text/plain; charset=utf-8'),
                    ('Content-Length', str(len(response_body))),
                ],
            )
            return [response_body]
        return self.wsgi_app(environ, start_response)


app = Flask(__name__)
trusted_proxy_count = get_integer_env('MARKET_TRUSTED_PROXY_COUNT', 0)
app.config.update(
    SECRET_KEY=get_required_secret_key(),
    DEBUG=get_boolean_env('MARKET_DEBUG', False),
    MAX_CONTENT_LENGTH=1024 * 1024,
    PERMANENT_SESSION_LIFETIME=timedelta(seconds=SESSION_IDLE_SECONDS),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=get_boolean_env('MARKET_COOKIE_SECURE', True),
    REQUIRE_HTTPS=get_boolean_env('MARKET_REQUIRE_HTTPS', False),
    TRUSTED_PROXY_COUNT=trusted_proxy_count,
    TRUSTED_HOSTS=get_trusted_hosts(),
)
DATABASE = 'market.db'
socketio = SocketIO(
    app,
    cors_allowed_origins=socket_origin_is_allowed,
    max_http_buffer_size=CHAT_MAX_PAYLOAD_BYTES,
)
app.wsgi_app = RequireHttpsMiddleware(app.wsgi_app, app.config)
if trusted_proxy_count:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=trusted_proxy_count,
        x_proto=trusted_proxy_count,
    )
password_hasher = PasswordHasher()
DUMMY_PASSWORD_HASH = password_hasher.hash(
    'This password is used only to equalize failed-login verification time.'
)
chat_rate_limit_lock = threading.Lock()
chat_rate_limit_state = {
    'user': {},
    'ip': {},
}
chat_duplicate_state = {}


# 데이터베이스 연결 관리: 요청마다 연결 생성 후 사용, 종료 시 close
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        try:
            os.chmod(DATABASE, 0o600)
        except OSError as error:
            db.close()
            g._database = None
            raise RuntimeError(
                '데이터베이스 파일 권한을 안전하게 설정할 수 없습니다.'
            ) from error
        db.row_factory = sqlite3.Row  # 결과를 dict처럼 사용하기 위함
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('PRAGMA busy_timeout = 5000')
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
    if 'session_version' not in columns:
        cursor.execute(
            '''
            ALTER TABLE user
            ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0
            '''
        )
    if 'deleted_at' not in columns:
        cursor.execute(
            '''
            ALTER TABLE user
            ADD COLUMN deleted_at INTEGER
                CHECK(
                    deleted_at IS NULL
                    OR (
                        typeof(deleted_at) = 'integer'
                        AND deleted_at >= 0
                    )
                )
            '''
        )
    if 'is_admin' not in columns:
        cursor.execute(
            '''
            ALTER TABLE user
            ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0
                CHECK(
                    typeof(is_admin) = 'integer'
                    AND is_admin IN (0, 1)
                )
            '''
        )
    if 'account_type' not in columns:
        cursor.execute(
            '''
            ALTER TABLE user
            ADD COLUMN account_type TEXT NOT NULL DEFAULT 'user'
                CHECK(account_type IN ('user', 'business'))
            '''
        )


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


def create_direct_message_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS direct_message (
            id TEXT PRIMARY KEY,
            sender_id TEXT NOT NULL,
            recipient_id TEXT NOT NULL,
            message TEXT NOT NULL
                CHECK(length(trim(message)) BETWEEN
                    {CHAT_MESSAGE_MIN_LENGTH} AND {CHAT_MESSAGE_MAX_LENGTH})
                CHECK(instr(message, char(0)) = 0),
            created_at INTEGER NOT NULL
                CHECK(typeof(created_at) = 'integer' AND created_at >= 0),
            CHECK(sender_id <> recipient_id),
            FOREIGN KEY (sender_id) REFERENCES user(id) ON DELETE RESTRICT,
            FOREIGN KEY (recipient_id) REFERENCES user(id) ON DELETE RESTRICT
        )
    """)


def create_transfer_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallet_account (
            user_id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL
                CHECK(typeof(created_at) = 'integer' AND created_at >= 0),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE RESTRICT
        )
    """)


    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS wallet_adjustment (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            amount INTEGER NOT NULL
                CHECK(
                    typeof(amount) = 'integer'
                    AND amount BETWEEN 1 AND {WALLET_MAX_BALANCE}
                ),
            source_type TEXT NOT NULL
                CHECK(source_type = 'quickstart_demo_credit'),
            created_at INTEGER NOT NULL
                CHECK(typeof(created_at) = 'integer' AND created_at >= 0),
            FOREIGN KEY (user_id)
                REFERENCES wallet_account(user_id) ON DELETE RESTRICT
        )
    """)
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS money_transfer (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL UNIQUE,
            sender_id TEXT NOT NULL,
            recipient_id TEXT NOT NULL,
            amount INTEGER NOT NULL
                CHECK(
                    typeof(amount) = 'integer'
                    AND amount BETWEEN
                        {TRANSFER_MIN_AMOUNT} AND {TRANSFER_MAX_AMOUNT}
                ),
            memo TEXT NOT NULL DEFAULT ''
                CHECK(length(memo) <= {TRANSFER_MEMO_MAX_LENGTH})
                CHECK(instr(memo, char(0)) = 0),
            sender_username_snapshot TEXT NOT NULL,
            recipient_username_snapshot TEXT NOT NULL,
            created_at INTEGER NOT NULL
                CHECK(typeof(created_at) = 'integer' AND created_at >= 0),
            CHECK(sender_id <> recipient_id),
            FOREIGN KEY (sender_id)
                REFERENCES wallet_account(user_id) ON DELETE RESTRICT,
            FOREIGN KEY (recipient_id)
                REFERENCES wallet_account(user_id) ON DELETE RESTRICT
        )
    """)


def create_purchase_order_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS purchase_order (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL UNIQUE,
            buyer_id TEXT NOT NULL,
            seller_id TEXT NOT NULL,
            transfer_request_id TEXT NOT NULL UNIQUE,
            amount INTEGER NOT NULL
                CHECK(
                    typeof(amount) = 'integer'
                    AND amount BETWEEN
                        {TRANSFER_MIN_AMOUNT} AND {TRANSFER_MAX_AMOUNT}
                ),
            status TEXT NOT NULL CHECK(status = 'paid'),
            product_title_snapshot TEXT NOT NULL,
            buyer_username_snapshot TEXT NOT NULL,
            seller_username_snapshot TEXT NOT NULL,
            created_at INTEGER NOT NULL
                CHECK(typeof(created_at) = 'integer' AND created_at >= 0),
            CHECK(buyer_id <> seller_id),
            FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE RESTRICT,
            FOREIGN KEY (buyer_id) REFERENCES wallet_account(user_id)
                ON DELETE RESTRICT,
            FOREIGN KEY (seller_id) REFERENCES wallet_account(user_id)
                ON DELETE RESTRICT
        )
    """)


def ensure_purchase_order_schema(cursor):
    create_purchase_order_table(cursor)
    cursor.execute('DROP TRIGGER IF EXISTS validate_purchase_order')
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS validate_purchase_order
        BEFORE INSERT ON purchase_order
        WHEN
            NOT EXISTS (
                SELECT 1
                FROM product
                JOIN user AS seller ON seller.id = product.seller_id
                WHERE
                    product.id = NEW.product_id
                    AND product.seller_id = NEW.seller_id
                    AND product.price = NEW.amount
                    AND seller.username = NEW.seller_username_snapshot
                    AND seller.is_admin = 0
                    AND seller.account_type IN ('user', 'business')
                    AND seller.deleted_at IS NULL
                    AND NOT EXISTS (
                        SELECT 1
                        FROM user_dormancy
                        WHERE user_dormancy.user_id = seller.id
                    )
                    AND NOT EXISTS (
                        SELECT 1
                        FROM product_moderation
                        WHERE product_moderation.product_id = product.id
                    )
            )
            OR NOT EXISTS (
                SELECT 1
                FROM user AS buyer
                WHERE
                    buyer.id = NEW.buyer_id
                    AND buyer.username = NEW.buyer_username_snapshot
                    AND buyer.is_admin = 0
                    AND buyer.account_type = 'user'
                    AND buyer.deleted_at IS NULL
                    AND NOT EXISTS (
                        SELECT 1
                        FROM user_dormancy
                        WHERE user_dormancy.user_id = buyer.id
                    )
            )
            OR NOT EXISTS (
                SELECT 1
                FROM money_transfer
                WHERE
                    request_id = NEW.transfer_request_id
                    AND sender_id = NEW.buyer_id
                    AND recipient_id = NEW.seller_id
                    AND amount = NEW.amount
            )
        BEGIN
            SELECT RAISE(ABORT, 'invalid purchase order');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_purchase_order_update
        BEFORE UPDATE ON purchase_order
        BEGIN
            SELECT RAISE(ABORT, 'purchase order is append-only');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_purchase_order_delete
        BEFORE DELETE ON purchase_order
        BEGIN
            SELECT RAISE(ABORT, 'purchase order is append-only');
        END
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS purchase_order_buyer_created
        ON purchase_order (buyer_id, created_at DESC, id DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS purchase_order_seller_created
        ON purchase_order (seller_id, created_at DESC, id DESC)
    """)


def transfer_schema_is_current(cursor):
    required_columns = {
        'wallet_account': {'user_id', 'created_at'},
        'wallet_adjustment': {
            'id',
            'user_id',
            'amount',
            'source_type',
            'created_at',
        },
        'money_transfer': {
            'id',
            'request_id',
            'sender_id',
            'recipient_id',
            'amount',
            'memo',
            'sender_username_snapshot',
            'recipient_username_snapshot',
            'created_at',
        },
    }
    required_foreign_keys = {
        'wallet_account': {('user_id', 'user')},
        'wallet_adjustment': {('user_id', 'wallet_account')},
        'money_transfer': {
            ('sender_id', 'wallet_account'),
            ('recipient_id', 'wallet_account'),
        },
    }
    for table_name, expected_columns in required_columns.items():
        columns = {
            row['name']
            for row in cursor.execute(
                f'PRAGMA table_info({table_name})'
            ).fetchall()
        }
        foreign_keys = {
            (row['from'], row['table'])
            for row in cursor.execute(
                f'PRAGMA foreign_key_list({table_name})'
            ).fetchall()
        }
        if (
            not expected_columns <= columns
            or not required_foreign_keys[table_name] <= foreign_keys
        ):
            return False
    transfer_schema = cursor.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'money_transfer'
        """
    ).fetchone()
    normalized_transfer_schema = ''.join(
        (transfer_schema['sql'] if transfer_schema else '').split()
    ).lower()
    return all(
        required_text in normalized_transfer_schema
        for required_text in (
            'request_idtextnotnullunique',
            f'amountbetween{TRANSFER_MIN_AMOUNT}and{TRANSFER_MAX_AMOUNT}',
            f'check(length(memo)<={TRANSFER_MEMO_MAX_LENGTH})',
            'check(sender_id<>recipient_id)',
        )
    )


def wallet_balance_sql(user_expression):
    return f"""
        (
            COALESCE((
                SELECT SUM(wallet_adjustment.amount)
                FROM wallet_adjustment
                WHERE wallet_adjustment.user_id = {user_expression}
            ), 0)
            + COALESCE((
                SELECT SUM(incoming_transfer.amount)
                FROM money_transfer AS incoming_transfer
                WHERE incoming_transfer.recipient_id = {user_expression}
            ), 0)
            - COALESCE((
                SELECT SUM(outgoing_transfer.amount)
                FROM money_transfer AS outgoing_transfer
                WHERE outgoing_transfer.sender_id = {user_expression}
            ), 0)
        )
    """


def ensure_transfer_schema(cursor):
    create_transfer_tables(cursor)
    if not transfer_schema_is_current(cursor):
        raise RuntimeError(
            '기존 송금 스키마가 현재 무결성 요구사항과 호환되지 않습니다.'
        )

    now = int(time.time())
    cursor.execute(
        """
        INSERT OR IGNORE INTO wallet_account (user_id, created_at)
        SELECT id, ? FROM user
        """,
        (now,),
    )
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS create_wallet_for_new_user
        AFTER INSERT ON user
        BEGIN
            INSERT INTO wallet_account (user_id, created_at)
            VALUES (
                NEW.id,
                CAST(strftime('%s', 'now') AS INTEGER)
            );
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_wallet_account_update
        BEFORE UPDATE ON wallet_account
        BEGIN
            SELECT RAISE(ABORT, 'wallet account is immutable');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_wallet_account_delete
        BEFORE DELETE ON wallet_account
        BEGIN
            SELECT RAISE(ABORT, 'wallet account is immutable');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_wallet_adjustment_update
        BEFORE UPDATE ON wallet_adjustment
        BEGIN
            SELECT RAISE(ABORT, 'wallet adjustment is append-only');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_wallet_adjustment_delete
        BEFORE DELETE ON wallet_adjustment
        BEGIN
            SELECT RAISE(ABORT, 'wallet adjustment is append-only');
        END
    """)
    cursor.execute('DROP TRIGGER IF EXISTS validate_money_transfer_participants')
    cursor.execute(f"""
        CREATE TRIGGER IF NOT EXISTS validate_money_transfer_participants
        BEFORE INSERT ON money_transfer
        WHEN
            NOT EXISTS (
                SELECT 1
                FROM user
                WHERE
                    user.id = NEW.sender_id
                    AND user.is_admin = 0
                    AND user.account_type = 'user'
                    AND user.username = NEW.sender_username_snapshot
                    AND user.deleted_at IS NULL
                    AND NOT EXISTS (
                        SELECT 1
                        FROM user_dormancy
                        WHERE user_dormancy.user_id = user.id
                    )
            )
            OR NOT EXISTS (
                SELECT 1
                FROM user
                WHERE
                    user.id = NEW.recipient_id
                    AND user.is_admin = 0
                    AND user.account_type = 'user'
                    AND user.username = NEW.recipient_username_snapshot
                    AND user.deleted_at IS NULL
                    AND NOT EXISTS (
                        SELECT 1
                        FROM user_dormancy
                        WHERE user_dormancy.user_id = user.id
                    )
            )
        BEGIN
            SELECT RAISE(ABORT, 'invalid transfer participant');
        END
    """)
    sender_balance = wallet_balance_sql('NEW.sender_id')
    recipient_balance = wallet_balance_sql('NEW.recipient_id')
    cursor.execute(f"""
        CREATE TRIGGER IF NOT EXISTS prevent_money_transfer_overdraft
        BEFORE INSERT ON money_transfer
        WHEN {sender_balance} < NEW.amount
        BEGIN
            SELECT RAISE(ABORT, 'insufficient wallet balance');
        END
    """)
    cursor.execute(f"""
        CREATE TRIGGER IF NOT EXISTS prevent_money_transfer_overflow
        BEFORE INSERT ON money_transfer
        WHEN {recipient_balance} > {WALLET_MAX_BALANCE} - NEW.amount
        BEGIN
            SELECT RAISE(ABORT, 'wallet balance limit exceeded');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_money_transfer_update
        BEFORE UPDATE ON money_transfer
        BEGIN
            SELECT RAISE(ABORT, 'money transfer is append-only');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_money_transfer_delete
        BEFORE DELETE ON money_transfer
        BEGIN
            SELECT RAISE(ABORT, 'money transfer is append-only');
        END
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS money_transfer_sender_created
        ON money_transfer (sender_id, created_at DESC, id DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS money_transfer_recipient_created
        ON money_transfer (recipient_id, created_at DESC, id DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS wallet_adjustment_user_created
        ON wallet_adjustment (user_id, created_at DESC, id DESC)
    """)


def create_moderation_tables(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS product_moderation (
            product_id TEXT PRIMARY KEY,
            admin_id TEXT NOT NULL,
            reason TEXT NOT NULL
                CHECK(length(trim(reason)) BETWEEN
                    {MODERATION_REASON_MIN_LENGTH}
                    AND {MODERATION_REASON_MAX_LENGTH})
                CHECK(instr(reason, char(0)) = 0),
            created_at INTEGER NOT NULL
                CHECK(typeof(created_at) = 'integer' AND created_at >= 0),
            title_snapshot TEXT NOT NULL,
            description_snapshot TEXT NOT NULL,
            price_snapshot INTEGER NOT NULL,
            seller_id_snapshot TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE RESTRICT,
            FOREIGN KEY (admin_id) REFERENCES user(id) ON DELETE RESTRICT
        )
    """)
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS user_dormancy (
            user_id TEXT PRIMARY KEY,
            admin_id TEXT NOT NULL,
            reason TEXT NOT NULL
                CHECK(length(trim(reason)) BETWEEN
                    {MODERATION_REASON_MIN_LENGTH}
                    AND {MODERATION_REASON_MAX_LENGTH})
                CHECK(instr(reason, char(0)) = 0),
            created_at INTEGER NOT NULL
                CHECK(typeof(created_at) = 'integer' AND created_at >= 0),
            CHECK(user_id <> admin_id),
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE RESTRICT,
            FOREIGN KEY (admin_id) REFERENCES user(id) ON DELETE RESTRICT
        )
    """)
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS admin_action_audit (
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
                CHECK(length(trim(reason)) BETWEEN
                    {MODERATION_REASON_MIN_LENGTH}
                    AND {MODERATION_REASON_MAX_LENGTH})
                CHECK(instr(reason, char(0)) = 0),
            admin_username_snapshot TEXT NOT NULL,
            target_label_snapshot TEXT NOT NULL,
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
            FOREIGN KEY (target_user_id) REFERENCES user(id) ON DELETE RESTRICT,
            FOREIGN KEY (target_product_id)
                REFERENCES product(id) ON DELETE RESTRICT
        )
    """)


def migrate_moderation_metadata(cursor):
    product_columns = {
        row['name']
        for row in cursor.execute(
            'PRAGMA table_info(product_moderation)'
        ).fetchall()
    }
    audit_columns = {
        row['name']
        for row in cursor.execute(
            'PRAGMA table_info(admin_action_audit)'
        ).fetchall()
    }
    required_product_columns = {
        'title_snapshot': 'TEXT',
        'description_snapshot': 'TEXT',
        'price_snapshot': 'INTEGER',
        'seller_id_snapshot': 'TEXT',
    }
    required_audit_columns = {
        'admin_username_snapshot': 'TEXT',
        'target_label_snapshot': 'TEXT',
    }
    if not required_product_columns.keys() <= product_columns:
        cursor.execute('DROP TRIGGER IF EXISTS prevent_product_moderation_update')
        for column_name, column_type in required_product_columns.items():
            if column_name not in product_columns:
                cursor.execute(
                    f'ALTER TABLE product_moderation '
                    f'ADD COLUMN {column_name} {column_type}'
                )
        cursor.execute(
            '''
            UPDATE product_moderation
            SET
                title_snapshot = (
                    SELECT title FROM product
                    WHERE product.id = product_moderation.product_id
                ),
                description_snapshot = (
                    SELECT description FROM product
                    WHERE product.id = product_moderation.product_id
                ),
                price_snapshot = (
                    SELECT price FROM product
                    WHERE product.id = product_moderation.product_id
                ),
                seller_id_snapshot = (
                    SELECT seller_id FROM product
                    WHERE product.id = product_moderation.product_id
                )
            WHERE
                title_snapshot IS NULL
                OR description_snapshot IS NULL
                OR price_snapshot IS NULL
                OR seller_id_snapshot IS NULL
            '''
        )
    if not required_audit_columns.keys() <= audit_columns:
        cursor.execute('DROP TRIGGER IF EXISTS prevent_admin_action_audit_update')
        for column_name, column_type in required_audit_columns.items():
            if column_name not in audit_columns:
                cursor.execute(
                    f'ALTER TABLE admin_action_audit '
                    f'ADD COLUMN {column_name} {column_type}'
                )
        cursor.execute(
            '''
            UPDATE admin_action_audit
            SET
                admin_username_snapshot = (
                    SELECT username FROM user
                    WHERE user.id = admin_action_audit.admin_id
                ),
                target_label_snapshot = CASE
                    WHEN target_user_id IS NOT NULL THEN (
                        SELECT username FROM user
                        WHERE user.id = admin_action_audit.target_user_id
                    )
                    ELSE (
                        SELECT title FROM product
                        WHERE product.id = admin_action_audit.target_product_id
                    )
                END
            WHERE
                admin_username_snapshot IS NULL
                OR target_label_snapshot IS NULL
            '''
        )
    incomplete_product_snapshot = cursor.execute(
        '''
        SELECT 1
        FROM product_moderation
        WHERE
            title_snapshot IS NULL
            OR description_snapshot IS NULL
            OR price_snapshot IS NULL
            OR seller_id_snapshot IS NULL
        LIMIT 1
        '''
    ).fetchone()
    incomplete_audit_snapshot = cursor.execute(
        '''
        SELECT 1
        FROM admin_action_audit
        WHERE
            admin_username_snapshot IS NULL
            OR target_label_snapshot IS NULL
        LIMIT 1
        '''
    ).fetchone()
    if incomplete_product_snapshot or incomplete_audit_snapshot:
        raise RuntimeError(
            '기존 관리자 처리 기록의 Snapshot을 안전하게 복원할 수 없습니다.'
        )


def create_admin_role_audit_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS admin_role_audit (
            id TEXT PRIMARY KEY,
            operator_name TEXT NOT NULL
                CHECK(length(trim(operator_name)) BETWEEN 1 AND 100)
                CHECK(instr(operator_name, char(0)) = 0),
            target_user_id TEXT NOT NULL,
            target_username_snapshot TEXT NOT NULL,
            action_type TEXT NOT NULL
                CHECK(action_type IN ('admin_granted', 'admin_revoked')),
            reason TEXT NOT NULL
                CHECK(length(trim(reason)) BETWEEN
                    {MODERATION_REASON_MIN_LENGTH}
                    AND {MODERATION_REASON_MAX_LENGTH})
                CHECK(instr(reason, char(0)) = 0),
            created_at INTEGER NOT NULL
                CHECK(typeof(created_at) = 'integer' AND created_at >= 0),
            FOREIGN KEY (target_user_id) REFERENCES user(id) ON DELETE RESTRICT
        )
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS validate_admin_role_audit_snapshot
        BEFORE INSERT ON admin_role_audit
        WHEN NOT EXISTS (
            SELECT 1
            FROM user
            WHERE
                user.id = NEW.target_user_id
                AND user.username = NEW.target_username_snapshot
                AND (
                    (
                        NEW.action_type = 'admin_granted'
                        AND user.is_admin = 1
                    )
                    OR (
                        NEW.action_type = 'admin_revoked'
                        AND user.is_admin = 0
                    )
                )
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid admin role audit snapshot');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_admin_role_audit_update
        BEFORE UPDATE ON admin_role_audit
        BEGIN
            SELECT RAISE(ABORT, 'admin role audit log is append-only');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_admin_role_audit_delete
        BEFORE DELETE ON admin_role_audit
        BEGIN
            SELECT RAISE(ABORT, 'admin role audit log is append-only');
        END
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS admin_role_audit_created
        ON admin_role_audit (created_at DESC, id DESC)
    """)


def create_business_role_audit_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS business_role_audit (
            id TEXT PRIMARY KEY,
            operator_name TEXT NOT NULL
                CHECK(length(trim(operator_name)) BETWEEN 1 AND 100)
                CHECK(instr(operator_name, char(0)) = 0),
            target_user_id TEXT NOT NULL,
            target_username_snapshot TEXT NOT NULL,
            action_type TEXT NOT NULL
                CHECK(action_type IN ('business_granted', 'business_revoked')),
            reason TEXT NOT NULL
                CHECK(length(trim(reason)) BETWEEN
                    {MODERATION_REASON_MIN_LENGTH} AND
                    {MODERATION_REASON_MAX_LENGTH})
                CHECK(instr(reason, char(0)) = 0),
            created_at INTEGER NOT NULL
                CHECK(typeof(created_at) = 'integer' AND created_at >= 0),
            FOREIGN KEY (target_user_id) REFERENCES user(id) ON DELETE RESTRICT
        )
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS validate_business_role_audit_snapshot
        BEFORE INSERT ON business_role_audit
        WHEN NOT EXISTS (
            SELECT 1
            FROM user
            WHERE
                user.id = NEW.target_user_id
                AND user.username = NEW.target_username_snapshot
                AND (
                    (
                        NEW.action_type = 'business_granted'
                        AND user.account_type = 'business'
                    )
                    OR (
                        NEW.action_type = 'business_revoked'
                        AND user.account_type = 'user'
                    )
                )
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid business role audit snapshot');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_business_role_audit_update
        BEFORE UPDATE ON business_role_audit
        BEGIN
            SELECT RAISE(ABORT, 'business role audit log is append-only');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_business_role_audit_delete
        BEFORE DELETE ON business_role_audit
        BEGIN
            SELECT RAISE(ABORT, 'business role audit log is append-only');
        END
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS business_role_audit_created
        ON business_role_audit (created_at DESC, id DESC)
    """)


def moderation_schema_is_current(cursor):
    required_columns = {
        'product_moderation': {
            'product_id',
            'admin_id',
            'reason',
            'created_at',
            'title_snapshot',
            'description_snapshot',
            'price_snapshot',
            'seller_id_snapshot',
        },
        'user_dormancy': {
            'user_id',
            'admin_id',
            'reason',
            'created_at',
        },
        'admin_action_audit': {
            'id',
            'admin_id',
            'action_type',
            'target_user_id',
            'target_product_id',
            'reason',
            'admin_username_snapshot',
            'target_label_snapshot',
            'created_at',
        },
    }
    required_foreign_keys = {
        'product_moderation': {
            ('product_id', 'product'),
            ('admin_id', 'user'),
        },
        'user_dormancy': {
            ('user_id', 'user'),
            ('admin_id', 'user'),
        },
        'admin_action_audit': {
            ('admin_id', 'user'),
            ('target_user_id', 'user'),
            ('target_product_id', 'product'),
        },
    }
    for table_name, expected_columns in required_columns.items():
        columns = {
            row['name']
            for row in cursor.execute(
                f'PRAGMA table_info({table_name})'
            ).fetchall()
        }
        foreign_keys = {
            (row['from'], row['table'])
            for row in cursor.execute(
                f'PRAGMA foreign_key_list({table_name})'
            ).fetchall()
        }
        schema_row = cursor.execute(
            '''
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            ''',
            (table_name,),
        ).fetchone()
        normalized_schema = ''.join(
            (schema_row['sql'] if schema_row else '').split()
        ).lower()
        required_constraints = (
            (
                'check(length(trim(reason))between'
                f'{MODERATION_REASON_MIN_LENGTH}and'
                f'{MODERATION_REASON_MAX_LENGTH})'
            )
            in normalized_schema
            and 'check(instr(reason,char(0))=0)' in normalized_schema
            and (
                "check(typeof(created_at)='integer'andcreated_at>=0)"
                in normalized_schema
            )
        )
        if (
            not expected_columns <= columns
            or not required_foreign_keys[table_name] <= foreign_keys
            or not required_constraints
        ):
            return False
        if (
            table_name == 'user_dormancy'
            and 'check(user_id<>admin_id)' not in normalized_schema
        ):
            return False
        if table_name == 'admin_action_audit' and not all(
            required_text in normalized_schema
            for required_text in (
                "'product_removed'",
                "'user_dormant'",
                "'user_reactivated'",
                "action_type='product_removed'",
                "action_typein('user_dormant','user_reactivated')",
            )
        ):
            return False
    return True


def ensure_moderation_schema(cursor):
    create_moderation_tables(cursor)
    migrate_moderation_metadata(cursor)
    if not moderation_schema_is_current(cursor):
        raise RuntimeError(
            '기존 관리자 처리 스키마가 현재 보안 요구사항과 호환되지 않습니다.'
        )
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS validate_product_moderation_admin
        BEFORE INSERT ON product_moderation
        WHEN NOT EXISTS (
            SELECT 1
            FROM user
            WHERE
                user.id = NEW.admin_id
                AND user.is_admin = 1
                AND user.deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM user_dormancy
                    WHERE user_dormancy.user_id = user.id
                )
        )
        BEGIN
            SELECT RAISE(ABORT, 'administrator required');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS validate_product_moderation_snapshot
        BEFORE INSERT ON product_moderation
        WHEN NOT EXISTS (
            SELECT 1
            FROM product
            WHERE
                product.id = NEW.product_id
                AND product.title = NEW.title_snapshot
                AND product.description = NEW.description_snapshot
                AND product.price = NEW.price_snapshot
                AND product.seller_id = NEW.seller_id_snapshot
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid product moderation snapshot');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS validate_user_dormancy_admin
        BEFORE INSERT ON user_dormancy
        WHEN
            NOT EXISTS (
                SELECT 1
                FROM user
                WHERE
                    user.id = NEW.admin_id
                    AND user.is_admin = 1
                    AND user.deleted_at IS NULL
                    AND NOT EXISTS (
                        SELECT 1
                        FROM user_dormancy
                        WHERE user_dormancy.user_id = user.id
                    )
            )
            OR NOT EXISTS (
                SELECT 1
                FROM user
                WHERE
                    user.id = NEW.user_id
                    AND user.is_admin = 0
                    AND user.deleted_at IS NULL
            )
        BEGIN
            SELECT RAISE(ABORT, 'invalid dormancy action');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS validate_admin_action_audit_admin
        BEFORE INSERT ON admin_action_audit
        WHEN NOT EXISTS (
            SELECT 1
            FROM user
            WHERE
                user.id = NEW.admin_id
                AND user.is_admin = 1
                AND user.deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM user_dormancy
                    WHERE user_dormancy.user_id = user.id
                )
        )
        BEGIN
            SELECT RAISE(ABORT, 'administrator required');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS validate_admin_action_audit_snapshot
        BEFORE INSERT ON admin_action_audit
        WHEN
            NOT EXISTS (
                SELECT 1
                FROM user
                WHERE
                    user.id = NEW.admin_id
                    AND user.username = NEW.admin_username_snapshot
            )
            OR (
                NEW.target_user_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM user
                    WHERE
                        user.id = NEW.target_user_id
                        AND user.username = NEW.target_label_snapshot
                )
            )
            OR (
                NEW.target_product_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM product
                    WHERE
                        product.id = NEW.target_product_id
                        AND product.title = NEW.target_label_snapshot
                )
            )
        BEGIN
            SELECT RAISE(ABORT, 'invalid admin audit snapshot');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_product_moderation_update
        BEFORE UPDATE ON product_moderation
        BEGIN
            SELECT RAISE(ABORT, 'product moderation is append-only');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_product_moderation_delete
        BEFORE DELETE ON product_moderation
        BEGIN
            SELECT RAISE(ABORT, 'product moderation is append-only');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_admin_action_audit_update
        BEFORE UPDATE ON admin_action_audit
        BEGIN
            SELECT RAISE(ABORT, 'admin audit log is append-only');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_admin_action_audit_delete
        BEFORE DELETE ON admin_action_audit
        BEGIN
            SELECT RAISE(ABORT, 'admin audit log is append-only');
        END
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS admin_action_audit_created
        ON admin_action_audit (created_at DESC, id DESC)
    """)


def direct_message_schema_is_current(cursor):
    columns = {
        row['name']
        for row in cursor.execute(
            'PRAGMA table_info(direct_message)'
        ).fetchall()
    }
    foreign_keys = {
        (row['from'], row['table'])
        for row in cursor.execute(
            'PRAGMA foreign_key_list(direct_message)'
        ).fetchall()
    }
    schema_row = cursor.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'direct_message'
        """
    ).fetchone()
    normalized_schema = ''.join(
        (schema_row['sql'] if schema_row else '').split()
    ).lower()
    return (
        {
            'id',
            'sender_id',
            'recipient_id',
            'message',
            'created_at',
        }
        <= columns
        and {
            ('sender_id', 'user'),
            ('recipient_id', 'user'),
        }
        <= foreign_keys
        and 'check(sender_id<>recipient_id)' in normalized_schema
        and (
            'check(length(trim(message))between'
            f'{CHAT_MESSAGE_MIN_LENGTH}and{CHAT_MESSAGE_MAX_LENGTH})'
        )
        in normalized_schema
        and 'check(instr(message,char(0))=0)' in normalized_schema
        and (
            "check(typeof(created_at)='integer'andcreated_at>=0)"
            in normalized_schema
        )
    )


def ensure_direct_message_schema(cursor):
    create_direct_message_table(cursor)
    if not direct_message_schema_is_current(cursor):
        raise RuntimeError(
            '기존 1대1 채팅 스키마가 현재 보안 요구사항과 호환되지 않습니다.'
        )
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS direct_message_sender_recipient_created
        ON direct_message (sender_id, recipient_id, created_at, id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS direct_message_recipient_sender_created
        ON direct_message (recipient_id, sender_id, created_at, id)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_block (
            blocker_id TEXT NOT NULL,
            blocked_id TEXT NOT NULL,
            created_at INTEGER NOT NULL
                CHECK(typeof(created_at) = 'integer' AND created_at >= 0),
            PRIMARY KEY (blocker_id, blocked_id),
            CHECK(blocker_id <> blocked_id),
            FOREIGN KEY (blocker_id) REFERENCES user(id) ON DELETE RESTRICT,
            FOREIGN KEY (blocked_id) REFERENCES user(id) ON DELETE RESTRICT
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS user_block_blocked
        ON user_block (blocked_id, blocker_id)
    """)


def create_current_security_rate_limit_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS security_rate_limit (
            scope_type TEXT NOT NULL
                CHECK(
                    scope_type IN (
                        'register_ip',
                        'login_ip',
                        'reauth_user',
                        'reauth_ip',
                        'admin_user',
                        'product_user',
                        'transfer_user',
                        'transfer_ip',
                        'socket_ip'
                    )
                ),
            scope_key TEXT NOT NULL,
            window_started_at INTEGER NOT NULL
                CHECK(typeof(window_started_at) = 'integer'),
            attempt_count INTEGER NOT NULL
                CHECK(typeof(attempt_count) = 'integer' AND attempt_count >= 1),
            PRIMARY KEY (scope_type, scope_key)
        )
    """)


def create_security_rate_limit_table(cursor):
    table = cursor.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'security_rate_limit'
        """
    ).fetchone()
    if table is not None:
        normalized_schema = ''.join(table['sql'].split()).lower()
        if not all(
            f"'{scope_type}'" in normalized_schema
            for scope_type in (
                'register_ip',
                'login_ip',
                'reauth_user',
                'reauth_ip',
                'admin_user',
                'product_user',
                'transfer_user',
                'transfer_ip',
                'socket_ip',
            )
        ):
            columns = {
                row['name']
                for row in cursor.execute(
                    'PRAGMA table_info(security_rate_limit)'
                ).fetchall()
            }
            if columns != {
                'scope_type',
                'scope_key',
                'window_started_at',
                'attempt_count',
            }:
                raise RuntimeError(
                    '기존 요청 제한 스키마를 안전하게 변환할 수 없습니다.'
                )
            cursor.execute(
                'DROP INDEX IF EXISTS security_rate_limit_window'
            )
            cursor.execute(
                'ALTER TABLE security_rate_limit '
                'RENAME TO security_rate_limit_legacy_v31'
            )
            create_current_security_rate_limit_table(cursor)
            cursor.execute("""
                INSERT INTO security_rate_limit (
                    scope_type,
                    scope_key,
                    window_started_at,
                    attempt_count
                )
                SELECT
                    scope_type,
                    scope_key,
                    window_started_at,
                    attempt_count
                FROM security_rate_limit_legacy_v31
                WHERE scope_type IN (
                    'register_ip',
                    'login_ip',
                    'reauth_user',
                    'reauth_ip',
                    'admin_user',
                    'product_user',
                    'socket_ip'
                )
            """)
            cursor.execute('DROP TABLE security_rate_limit_legacy_v31')
    create_current_security_rate_limit_table(cursor)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS security_rate_limit_window
        ON security_rate_limit (window_started_at)
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


def ensure_product_indexes(cursor):
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS product_seller_title
        ON product (seller_id, title, id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS product_title
        ON product (title, id)
    """)


def create_report_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS report (
            id TEXT PRIMARY KEY,
            reporter_id TEXT NOT NULL,
            target_type TEXT NOT NULL
                CHECK(target_type IN ('user', 'product')),
            target_user_id TEXT,
            target_product_id TEXT,
            reason TEXT NOT NULL
                CHECK(length(trim(reason)) BETWEEN
                    {REPORT_REASON_MIN_LENGTH} AND {REPORT_REASON_MAX_LENGTH})
                CHECK(instr(reason, char(0)) = 0),
            created_at INTEGER NOT NULL
                CHECK(typeof(created_at) = 'integer' AND created_at >= 0),
            CHECK(
                (
                    target_type = 'user'
                    AND target_user_id IS NOT NULL
                    AND target_product_id IS NULL
                    AND reporter_id <> target_user_id
                )
                OR
                (
                    target_type = 'product'
                    AND target_user_id IS NULL
                    AND target_product_id IS NOT NULL
                )
            ),
            FOREIGN KEY (reporter_id) REFERENCES user(id) ON DELETE RESTRICT,
            FOREIGN KEY (target_user_id) REFERENCES user(id) ON DELETE RESTRICT,
            FOREIGN KEY (target_product_id)
                REFERENCES product(id) ON DELETE RESTRICT
        )
    """)


def create_report_audit_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS report_audit_log (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL
                CHECK(event_type IN (
                    'report_created',
                    'report_migrated',
                    'report_rejected_validation',
                    'report_rejected_sensitive_data',
                    'report_rejected_duplicate',
                    'report_rejected_user_rate',
                    'report_rejected_ip_rate'
                )),
            actor_id TEXT NOT NULL,
            target_type TEXT
                CHECK(
                    target_type IS NULL
                    OR target_type IN ('user', 'product')
                ),
            target_id TEXT,
            source_ip_hash TEXT
                CHECK(
                    source_ip_hash IS NULL
                    OR (
                        length(source_ip_hash) = 64
                        AND source_ip_hash NOT GLOB '*[^0-9a-f]*'
                    )
                ),
            created_at INTEGER NOT NULL
                CHECK(typeof(created_at) = 'integer' AND created_at >= 0),
            FOREIGN KEY (actor_id) REFERENCES user(id) ON DELETE RESTRICT
        )
    """)


def create_report_rate_limit_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS report_rate_limit (
            scope_type TEXT NOT NULL
                CHECK(scope_type IN ('user', 'ip')),
            scope_key TEXT NOT NULL,
            window_started_at INTEGER NOT NULL
                CHECK(typeof(window_started_at) = 'integer'),
            attempt_count INTEGER NOT NULL
                CHECK(typeof(attempt_count) = 'integer' AND attempt_count >= 1),
            blocked_logged INTEGER NOT NULL DEFAULT 0
                CHECK(blocked_logged IN (0, 1)),
            PRIMARY KEY (scope_type, scope_key)
        )
    """)


def create_report_review_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS report_review (
            report_id TEXT PRIMARY KEY,
            admin_id TEXT NOT NULL,
            admin_username_snapshot TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK(status IN ('resolved', 'dismissed')),
            note TEXT NOT NULL
                CHECK(length(trim(note)) BETWEEN
                    {MODERATION_REASON_MIN_LENGTH}
                    AND {MODERATION_REASON_MAX_LENGTH})
                CHECK(instr(note, char(0)) = 0),
            reviewed_at INTEGER NOT NULL
                CHECK(typeof(reviewed_at) = 'integer' AND reviewed_at >= 0),
            FOREIGN KEY (report_id) REFERENCES report(id) ON DELETE RESTRICT,
            FOREIGN KEY (admin_id) REFERENCES user(id) ON DELETE RESTRICT
        )
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS validate_report_review_admin
        BEFORE INSERT ON report_review
        WHEN NOT EXISTS (
            SELECT 1
            FROM user
            WHERE
                user.id = NEW.admin_id
                AND user.is_admin = 1
                AND user.deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM user_dormancy
                    WHERE user_dormancy.user_id = user.id
                )
        )
        BEGIN
            SELECT RAISE(ABORT, 'administrator required');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS validate_report_review_snapshot
        BEFORE INSERT ON report_review
        WHEN NOT EXISTS (
            SELECT 1
            FROM user
            WHERE
                user.id = NEW.admin_id
                AND user.username = NEW.admin_username_snapshot
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid report review snapshot');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_report_review_update
        BEFORE UPDATE ON report_review
        BEGIN
            SELECT RAISE(ABORT, 'report review is append-only');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_report_review_delete
        BEFORE DELETE ON report_review
        BEGIN
            SELECT RAISE(ABORT, 'report review is append-only');
        END
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS report_review_status_time
        ON report_review (status, reviewed_at DESC, report_id)
    """)


def ensure_report_schema_objects(cursor):
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS report_unique_user_target
        ON report (reporter_id, target_user_id)
        WHERE target_type = 'user'
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS report_unique_product_target
        ON report (reporter_id, target_product_id)
        WHERE target_type = 'product'
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS report_reporter_created_at
        ON report (reporter_id, created_at)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS report_target_user_created
        ON report (target_user_id, created_at DESC)
        WHERE target_type = 'user'
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS report_target_product_created
        ON report (target_product_id, created_at DESC)
        WHERE target_type = 'product'
    """)
    cursor.execute(f"""
        CREATE TRIGGER IF NOT EXISTS prevent_report_rate_limit_bypass
        BEFORE INSERT ON report
        WHEN (
            SELECT COUNT(*)
            FROM report
            WHERE reporter_id = NEW.reporter_id
                AND created_at >= NEW.created_at - {REPORT_RATE_WINDOW_SECONDS}
        ) >= {MAX_REPORTS_PER_WINDOW}
        BEGIN
            SELECT RAISE(ABORT, 'report rate limit exceeded');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_duplicate_report_insert
        BEFORE INSERT ON report
        WHEN EXISTS (
            SELECT 1
            FROM report
            WHERE reporter_id = NEW.reporter_id
                AND (
                    (
                        NEW.target_type = 'user'
                        AND target_user_id = NEW.target_user_id
                    )
                    OR
                    (
                        NEW.target_type = 'product'
                        AND target_product_id = NEW.target_product_id
                    )
                )
        )
        BEGIN
            SELECT RAISE(ABORT, 'duplicate report');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_own_product_report_insert
        BEFORE INSERT ON report
        WHEN NEW.target_type = 'product'
            AND EXISTS (
                SELECT 1
                FROM product
                WHERE id = NEW.target_product_id
                    AND seller_id = NEW.reporter_id
            )
        BEGIN
            SELECT RAISE(ABORT, 'invalid report target');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_own_product_report_update
        BEFORE UPDATE ON report
        WHEN NEW.target_type = 'product'
            AND EXISTS (
                SELECT 1
                FROM product
                WHERE id = NEW.target_product_id
                    AND seller_id = NEW.reporter_id
            )
        BEGIN
            SELECT RAISE(ABORT, 'invalid report target');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_report_audit_log_update
        BEFORE UPDATE ON report_audit_log
        BEGIN
            SELECT RAISE(ABORT, 'report audit log is append-only');
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_report_audit_log_delete
        BEFORE DELETE ON report_audit_log
        BEGIN
            SELECT RAISE(ABORT, 'report audit log is append-only');
        END
    """)


def report_schema_is_current(cursor):
    columns = {
        row['name']
        for row in cursor.execute('PRAGMA table_info(report)').fetchall()
    }
    required_columns = {
        'id',
        'reporter_id',
        'target_type',
        'target_user_id',
        'target_product_id',
        'reason',
        'created_at',
    }
    foreign_keys = cursor.execute('PRAGMA foreign_key_list(report)').fetchall()
    required_foreign_keys = {
        ('reporter_id', 'user'),
        ('target_user_id', 'user'),
        ('target_product_id', 'product'),
    }
    actual_foreign_keys = {
        (row['from'], row['table'])
        for row in foreign_keys
    }
    schema_row = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'report'"
    ).fetchone()
    normalized_schema = ''.join(
        (schema_row['sql'] if schema_row else '').split()
    ).lower()
    required_constraints = (
        (
            'check(length(trim(reason))between'
            f'{REPORT_REASON_MIN_LENGTH}and{REPORT_REASON_MAX_LENGTH})'
        )
        in normalized_schema
        and 'check(instr(reason,char(0))=0)' in normalized_schema
        and "check(target_typein('user','product'))" in normalized_schema
    )
    return (
        required_columns <= columns
        and required_foreign_keys <= actual_foreign_keys
        and required_constraints
    )


def report_audit_schema_is_current(cursor):
    columns = {
        row['name']
        for row in cursor.execute(
            'PRAGMA table_info(report_audit_log)'
        ).fetchall()
    }
    schema_row = cursor.execute(
        '''
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'report_audit_log'
        '''
    ).fetchone()
    normalized_schema = ''.join(
        (schema_row['sql'] if schema_row else '').split()
    ).lower()
    required_events = {
        'report_created',
        'report_migrated',
        'report_rejected_validation',
        'report_rejected_sensitive_data',
        'report_rejected_duplicate',
        'report_rejected_user_rate',
        'report_rejected_ip_rate',
    }
    return (
        'source_ip_hash' in columns
        and all(event in normalized_schema for event in required_events)
    )


def migrate_report_audit_schema(cursor):
    if report_audit_schema_is_current(cursor):
        return

    columns = {
        row['name']
        for row in cursor.execute(
            'PRAGMA table_info(report_audit_log)'
        ).fetchall()
    }
    source_ip_expression = (
        'source_ip_hash'
        if 'source_ip_hash' in columns
        else 'NULL AS source_ip_hash'
    )
    audit_rows = cursor.execute(
        f'''
        SELECT
            id,
            event_type,
            actor_id,
            target_type,
            target_id,
            {source_ip_expression},
            created_at
        FROM report_audit_log
        '''
    ).fetchall()

    cursor.execute('DROP TRIGGER IF EXISTS prevent_report_audit_log_update')
    cursor.execute('DROP TRIGGER IF EXISTS prevent_report_audit_log_delete')
    cursor.execute(
        'ALTER TABLE report_audit_log RENAME TO report_audit_log_legacy_v1'
    )
    create_report_audit_table(cursor)
    cursor.executemany(
        '''
        INSERT INTO report_audit_log (
            id,
            event_type,
            actor_id,
            target_type,
            target_id,
            source_ip_hash,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        [
            (
                row['id'],
                row['event_type'],
                row['actor_id'],
                row['target_type'],
                row['target_id'],
                row['source_ip_hash'],
                row['created_at'],
            )
            for row in audit_rows
        ],
    )
    cursor.execute('DROP TABLE report_audit_log_legacy_v1')


def add_report_audit_log(
    cursor,
    event_type,
    actor_id,
    target_type,
    target_id,
    created_at,
    source_ip_hash=None,
):
    cursor.execute(
        '''
        INSERT INTO report_audit_log (
            id,
            event_type,
            actor_id,
            target_type,
            target_id,
            source_ip_hash,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            str(uuid.uuid4()),
            event_type,
            actor_id,
            target_type,
            target_id,
            source_ip_hash,
            created_at,
        ),
    )


def migrate_report_schema(cursor):
    if report_schema_is_current(cursor):
        return

    reports = cursor.execute(
        'SELECT id, reporter_id, target_id, reason FROM report'
    ).fetchall()
    migrated_reports = []
    seen_targets = set()
    migration_time = int(time.time())
    for report_row in reports:
        try:
            report_id = str(uuid.UUID(report_row['id']))
            target_id = str(uuid.UUID(report_row['target_id']))
        except (ValueError, AttributeError):
            raise RuntimeError(
                '기존 신고 데이터에 올바르지 않은 UUID가 포함되어 있습니다.'
            ) from None

        reporter = cursor.execute(
            'SELECT id FROM user WHERE id = ?',
            (report_row['reporter_id'],),
        ).fetchone()
        target_user = cursor.execute(
            'SELECT id FROM user WHERE id = ?',
            (target_id,),
        ).fetchone()
        target_product = cursor.execute(
            'SELECT id, seller_id FROM product WHERE id = ?',
            (target_id,),
        ).fetchone()
        reason, reason_error = validate_report_reason(report_row['reason'])
        target_count = int(target_user is not None) + int(target_product is not None)
        invalid_self_target = (
            target_user is not None
            and target_user['id'] == report_row['reporter_id']
        ) or (
            target_product is not None
            and target_product['seller_id'] == report_row['reporter_id']
        )
        if (
            reporter is None
            or target_count != 1
            or invalid_self_target
            or reason_error
        ):
            raise RuntimeError(
                f'기존 신고 {report_id}을 안전한 스키마로 변환할 수 없습니다.'
            )

        target_type = 'user' if target_user is not None else 'product'
        unique_target = (report_row['reporter_id'], target_type, target_id)
        if unique_target in seen_targets:
            raise RuntimeError(
                '기존 신고 데이터에 중복 신고가 포함되어 있습니다.'
            )
        seen_targets.add(unique_target)
        migrated_reports.append(
            (
                report_id,
                report_row['reporter_id'],
                target_type,
                target_id if target_type == 'user' else None,
                target_id if target_type == 'product' else None,
                reason,
                migration_time,
            )
        )

    cursor.execute('ALTER TABLE report RENAME TO report_legacy_v1')
    create_report_table(cursor)
    cursor.executemany(
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
        migrated_reports,
    )
    for migrated_report in migrated_reports:
        target_type = migrated_report[2]
        target_id = migrated_report[3] or migrated_report[4]
        add_report_audit_log(
            cursor,
            'report_migrated',
            migrated_report[1],
            target_type,
            target_id,
            migration_time,
        )
    cursor.execute('DROP TABLE report_legacy_v1')


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
                locked_until INTEGER,
                session_version INTEGER NOT NULL DEFAULT 0,
                is_admin INTEGER NOT NULL DEFAULT 0
                    CHECK(
                        typeof(is_admin) = 'integer'
                        AND is_admin IN (0, 1)
                    ),
                account_type TEXT NOT NULL DEFAULT 'user'
                    CHECK(account_type IN ('user', 'business')),
                deleted_at INTEGER
                    CHECK(
                        deleted_at IS NULL
                        OR (
                            typeof(deleted_at) = 'integer'
                            AND deleted_at >= 0
                        )
                    )
            )
        """)
        # 상품 테이블 생성
        create_product_table(cursor)
        add_user_security_columns(cursor)
        migrate_plaintext_passwords(cursor)
        migrate_product_schema(cursor)
        ensure_product_indexes(cursor)
        ensure_moderation_schema(cursor)
        create_admin_role_audit_table(cursor)
        create_business_role_audit_table(cursor)
        ensure_transfer_schema(cursor)
        ensure_purchase_order_schema(cursor)
        ensure_direct_message_schema(cursor)
        create_security_rate_limit_table(cursor)
        # 상품 스키마 마이그레이션 이후 신고 외래키를 생성한다.
        create_report_table(cursor)
        create_report_audit_table(cursor)
        migrate_report_schema(cursor)
        migrate_report_audit_schema(cursor)
        create_report_rate_limit_table(cursor)
        create_report_review_table(cursor)
        ensure_report_schema_objects(cursor)
        db.commit()


def normalize_username(value):
    return unicodedata.normalize('NFKC', value.strip())


def escape_like_query(value):
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def validate_username(username):
    if not USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH:
        return f'사용자명은 {USERNAME_MIN_LENGTH}~{USERNAME_MAX_LENGTH}자여야 합니다.'
    if re.fullmatch(r'[A-Za-z0-9_.-]+', username) is None:
        return (
            '사용자명에는 영문자, ASCII 숫자, 밑줄, 마침표, '
            '하이픈만 사용할 수 있습니다.'
        )
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
    if password.casefold() in {
        common_password.casefold()
        for common_password in COMMON_PASSWORDS
    }:
        return '추측하기 쉬운 비밀번호는 사용할 수 없습니다.'
    return None


def validate_bio(bio):
    if len(bio) > BIO_MAX_LENGTH:
        return f'소개글은 {BIO_MAX_LENGTH}자 이하여야 합니다.'
    if any(
        unicodedata.category(character).startswith('C')
        and character not in {'\n', '\t'}
        for character in bio
    ):
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
    if any(
        unicodedata.category(character).startswith('C')
        and character not in {'\n', '\t'}
        for character in description
    ):
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


def report_reason_contains_sensitive_data(reason):
    return any(
        pattern.search(reason)
        for pattern in (
            REPORT_EMAIL_PATTERN,
            REPORT_PHONE_PATTERN,
            REPORT_RESIDENT_ID_PATTERN,
        )
    )


def validate_report_reason(raw_reason):
    reason = unicodedata.normalize(
        'NFKC',
        raw_reason.replace('\r\n', '\n').replace('\r', '\n').strip(),
    )
    if not REPORT_REASON_MIN_LENGTH <= len(reason) <= REPORT_REASON_MAX_LENGTH:
        return None, (
            f'신고 사유는 {REPORT_REASON_MIN_LENGTH}~'
            f'{REPORT_REASON_MAX_LENGTH}자여야 합니다.'
        )
    if any(
        unicodedata.category(character).startswith('C')
        and character not in {'\n', '\t'}
        for character in reason
    ):
        return None, '신고 사유에 허용되지 않는 문자가 포함되어 있습니다.'
    if report_reason_contains_sensitive_data(reason):
        return None, REPORT_SENSITIVE_DATA_ERROR
    return reason, None


def validate_moderation_reason(raw_reason):
    reason = unicodedata.normalize(
        'NFKC',
        raw_reason.replace('\r\n', '\n').replace('\r', '\n').strip(),
    )
    if not (
        MODERATION_REASON_MIN_LENGTH
        <= len(reason)
        <= MODERATION_REASON_MAX_LENGTH
    ):
        return None, (
            f'관리 사유는 {MODERATION_REASON_MIN_LENGTH}~'
            f'{MODERATION_REASON_MAX_LENGTH}자여야 합니다.'
        )
    if any(
        unicodedata.category(character).startswith('C')
        and character not in {'\n', '\t'}
        for character in reason
    ):
        return None, '관리 사유에 허용되지 않는 문자가 포함되어 있습니다.'
    if report_reason_contains_sensitive_data(reason):
        return None, '관리 사유에 개인정보를 입력할 수 없습니다.'
    return reason, None


def validate_transfer_input(
    raw_recipient_username,
    raw_amount,
    raw_memo,
):
    recipient_username = normalize_username(raw_recipient_username)
    if validate_username(recipient_username):
        return None, None, None, '받는 사용자명을 확인해주세요.'

    amount_text = raw_amount.strip()
    if (
        re.fullmatch(r'[1-9][0-9]*', amount_text) is None
        or len(amount_text) > len(str(TRANSFER_MAX_AMOUNT))
    ):
        return None, None, None, (
            f'송금액은 {TRANSFER_MIN_AMOUNT:,}원 이상 '
            f'{TRANSFER_MAX_AMOUNT:,}원 이하의 정수여야 합니다.'
        )
    amount = int(amount_text)
    if not TRANSFER_MIN_AMOUNT <= amount <= TRANSFER_MAX_AMOUNT:
        return None, None, None, (
            f'송금액은 {TRANSFER_MIN_AMOUNT:,}원 이상 '
            f'{TRANSFER_MAX_AMOUNT:,}원 이하여야 합니다.'
        )

    memo = unicodedata.normalize('NFKC', raw_memo.strip())
    if len(memo) > TRANSFER_MEMO_MAX_LENGTH:
        return None, None, None, (
            f'송금 메모는 {TRANSFER_MEMO_MAX_LENGTH}자 이하여야 합니다.'
        )
    if any(
        unicodedata.category(character).startswith('C')
        for character in memo
    ):
        return None, None, None, (
            '송금 메모에 허용되지 않는 문자가 포함되어 있습니다.'
        )
    if memo and report_reason_contains_sensitive_data(memo):
        return None, None, None, (
            '송금 메모에 이메일, 전화번호 또는 주민등록번호를 입력할 수 없습니다.'
        )
    return recipient_username, amount, memo, None


def get_wallet_balance(cursor, user_id):
    balance_expression = wallet_balance_sql(':user_id')
    row = cursor.execute(
        f'SELECT {balance_expression} AS balance',
        {'user_id': user_id},
    ).fetchone()
    return row['balance']


def add_admin_action_audit(
    cursor,
    action_type,
    admin_id,
    reason,
    created_at,
    target_user_id=None,
    target_product_id=None,
):
    admin = cursor.execute(
        'SELECT username FROM user WHERE id = ?',
        (admin_id,),
    ).fetchone()
    if target_user_id is not None:
        target = cursor.execute(
            'SELECT username AS label FROM user WHERE id = ?',
            (target_user_id,),
        ).fetchone()
    else:
        target = cursor.execute(
            'SELECT title AS label FROM product WHERE id = ?',
            (target_product_id,),
        ).fetchone()
    if admin is None or target is None:
        raise sqlite3.IntegrityError('invalid admin audit target')
    cursor.execute(
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            str(uuid.uuid4()),
            admin_id,
            action_type,
            target_user_id,
            target_product_id,
            reason,
            admin['username'],
            target['label'],
            created_at,
        ),
    )


def get_client_ip_hash():
    raw_address = request.remote_addr or 'unknown'
    try:
        normalized_address = ipaddress.ip_address(raw_address).compressed
    except ValueError:
        normalized_address = 'unknown'
    return hmac.new(
        app.config['SECRET_KEY'].encode('utf-8'),
        normalized_address.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def consume_security_rate_limit(
    cursor,
    scope_type,
    scope_key,
    maximum_attempts,
    window_seconds,
    now,
):
    cursor.execute(
        '''
        DELETE FROM security_rate_limit
        WHERE window_started_at < ?
        ''',
        (now - RATE_LIMIT_RETENTION_SECONDS,),
    )
    row = cursor.execute(
        '''
        SELECT window_started_at, attempt_count
        FROM security_rate_limit
        WHERE scope_type = ? AND scope_key = ?
        ''',
        (scope_type, scope_key),
    ).fetchone()
    if row is None:
        cursor.execute(
            '''
            INSERT INTO security_rate_limit (
                scope_type,
                scope_key,
                window_started_at,
                attempt_count
            )
            VALUES (?, ?, ?, 1)
            ''',
            (scope_type, scope_key, now),
        )
        return True
    window_expired = (
        now - row['window_started_at'] >= window_seconds
        or now < row['window_started_at']
    )
    if window_expired:
        cursor.execute(
            '''
            UPDATE security_rate_limit
            SET window_started_at = ?, attempt_count = 1
            WHERE scope_type = ? AND scope_key = ?
            ''',
            (now, scope_type, scope_key),
        )
        return True
    if row['attempt_count'] >= maximum_attempts:
        return False
    cursor.execute(
        '''
        UPDATE security_rate_limit
        SET attempt_count = attempt_count + 1
        WHERE scope_type = ? AND scope_key = ?
        ''',
        (scope_type, scope_key),
    )
    return True


def reset_security_rate_limit(cursor, scope_type, scope_key):
    cursor.execute(
        '''
        DELETE FROM security_rate_limit
        WHERE scope_type = ? AND scope_key = ?
        ''',
        (scope_type, scope_key),
    )


def consume_report_rate_limit(
    cursor,
    scope_type,
    scope_key,
    maximum_attempts,
    now,
):
    cursor.execute(
        '''
        DELETE FROM report_rate_limit
        WHERE window_started_at < ?
        ''',
        (now - RATE_LIMIT_RETENTION_SECONDS,),
    )
    row = cursor.execute(
        '''
        SELECT window_started_at, attempt_count, blocked_logged
        FROM report_rate_limit
        WHERE scope_type = ? AND scope_key = ?
        ''',
        (scope_type, scope_key),
    ).fetchone()
    if row is None:
        cursor.execute(
            '''
            INSERT INTO report_rate_limit (
                scope_type,
                scope_key,
                window_started_at,
                attempt_count,
                blocked_logged
            )
            VALUES (?, ?, ?, 1, 0)
            ''',
            (scope_type, scope_key, now),
        )
        return True, False

    window_expired = (
        now - row['window_started_at'] >= REPORT_ATTEMPT_WINDOW_SECONDS
        or now < row['window_started_at']
    )
    if window_expired:
        cursor.execute(
            '''
            UPDATE report_rate_limit
            SET window_started_at = ?, attempt_count = 1, blocked_logged = 0
            WHERE scope_type = ? AND scope_key = ?
            ''',
            (now, scope_type, scope_key),
        )
        return True, False

    if row['attempt_count'] >= maximum_attempts:
        should_log = row['blocked_logged'] == 0
        if should_log:
            cursor.execute(
                '''
                UPDATE report_rate_limit
                SET blocked_logged = 1
                WHERE scope_type = ? AND scope_key = ?
                ''',
                (scope_type, scope_key),
            )
        return False, should_log

    cursor.execute(
        '''
        UPDATE report_rate_limit
        SET attempt_count = attempt_count + 1
        WHERE scope_type = ? AND scope_key = ?
        ''',
        (scope_type, scope_key),
    )
    return True, False


def validate_report_input(
    raw_target_type,
    raw_target_id,
    raw_reason,
    reporter_id,
    db,
):
    target_type = raw_target_type.strip().lower()
    if target_type not in {'user', 'product'}:
        return None, '신고 대상을 확인해주세요.'

    target_id_text = raw_target_id.strip()
    try:
        target_id = str(uuid.UUID(target_id_text))
    except (ValueError, AttributeError):
        return None, '신고 대상을 확인해주세요.'
    if len(target_id_text) != 36 or target_id != target_id_text.lower():
        return None, '신고 대상을 확인해주세요.'

    reason, reason_error = validate_report_reason(raw_reason)
    if reason_error:
        return None, reason_error

    target_user_id = None
    target_product_id = None
    if target_type == 'user':
        target_user = db.execute(
            '''
            SELECT id
            FROM user
            WHERE
                id = ?
                AND deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM user_dormancy
                    WHERE user_dormancy.user_id = user.id
                )
            ''',
            (target_id,),
        ).fetchone()
        if target_user is None or target_user['id'] == reporter_id:
            return None, '신고 대상을 확인해주세요.'
        target_user_id = target_id
    else:
        target_product = db.execute(
            '''
            SELECT product.id, product.seller_id
            FROM product
            JOIN user AS seller ON seller.id = product.seller_id
            WHERE
                product.id = ?
                AND seller.deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM user_dormancy
                    WHERE user_dormancy.user_id = seller.id
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM product_moderation
                    WHERE product_moderation.product_id = product.id
                )
            ''',
            (target_id,),
        ).fetchone()
        if target_product is None or target_product['seller_id'] == reporter_id:
            return None, '신고 대상을 확인해주세요.'
        target_product_id = target_id

    return {
        'target_type': target_type,
        'target_id': target_id,
        'target_user_id': target_user_id,
        'target_product_id': target_product_id,
        'reason': reason,
    }, None


def generate_csrf_token():
    token = session.get(CSRF_SESSION_KEY)
    if token is None:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


app.jinja_env.globals['csrf_token'] = generate_csrf_token


def get_csp_nonce():
    return g.csp_nonce


app.jinja_env.globals['csp_nonce'] = get_csp_nonce


@app.before_request
def prepare_request_security():
    g.csp_nonce = secrets.token_urlsafe(18)


@app.after_request
def apply_security_headers(response):
    nonce = getattr(g, 'csp_nonce', None) or secrets.token_urlsafe(18)
    content_security_policy = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}' https://cdnjs.cloudflare.com; "
        f"style-src 'self' 'nonce-{nonce}'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    response.headers['Content-Security-Policy'] = content_security_policy
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = (
        'camera=(), microphone=(), geolocation=()'
    )
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = (
            'max-age=31536000; includeSubDomains'
        )
    return response


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


def session_timestamps_are_valid(now):
    authenticated_at = session.get('authenticated_at')
    last_activity = session.get('last_activity')
    return (
        isinstance(authenticated_at, int)
        and isinstance(last_activity, int)
        and 0 <= now - authenticated_at <= SESSION_ABSOLUTE_SECONDS
        and 0 <= now - last_activity <= SESSION_IDLE_SECONDS
    )


@app.before_request
def load_and_validate_session():
    g.current_user = None
    user_id = session.get('user_id')
    if user_id is None:
        return None

    now = int(time.time())
    if not session_timestamps_are_valid(now):
        session.clear()
        flash('세션이 만료되었습니다. 다시 로그인해주세요.')
        return redirect(url_for('login'))

    db = get_db()
    g.current_user = db.execute(
        '''
        SELECT *
        FROM user
        WHERE
            id = ?
            AND deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM user_dormancy
                WHERE user_dormancy.user_id = user.id
            )
        ''',
        (user_id,),
    ).fetchone()
    session_version = session.get('session_version', 0)
    if (
        g.current_user is None
        or not isinstance(session_version, int)
        or session_version != g.current_user['session_version']
    ):
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


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.current_user is None:
            return redirect(url_for('login'))
        if g.current_user['is_admin'] != 1:
            abort(403)
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
        '''
        SELECT product.*
        FROM product
        JOIN user AS seller ON seller.id = product.seller_id
        WHERE
            product.id = ?
            AND seller.deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM user_dormancy
                WHERE user_dormancy.user_id = seller.id
            )
            AND NOT EXISTS (
                SELECT 1
                FROM product_moderation
                WHERE product_moderation.product_id = product.id
            )
        ''',
        (normalized_product_id,),
    ).fetchone()
    if product is None:
        abort(404)
    return product


def require_product_owner(product):
    if g.current_user is None or product['seller_id'] != g.current_user['id']:
        abort(403)


def normalize_uuid_identifier(value):
    if not isinstance(value, str):
        return None
    try:
        normalized_value = str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return None
    if normalized_value != value.lower():
        return None
    return normalized_value


def get_page_number(parameter='page'):
    raw_page = request.args.get(parameter, '1')
    if re.fullmatch(r'[1-9][0-9]*', raw_page) is None:
        abort(400)
    page = int(raw_page)
    if page > MAX_PAGE_NUMBER:
        abort(400)
    return page


def build_pagination(total_items, page, page_size=PAGE_SIZE):
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    if page > total_pages and total_items:
        abort(404)
    return {
        'page': page,
        'page_size': page_size,
        'total_items': total_items,
        'total_pages': total_pages,
        'has_previous': page > 1,
        'has_next': page < total_pages,
    }


def verify_sensitive_password(candidate):
    if len(candidate) > PASSWORD_MAX_LENGTH:
        return False
    now = int(time.time())
    db = get_db()
    cursor = db.cursor()
    user_key = g.current_user['id']
    ip_key = get_client_ip_hash()
    user_allowed = consume_security_rate_limit(
        cursor,
        'reauth_user',
        user_key,
        REAUTH_RATE_LIMIT,
        REAUTH_RATE_WINDOW_SECONDS,
        now,
    )
    ip_allowed = consume_security_rate_limit(
        cursor,
        'reauth_ip',
        ip_key,
        REAUTH_RATE_LIMIT,
        REAUTH_RATE_WINDOW_SECONDS,
        now,
    )
    if not user_allowed or not ip_allowed:
        db.commit()
        abort(429)
    if not verify_password(g.current_user['password'], candidate):
        db.commit()
        return False
    reset_security_rate_limit(cursor, 'reauth_user', user_key)
    reset_security_rate_limit(cursor, 'reauth_ip', ip_key)
    db.commit()
    session['sensitive_authenticated_at'] = now
    return True


def enforce_admin_action_authorization():
    now = int(time.time())
    submitted_password = request.form.get('current_password', '')
    recent_authentication = session.get(
        'sensitive_authenticated_at',
        session.get('authenticated_at'),
    )
    recent_authentication_is_valid = (
        isinstance(recent_authentication, int)
        and now >= recent_authentication
        and now - recent_authentication <= ADMIN_RECENT_AUTH_SECONDS
    )
    if submitted_password:
        if not verify_sensitive_password(submitted_password):
            flash('현재 비밀번호가 올바르지 않습니다.')
            return False
    elif not recent_authentication_is_valid:
        flash('관리 작업을 계속하려면 현재 비밀번호를 확인해주세요.')
        return False
    db = get_db()
    allowed = consume_security_rate_limit(
        db.cursor(),
        'admin_user',
        g.current_user['id'],
        ADMIN_ACTION_RATE_LIMIT,
        ADMIN_ACTION_RATE_WINDOW_SECONDS,
        now,
    )
    db.commit()
    if not allowed:
        abort(429)
    return True


def users_are_blocked(first_user_id, second_user_id):
    return get_db().execute(
        '''
        SELECT 1
        FROM user_block
        WHERE
            (blocker_id = ? AND blocked_id = ?)
            OR (blocker_id = ? AND blocked_id = ?)
        ''',
        (
            first_user_id,
            second_user_id,
            second_user_id,
            first_user_id,
        ),
    ).fetchone() is not None


def get_chat_recipient_or_404(recipient_id):
    normalized_recipient_id = normalize_uuid_identifier(recipient_id)
    if normalized_recipient_id is None:
        abort(404)
    recipient = get_db().execute(
        '''
        SELECT id, username
        FROM user
        WHERE
            id = ?
            AND deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM user_dormancy
                WHERE user_dormancy.user_id = user.id
            )
        ''',
        (normalized_recipient_id,),
    ).fetchone()
    if recipient is None or recipient['id'] == g.current_user['id']:
        abort(404)
    return recipient


# 기본 라우트
@app.route('/')
def index():
    if g.current_user is not None:
        return redirect(url_for('dashboard'))
    return redirect(url_for('products'))

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
    now = int(time.time())
    registration_allowed = consume_security_rate_limit(
        cursor,
        'register_ip',
        get_client_ip_hash(),
        REGISTER_IP_RATE_LIMIT,
        REGISTER_RATE_WINDOW_SECONDS,
        now,
    )
    db.commit()
    if not registration_allowed:
        abort(429)
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
    source_ip_hash = get_client_ip_hash()
    now = int(time.time())
    login_allowed = consume_security_rate_limit(
        cursor,
        'login_ip',
        source_ip_hash,
        LOGIN_IP_RATE_LIMIT,
        LOGIN_RATE_WINDOW_SECONDS,
        now,
    )
    if not login_allowed:
        db.commit()
        abort(429)
    cursor.execute(
        '''
        SELECT *
        FROM user
        WHERE
            username = ?
            AND deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM user_dormancy
                WHERE user_dormancy.user_id = user.id
            )
        ''',
        (username,),
    )
    user = cursor.fetchone()

    if user is None:
        verify_password(DUMMY_PASSWORD_HASH, password)
        db.commit()
        flash('아이디 또는 비밀번호가 올바르지 않습니다.')
        return redirect(url_for('login'))

    password_is_valid = verify_password(user['password'], password)
    if not password_is_valid:
        if user['locked_until'] is None or user['locked_until'] <= now:
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
    session['session_version'] = user['session_version']
    session['authenticated_at'] = now
    session['last_activity'] = now
    session['sensitive_authenticated_at'] = now
    flash('로그인 성공!')
    return redirect(url_for('dashboard'))


# 로그아웃
@app.route('/logout', methods=['POST'])
@csrf_protected
def logout():
    session.clear()
    flash('로그아웃되었습니다.')
    return redirect(url_for('index'))

# 공개 상품 목록
@app.route('/products')
def products():
    page = get_page_number()
    db = get_db()
    search_query = unicodedata.normalize(
        'NFKC',
        request.args.get('q', ''),
    ).strip()[:PRODUCT_SEARCH_MAX_LENGTH]
    product_filter = '''
        FROM product
        JOIN user AS seller ON seller.id = product.seller_id
        WHERE
            seller.deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM user_dormancy
                WHERE user_dormancy.user_id = seller.id
            )
            AND NOT EXISTS (
                SELECT 1
                FROM product_moderation
                WHERE product_moderation.product_id = product.id
            )
            AND NOT EXISTS (
                SELECT 1
                FROM purchase_order
                WHERE purchase_order.product_id = product.id
            )
    '''
    filter_params = []
    if search_query:
        search_pattern = f'%{escape_like_query(search_query)}%'
        product_filter += '''
            AND (
                product.title LIKE ? ESCAPE '\\'
                OR product.description LIKE ? ESCAPE '\\'
            )
        '''
        filter_params.extend((search_pattern, search_pattern))
    total_items = db.execute(
        f'SELECT COUNT(*) {product_filter}',
        filter_params,
    ).fetchone()[0]
    pagination = build_pagination(total_items, page)
    public_products = db.execute(
        f'''
        SELECT
            product.id,
            product.title,
            product.price,
            seller.username AS seller_username
        {product_filter}
        ORDER BY product.title, product.id
        LIMIT ? OFFSET ?
        ''',
        (*filter_params, PAGE_SIZE, (page - 1) * PAGE_SIZE),
    ).fetchall()
    return render_template(
        'products.html',
        products=public_products,
        pagination=pagination,
        search_query=search_query,
    )


# 대시보드: 로그인 사용자 정보와 공개 상품 리스트 표시
@app.route('/dashboard')
@login_required
def dashboard():
    page = get_page_number()
    db = get_db()
    product_filter = '''
        FROM product
        JOIN user AS seller ON seller.id = product.seller_id
        WHERE
            seller.deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM user_dormancy
                WHERE user_dormancy.user_id = seller.id
            )
            AND NOT EXISTS (
                SELECT 1
                FROM product_moderation
                WHERE product_moderation.product_id = product.id
            )
            AND NOT EXISTS (
                SELECT 1
                FROM purchase_order
                WHERE purchase_order.product_id = product.id
            )
    '''
    total_items = db.execute(
        f'SELECT COUNT(*) {product_filter}'
    ).fetchone()[0]
    pagination = build_pagination(total_items, page)
    public_products = db.execute(
        f'''
        SELECT product.id, product.title, product.price
        {product_filter}
        ORDER BY product.title, product.id
        LIMIT ? OFFSET ?
        ''',
        (PAGE_SIZE, (page - 1) * PAGE_SIZE),
    ).fetchall()
    return render_template(
        'dashboard.html',
        products=public_products,
        pagination=pagination,
        user=g.current_user,
    )


@app.route('/transfers', methods=['GET', 'POST'])
@login_required
def transfers():
    if g.current_user['is_admin'] == 1 or g.current_user['account_type'] != 'user':
        abort(403)
    if request.method == 'POST':
        return create_transfer()

    page = get_page_number()
    db = get_db()
    balance = get_wallet_balance(db, g.current_user['id'])
    recipients = db.execute(
        '''
        SELECT id, username
        FROM user
        WHERE
            id <> ?
            AND is_admin = 0
            AND account_type = 'user'
            AND deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM user_dormancy
                WHERE user_dormancy.user_id = user.id
            )
        ORDER BY username, id
        LIMIT ?
        ''',
        (g.current_user['id'], TRANSFER_RECIPIENT_LIMIT),
    ).fetchall()
    transfer_count = db.execute(
        '''
        SELECT COUNT(*)
        FROM money_transfer
        WHERE sender_id = ? OR recipient_id = ?
        ''',
        (g.current_user['id'], g.current_user['id']),
    ).fetchone()[0]
    pagination = build_pagination(transfer_count, page)
    transfer_history = db.execute(
        '''
        SELECT
            id,
            sender_id,
            recipient_id,
            amount,
            memo,
            sender_username_snapshot,
            recipient_username_snapshot,
            created_at
        FROM money_transfer
        WHERE sender_id = ? OR recipient_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        ''',
        (
            g.current_user['id'],
            g.current_user['id'],
            PAGE_SIZE,
            (page - 1) * PAGE_SIZE,
        ),
    ).fetchall()
    return render_template(
        'transfers.html',
        balance=balance,
        recipients=recipients,
        transfer_history=transfer_history,
        transfer_request_id=str(uuid.uuid4()),
        pagination=pagination,
        user_id=g.current_user['id'],
        transfer_max_amount=TRANSFER_MAX_AMOUNT,
        transfer_memo_max_length=TRANSFER_MEMO_MAX_LENGTH,
    )


@csrf_protected
def create_transfer():
    if g.current_user['is_admin'] == 1 or g.current_user['account_type'] != 'user':
        abort(403)
    request_id = normalize_uuid_identifier(
        request.form.get('request_id', '')
    )
    (
        recipient_username,
        amount,
        memo,
        validation_error,
    ) = validate_transfer_input(
        request.form.get('recipient_username', ''),
        request.form.get('amount', ''),
        request.form.get('memo', ''),
    )
    if request_id is None or validation_error:
        flash(validation_error or '송금 요청 정보를 확인해주세요.')
        return redirect(url_for('transfers'))

    db = get_db()
    recipient = db.execute(
        '''
        SELECT id, username
        FROM user
        WHERE
            username = ?
            AND id <> ?
            AND is_admin = 0
            AND account_type = 'user'
            AND deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM user_dormancy
                WHERE user_dormancy.user_id = user.id
            )
        ''',
        (recipient_username, g.current_user['id']),
    ).fetchone()
    if recipient is None:
        flash('받는 사용자를 확인해주세요.')
        return redirect(url_for('transfers'))

    current_password = request.form.get('current_password', '')
    if not verify_sensitive_password(current_password):
        flash('현재 비밀번호가 올바르지 않습니다.')
        return redirect(url_for('transfers'))

    now = int(time.time())
    cursor = db.cursor()
    user_allowed = consume_security_rate_limit(
        cursor,
        'transfer_user',
        g.current_user['id'],
        TRANSFER_USER_RATE_LIMIT,
        TRANSFER_RATE_WINDOW_SECONDS,
        now,
    )
    ip_allowed = consume_security_rate_limit(
        cursor,
        'transfer_ip',
        get_client_ip_hash(),
        TRANSFER_IP_RATE_LIMIT,
        TRANSFER_RATE_WINDOW_SECONDS,
        now,
    )
    db.commit()
    if not user_allowed or not ip_allowed:
        abort(429)

    try:
        db.execute('BEGIN IMMEDIATE')
        recipient = db.execute(
            '''
            SELECT id, username
            FROM user
            WHERE
                id = ?
                AND username = ?
                AND is_admin = 0
                AND account_type = 'user'
                AND deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM user_dormancy
                    WHERE user_dormancy.user_id = user.id
                )
            ''',
            (recipient['id'], recipient_username),
        ).fetchone()
        if recipient is None:
            db.rollback()
            flash('받는 사용자를 확인해주세요.')
            return redirect(url_for('transfers'))

        db.execute(
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
                str(uuid.uuid4()),
                request_id,
                g.current_user['id'],
                recipient['id'],
                amount,
                memo,
                g.current_user['username'],
                recipient['username'],
                now,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError as error:
        db.rollback()
        error_message = str(error)
        if 'money_transfer.request_id' in error_message:
            existing_transfer = db.execute(
                '''
                SELECT sender_id
                FROM money_transfer
                WHERE request_id = ?
                ''',
                (request_id,),
            ).fetchone()
            if (
                existing_transfer is not None
                and existing_transfer['sender_id'] == g.current_user['id']
            ):
                flash('이미 처리된 송금 요청입니다.')
                return redirect(url_for('transfers'))
        if 'insufficient wallet balance' in error_message:
            flash('송금할 수 있는 잔액이 부족합니다.')
            return redirect(url_for('transfers'))
        if 'wallet balance limit exceeded' in error_message:
            flash('받는 사용자의 잔액 한도를 초과합니다.')
            return redirect(url_for('transfers'))
        abort(400)

    flash('송금이 완료되었습니다.')
    return redirect(url_for('transfers'))


# 마이페이지: 로그인한 사용자의 계정 정보 조회와 소개글 업데이트
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
    if not verify_sensitive_password(current_password):
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


@app.route('/profile/password', methods=['POST'])
@login_required
@csrf_protected
def update_password():
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if not verify_sensitive_password(current_password):
        flash('현재 비밀번호가 올바르지 않습니다.')
        return redirect(url_for('profile'))

    validation_error = validate_password(new_password)
    if validation_error:
        flash(validation_error)
        return redirect(url_for('profile'))
    if not hmac.compare_digest(new_password, confirm_password):
        flash('새 비밀번호 확인이 일치하지 않습니다.')
        return redirect(url_for('profile'))
    if verify_password(g.current_user['password'], new_password):
        flash('현재 비밀번호와 다른 새 비밀번호를 사용해주세요.')
        return redirect(url_for('profile'))

    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        '''
        UPDATE user
        SET
            password = ?,
            session_version = session_version + 1,
            failed_login_attempts = 0,
            locked_until = NULL
        WHERE id = ? AND session_version = ?
        ''',
        (
            password_hasher.hash(new_password),
            g.current_user['id'],
            g.current_user['session_version'],
        ),
    )
    if cursor.rowcount != 1:
        db.rollback()
        session.clear()
        abort(403)
    db.commit()

    session.clear()
    flash('비밀번호가 변경되었습니다. 새 비밀번호로 다시 로그인해주세요.')
    return redirect(url_for('login'))


@app.route('/profile/delete', methods=['POST'])
@login_required
@csrf_protected
def delete_account():
    current_password = request.form.get('current_password', '')
    confirmation = request.form.get('confirmation', '')
    if g.current_user['is_admin'] == 1:
        flash('관리자 권한을 해제한 뒤 회원 탈퇴를 진행해주세요.')
        return redirect(url_for('profile'))
    if not verify_sensitive_password(current_password):
        flash('현재 비밀번호가 올바르지 않습니다.')
        return redirect(url_for('profile'))
    if not hmac.compare_digest(
        confirmation.encode('utf-8'),
        ACCOUNT_DELETION_CONFIRMATION.encode('utf-8'),
    ):
        flash(f'확인 문구로 {ACCOUNT_DELETION_CONFIRMATION}를 입력해주세요.')
        return redirect(url_for('profile'))

    user_id = g.current_user['id']
    db = get_db()
    if get_wallet_balance(db, user_id) != 0:
        flash('회원 탈퇴 전에 학습용 잔액을 모두 송금해주세요.')
        return redirect(url_for('profile'))

    anonymized_username = f'deleted-{user_id}'
    disabled_password = password_hasher.hash(secrets.token_urlsafe(48))
    deleted_at = int(time.time())
    cursor = db.execute(
        '''
        UPDATE user
        SET
            username = ?,
            password = ?,
            bio = NULL,
            failed_login_attempts = 0,
            locked_until = NULL,
            session_version = session_version + 1,
            deleted_at = ?
        WHERE
            id = ?
            AND session_version = ?
            AND deleted_at IS NULL
        ''',
        (
            anonymized_username,
            disabled_password,
            deleted_at,
            user_id,
            g.current_user['session_version'],
        ),
    )
    if cursor.rowcount != 1:
        db.rollback()
        session.clear()
        abort(403)
    db.commit()

    disconnect_user_sockets(user_id)
    session.clear()
    flash('회원 탈퇴가 완료되었습니다.')
    return redirect(url_for('products'))


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
    cursor = db.cursor()
    now = int(time.time())
    creation_allowed = consume_security_rate_limit(
        cursor,
        'product_user',
        g.current_user['id'],
        PRODUCT_CREATE_RATE_LIMIT,
        PRODUCT_CREATE_RATE_WINDOW_SECONDS,
        now,
    )
    product_count = cursor.execute(
        'SELECT COUNT(*) FROM product WHERE seller_id = ?',
        (g.current_user['id'],),
    ).fetchone()[0]
    db.commit()
    if not creation_allowed or product_count >= MAX_PRODUCTS_PER_USER:
        abort(429)
    product_id = str(uuid.uuid4())
    try:
        cursor.execute(
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


# 등록 상품 관리
@app.route('/products/manage')
@login_required
def manage_products():
    page = get_page_number()
    db = get_db()
    product_filter = '''
        FROM product
        WHERE
            seller_id = ?
            AND NOT EXISTS (
                SELECT 1
                FROM product_moderation
                WHERE product_moderation.product_id = product.id
            )
    '''
    total_items = db.execute(
        f'SELECT COUNT(*) {product_filter}',
        (g.current_user['id'],),
    ).fetchone()[0]
    pagination = build_pagination(total_items, page)
    products = db.execute(
        f'''
        SELECT id, title, description, price, seller_id
        {product_filter}
        ORDER BY title, id
        LIMIT ? OFFSET ?
        ''',
        (
            g.current_user['id'],
            PAGE_SIZE,
            (page - 1) * PAGE_SIZE,
        ),
    ).fetchall()
    return render_template(
        'manage_products.html',
        products=products,
        pagination=pagination,
    )


# 상품 상세보기
@app.route('/product/<product_id>')
def view_product(product_id):
    db = get_db()
    product = get_product_or_404(product_id)
    # 판매자 정보 조회
    seller = db.execute(
        '''
        SELECT id, username
        FROM user
        WHERE
            id = ?
            AND deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM user_dormancy
                WHERE user_dormancy.user_id = user.id
            )
        ''',
        (product['seller_id'],),
    ).fetchone()
    sold_order = db.execute(
        '''
        SELECT id, buyer_username_snapshot, amount, created_at
        FROM purchase_order
        WHERE product_id = ?
        ''',
        (product['id'],),
    ).fetchone()
    balance = None
    if (
        g.current_user is not None
        and g.current_user['is_admin'] == 0
        and g.current_user['account_type'] == 'user'
    ):
        balance = get_wallet_balance(db, g.current_user['id'])
    return render_template(
        'view_product.html',
        product=product,
        seller=seller,
        sold_order=sold_order,
        balance=balance,
    )


@app.route('/product/<product_id>/purchase', methods=['POST'])
@login_required
@csrf_protected
def purchase_product(product_id):
    if g.current_user['is_admin'] == 1 or g.current_user['account_type'] != 'user':
        abort(403)
    if not verify_sensitive_password(
        request.form.get('current_password', '')
    ):
        flash('현재 비밀번호가 올바르지 않습니다.')
        return redirect(url_for('view_product', product_id=product_id))

    try:
        normalized_product_id = str(uuid.UUID(product_id))
    except (ValueError, AttributeError):
        abort(404)
    if normalized_product_id != product_id.lower():
        abort(404)

    db = get_db()
    now = int(time.time())
    cursor = db.cursor()
    user_allowed = consume_security_rate_limit(
        cursor,
        'transfer_user',
        g.current_user['id'],
        TRANSFER_USER_RATE_LIMIT,
        TRANSFER_RATE_WINDOW_SECONDS,
        now,
    )
    ip_allowed = consume_security_rate_limit(
        cursor,
        'transfer_ip',
        get_client_ip_hash(),
        TRANSFER_IP_RATE_LIMIT,
        TRANSFER_RATE_WINDOW_SECONDS,
        now,
    )
    db.commit()
    if not user_allowed or not ip_allowed:
        abort(429)

    try:
        db.execute('BEGIN IMMEDIATE')
        product = db.execute(
            '''
            SELECT
                product.id,
                product.title,
                product.price,
                product.seller_id,
                seller.username AS seller_username
            FROM product
            JOIN user AS seller ON seller.id = product.seller_id
            WHERE
                product.id = ?
                AND product.seller_id <> ?
                AND product.price >= ?
                AND seller.is_admin = 0
                AND seller.deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM user_dormancy
                    WHERE user_dormancy.user_id = seller.id
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM product_moderation
                    WHERE product_moderation.product_id = product.id
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM purchase_order
                    WHERE purchase_order.product_id = product.id
                )
            ''',
            (
                normalized_product_id,
                g.current_user['id'],
                TRANSFER_MIN_AMOUNT,
            ),
        ).fetchone()
        if product is None:
            db.rollback()
            flash('구매할 수 없는 상품입니다.')
            return redirect(url_for('products'))

        transfer_request_id = str(uuid.uuid4())
        db.execute(
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
                str(uuid.uuid4()),
                transfer_request_id,
                g.current_user['id'],
                product['seller_id'],
                product['price'],
                '상품 구매',
                g.current_user['username'],
                product['seller_username'],
                now,
            ),
        )
        db.execute(
            '''
            INSERT INTO purchase_order (
                id,
                product_id,
                buyer_id,
                seller_id,
                transfer_request_id,
                amount,
                status,
                product_title_snapshot,
                buyer_username_snapshot,
                seller_username_snapshot,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'paid', ?, ?, ?, ?)
            ''',
            (
                str(uuid.uuid4()),
                product['id'],
                g.current_user['id'],
                product['seller_id'],
                transfer_request_id,
                product['price'],
                product['title'],
                g.current_user['username'],
                product['seller_username'],
                now,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError as error:
        db.rollback()
        if 'insufficient wallet balance' in str(error):
            flash('상품 가격보다 학습용 잔액이 부족합니다.')
            return redirect(url_for('view_product', product_id=product_id))
        if 'purchase_order.product_id' in str(error):
            flash('이미 판매된 상품입니다.')
            return redirect(url_for('products'))
        abort(400)

    flash('구매가 완료되었습니다. 주문 내역에서 확인할 수 있습니다.')
    return redirect(url_for('orders'))


@app.route('/orders')
@login_required
def orders():
    if g.current_user['is_admin'] == 1:
        abort(403)
    db = get_db()
    order_rows = db.execute(
        '''
        SELECT
            id,
            product_title_snapshot,
            amount,
            status,
            buyer_id,
            buyer_username_snapshot,
            seller_username_snapshot,
            created_at
        FROM purchase_order
        WHERE buyer_id = ? OR seller_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        ''',
        (
            g.current_user['id'],
            g.current_user['id'],
            ORDER_HISTORY_LIMIT,
        ),
    ).fetchall()
    return render_template(
        'orders.html',
        orders=order_rows,
        user_id=g.current_user['id'],
    )


@app.route('/product/<product_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product = get_product_or_404(product_id)
    require_product_owner(product)
    if get_db().execute(
        'SELECT 1 FROM purchase_order WHERE product_id = ?',
        (product['id'],),
    ).fetchone() is not None:
        flash('판매 완료 상품은 수정할 수 없습니다.')
        return redirect(url_for('view_product', product_id=product['id']))
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
            WHERE
                id = ?
                AND seller_id = ?
                AND NOT EXISTS (
                    SELECT 1
                    FROM product_moderation
                    WHERE product_moderation.product_id = product.id
                )
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
    try:
        cursor = db.execute(
            'DELETE FROM product WHERE id = ? AND seller_id = ?',
            (product['id'], g.current_user['id']),
        )
        if cursor.rowcount != 1:
            db.rollback()
            abort(404)
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        flash('현재 상품을 삭제할 수 없습니다.')
        return redirect(url_for('view_product', product_id=product['id']))

    flash('상품이 삭제되었습니다.')
    return redirect(url_for('manage_products'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    db = get_db()
    product_page = get_page_number('product_page')
    user_page = get_page_number('user_page')
    report_page = get_page_number('report_page')
    audit_page = get_page_number('audit_page')
    product_count = db.execute(
        '''
        SELECT COUNT(*)
        FROM product
        JOIN user AS seller ON seller.id = product.seller_id
        WHERE
            seller.deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM product_moderation
                WHERE product_moderation.product_id = product.id
            )
        '''
    ).fetchone()[0]
    product_pagination = build_pagination(product_count, product_page)
    products = db.execute(
        '''
        WITH report_counts AS (
            SELECT target_product_id, COUNT(*) AS report_count
            FROM report
            WHERE target_type = 'product'
            GROUP BY target_product_id
        )
        SELECT
            product.id,
            product.title,
            product.price,
            seller.username AS seller_username,
            EXISTS (
                SELECT 1
                FROM user_dormancy
                WHERE user_dormancy.user_id = seller.id
            ) AS seller_is_dormant,
            COALESCE(report_counts.report_count, 0) AS report_count
        FROM product
        JOIN user AS seller ON seller.id = product.seller_id
        LEFT JOIN report_counts
            ON report_counts.target_product_id = product.id
        WHERE
            seller.deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM product_moderation
                WHERE product_moderation.product_id = product.id
            )
        ORDER BY report_count DESC, product.title, product.id
        LIMIT ? OFFSET ?
        ''',
        (PAGE_SIZE, (product_page - 1) * PAGE_SIZE),
    ).fetchall()
    user_count = db.execute(
        'SELECT COUNT(*) FROM user WHERE deleted_at IS NULL'
    ).fetchone()[0]
    user_pagination = build_pagination(user_count, user_page)
    users = db.execute(
        '''
        WITH report_counts AS (
            SELECT target_user_id, COUNT(*) AS report_count
            FROM report
            WHERE target_type = 'user'
            GROUP BY target_user_id
        )
        SELECT
            user.id,
            user.username,
            user.is_admin,
            user.account_type,
            user_dormancy.created_at AS dormant_at,
            user_dormancy.reason AS dormant_reason,
            COALESCE(report_counts.report_count, 0) AS report_count
        FROM user
        LEFT JOIN user_dormancy ON user_dormancy.user_id = user.id
        LEFT JOIN report_counts ON report_counts.target_user_id = user.id
        WHERE user.deleted_at IS NULL
        ORDER BY report_count DESC, user.username, user.id
        LIMIT ? OFFSET ?
        ''',
        (PAGE_SIZE, (user_page - 1) * PAGE_SIZE),
    ).fetchall()
    report_count = db.execute('SELECT COUNT(*) FROM report').fetchone()[0]
    report_pagination = build_pagination(report_count, report_page)
    reports = db.execute(
        '''
        SELECT
            report.id,
            report.target_type,
            report.reason,
            report.created_at,
            reporter.username AS reporter_username,
            target_user.username AS target_username,
            target_product.title AS target_product_title,
            COALESCE(report_review.status, 'pending') AS review_status,
            report_review.note AS review_note,
            report_review.reviewed_at,
            report_review.admin_username_snapshot AS reviewer_username
        FROM report
        JOIN user AS reporter ON reporter.id = report.reporter_id
        LEFT JOIN user AS target_user
            ON target_user.id = report.target_user_id
        LEFT JOIN product AS target_product
            ON target_product.id = report.target_product_id
        LEFT JOIN report_review ON report_review.report_id = report.id
        ORDER BY
            CASE WHEN report_review.report_id IS NULL THEN 0 ELSE 1 END,
            report.created_at DESC,
            report.id DESC
        LIMIT ? OFFSET ?
        ''',
        (PAGE_SIZE, (report_page - 1) * PAGE_SIZE),
    ).fetchall()
    audit_count = db.execute(
        'SELECT COUNT(*) FROM admin_action_audit'
    ).fetchone()[0]
    audit_pagination = build_pagination(audit_count, audit_page)
    audit_events = db.execute(
        '''
        SELECT
            admin_action_audit.id,
            admin_action_audit.action_type,
            admin_action_audit.reason,
            admin_action_audit.created_at,
            admin_action_audit.admin_username_snapshot AS admin_username,
            CASE
                WHEN admin_action_audit.target_user_id IS NOT NULL
                THEN admin_action_audit.target_label_snapshot
            END AS target_username,
            CASE
                WHEN admin_action_audit.target_product_id IS NOT NULL
                THEN admin_action_audit.target_label_snapshot
            END AS target_product_title
        FROM admin_action_audit
        ORDER BY
            admin_action_audit.created_at DESC,
            admin_action_audit.id DESC
        LIMIT ? OFFSET ?
        ''',
        (PAGE_SIZE, (audit_page - 1) * PAGE_SIZE),
    ).fetchall()
    return render_template(
        'admin_dashboard.html',
        products=products,
        users=users,
        reports=reports,
        audit_events=audit_events,
        product_pagination=product_pagination,
        user_pagination=user_pagination,
        report_pagination=report_pagination,
        audit_pagination=audit_pagination,
    )


@app.route('/admin/users/<user_id>/business', methods=['POST'])
@admin_required
@csrf_protected
def admin_set_business_role(user_id):
    normalized_user_id = normalize_uuid_identifier(user_id)
    if normalized_user_id is None:
        abort(404)
    action = request.form.get('action', '').strip().lower()
    if action not in {'grant', 'revoke'}:
        abort(400)
    reason, validation_error = validate_moderation_reason(
        request.form.get('reason', '')
    )
    if validation_error:
        flash(validation_error)
        return redirect(url_for('admin_dashboard'))
    if not enforce_admin_action_authorization():
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    target = db.execute(
        '''
        SELECT id, username, is_admin, account_type, session_version
        FROM user
        WHERE id = ? AND deleted_at IS NULL
        ''',
        (normalized_user_id,),
    ).fetchone()
    if target is None:
        abort(404)
    if target['is_admin'] == 1 or target['id'] == g.current_user['id']:
        abort(403)
    granting = action == 'grant'
    if target['account_type'] == ('business' if granting else 'user'):
        flash('사용자가 이미 요청한 사업자 역할 상태입니다.')
        return redirect(url_for('admin_dashboard'))
    if granting and db.execute(
        'SELECT 1 FROM user_dormancy WHERE user_id = ?', (target['id'],)
    ).fetchone() is not None:
        flash('휴면 사용자는 사업자로 지정할 수 없습니다.')
        return redirect(url_for('admin_dashboard'))
    if get_wallet_balance(db, target['id']) != 0:
        flash('사업자 역할을 변경하려면 학습용 잔액이 0원이어야 합니다.')
        return redirect(url_for('admin_dashboard'))

    now = int(time.time())
    try:
        db.execute(
            '''
            UPDATE user
            SET account_type = ?, session_version = session_version + 1
            WHERE id = ? AND account_type = ?
            ''',
            ('business' if granting else 'user', target['id'],
             'user' if granting else 'business'),
        )
        db.execute(
            '''
            INSERT INTO business_role_audit (
                id, operator_name, target_user_id, target_username_snapshot,
                action_type, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                str(uuid.uuid4()), g.current_user['username'], target['id'],
                target['username'], 'business_granted' if granting else 'business_revoked',
                reason, now,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        abort(400)
    disconnect_user_sockets(target['id'])
    flash('사업자 권한을 부여했습니다.' if granting else '사업자 권한을 해제했습니다.')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/moderation')
@admin_required
def legacy_admin_moderation():
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/products/<product_id>/remove', methods=['POST'])
@admin_required
@csrf_protected
def admin_remove_product(product_id):
    normalized_product_id = normalize_uuid_identifier(product_id)
    if normalized_product_id is None:
        abort(404)
    reason, validation_error = validate_moderation_reason(
        request.form.get('reason', '')
    )
    if validation_error:
        flash(validation_error)
        return redirect(url_for('admin_dashboard'))
    if not enforce_admin_action_authorization():
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    cursor = db.cursor()
    product = cursor.execute(
        '''
        SELECT id, title, description, price, seller_id
        FROM product
        WHERE
            id = ?
            AND NOT EXISTS (
                SELECT 1
                FROM product_moderation
                WHERE product_moderation.product_id = product.id
            )
        ''',
        (normalized_product_id,),
    ).fetchone()
    if product is None:
        abort(404)

    now = int(time.time())
    try:
        cursor.execute(
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
                product['id'],
                g.current_user['id'],
                reason,
                now,
                product['title'],
                product['description'],
                product['price'],
                product['seller_id'],
            ),
        )
        add_admin_action_audit(
            cursor,
            'product_removed',
            g.current_user['id'],
            reason,
            now,
            target_product_id=product['id'],
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        abort(400)

    flash('불량 상품이 관리 삭제되었습니다.')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/users/<user_id>/dormant', methods=['POST'])
@admin_required
@csrf_protected
def admin_dormant_user(user_id):
    normalized_user_id = normalize_uuid_identifier(user_id)
    if normalized_user_id is None:
        abort(404)
    reason, validation_error = validate_moderation_reason(
        request.form.get('reason', '')
    )
    if validation_error:
        flash(validation_error)
        return redirect(url_for('admin_dashboard'))
    if not enforce_admin_action_authorization():
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    cursor = db.cursor()
    target_user = cursor.execute(
        '''
        SELECT id, is_admin
        FROM user
        WHERE id = ? AND deleted_at IS NULL
        ''',
        (normalized_user_id,),
    ).fetchone()
    if target_user is None:
        abort(404)
    if (
        target_user['id'] == g.current_user['id']
        or target_user['is_admin'] == 1
    ):
        abort(403)

    now = int(time.time())
    try:
        update_cursor = cursor.execute(
            '''
            UPDATE user
            SET session_version = session_version + 1
            WHERE
                id = ?
                AND is_admin = 0
                AND deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM user_dormancy
                    WHERE user_dormancy.user_id = user.id
                )
            ''',
            (target_user['id'],),
        )
        if update_cursor.rowcount != 1:
            db.rollback()
            abort(404)
        cursor.execute(
            '''
            INSERT INTO user_dormancy (
                user_id,
                admin_id,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?)
            ''',
            (
                target_user['id'],
                g.current_user['id'],
                reason,
                now,
            ),
        )
        add_admin_action_audit(
            cursor,
            'user_dormant',
            g.current_user['id'],
            reason,
            now,
            target_user_id=target_user['id'],
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        abort(400)

    disconnect_user_sockets(target_user['id'])
    flash('불량 사용자를 휴면 처리했습니다.')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/users/<user_id>/reactivate', methods=['POST'])
@admin_required
@csrf_protected
def admin_reactivate_user(user_id):
    normalized_user_id = normalize_uuid_identifier(user_id)
    if normalized_user_id is None:
        abort(404)
    reason, validation_error = validate_moderation_reason(
        request.form.get('reason', '')
    )
    if validation_error:
        flash(validation_error)
        return redirect(url_for('admin_dashboard'))
    if not enforce_admin_action_authorization():
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    cursor = db.cursor()
    target_user = cursor.execute(
        '''
        SELECT user.id, user.is_admin
        FROM user
        JOIN user_dormancy ON user_dormancy.user_id = user.id
        WHERE user.id = ? AND user.deleted_at IS NULL
        ''',
        (normalized_user_id,),
    ).fetchone()
    if target_user is None:
        abort(404)
    if target_user['is_admin'] == 1:
        abort(403)

    now = int(time.time())
    try:
        delete_cursor = cursor.execute(
            'DELETE FROM user_dormancy WHERE user_id = ?',
            (target_user['id'],),
        )
        if delete_cursor.rowcount != 1:
            db.rollback()
            abort(404)
        add_admin_action_audit(
            cursor,
            'user_reactivated',
            g.current_user['id'],
            reason,
            now,
            target_user_id=target_user['id'],
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        abort(400)

    flash('사용자 휴면을 해제했습니다.')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/reports/<report_id>/review', methods=['POST'])
@admin_required
@csrf_protected
def admin_review_report(report_id):
    normalized_report_id = normalize_uuid_identifier(report_id)
    if normalized_report_id is None:
        abort(404)
    status = request.form.get('status', '').strip().lower()
    if status not in {'resolved', 'dismissed'}:
        abort(400)
    note, validation_error = validate_moderation_reason(
        request.form.get('reason', '')
    )
    if validation_error:
        flash(validation_error)
        return redirect(url_for('admin_dashboard'))
    if not enforce_admin_action_authorization():
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    cursor = db.cursor()
    report_row = cursor.execute(
        '''
        SELECT report.id
        FROM report
        LEFT JOIN report_review ON report_review.report_id = report.id
        WHERE report.id = ? AND report_review.report_id IS NULL
        ''',
        (normalized_report_id,),
    ).fetchone()
    if report_row is None:
        abort(404)
    try:
        cursor.execute(
            '''
            INSERT INTO report_review (
                report_id,
                admin_id,
                admin_username_snapshot,
                status,
                note,
                reviewed_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (
                report_row['id'],
                g.current_user['id'],
                g.current_user['username'],
                status,
                note,
                int(time.time()),
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        abort(400)

    flash('신고 검토 상태를 저장했습니다.')
    return redirect(url_for('admin_dashboard'))


# 1대1 채팅 사용자 목록
@app.route('/chat')
@login_required
def direct_chat_users():
    page = get_page_number()
    db = get_db()
    user_filter = '''
        FROM user
        WHERE
            id <> ?
            AND deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM user_dormancy
                WHERE user_dormancy.user_id = user.id
            )
    '''
    total_items = db.execute(
        f'SELECT COUNT(*) {user_filter}',
        (g.current_user['id'],),
    ).fetchone()[0]
    pagination = build_pagination(
        total_items,
        page,
        DIRECT_CHAT_USER_LIST_LIMIT,
    )
    users = db.execute(
        f'''
        SELECT
            id,
            username,
            EXISTS (
                SELECT 1
                FROM user_block
                WHERE
                    (
                        blocker_id = ?
                        AND blocked_id = user.id
                    )
                    OR (
                        blocker_id = user.id
                        AND blocked_id = ?
                    )
            ) AS is_blocked
        {user_filter}
        ORDER BY username, id
        LIMIT ? OFFSET ?
        ''',
        (
            g.current_user['id'],
            g.current_user['id'],
            g.current_user['id'],
            DIRECT_CHAT_USER_LIST_LIMIT,
            (page - 1) * DIRECT_CHAT_USER_LIST_LIMIT,
        ),
    ).fetchall()
    return render_template(
        'direct_chat_users.html',
        users=users,
        pagination=pagination,
    )


# 1대1 채팅 대화 화면
@app.route('/chat/<recipient_id>')
@login_required
def direct_chat(recipient_id):
    recipient = get_chat_recipient_or_404(recipient_id)
    page = get_page_number()
    db = get_db()
    conversation_filter = '''
        FROM direct_message
        JOIN user AS sender ON sender.id = direct_message.sender_id
        WHERE
            (
                direct_message.sender_id = ?
                AND direct_message.recipient_id = ?
            )
            OR
            (
                direct_message.sender_id = ?
                AND direct_message.recipient_id = ?
            )
    '''
    parameters = (
        g.current_user['id'],
        recipient['id'],
        recipient['id'],
        g.current_user['id'],
    )
    total_items = db.execute(
        f'SELECT COUNT(*) {conversation_filter}',
        parameters,
    ).fetchone()[0]
    pagination = build_pagination(
        total_items,
        page,
        DIRECT_CHAT_HISTORY_LIMIT,
    )
    messages = db.execute(
        f'''
        SELECT
            direct_message.id,
            direct_message.sender_id,
            direct_message.recipient_id,
            direct_message.message,
            direct_message.created_at,
            sender.username AS sender_username
        {conversation_filter}
        ORDER BY direct_message.created_at DESC, direct_message.id DESC
        LIMIT ? OFFSET ?
        ''',
        (
            *parameters,
            DIRECT_CHAT_HISTORY_LIMIT,
            (page - 1) * DIRECT_CHAT_HISTORY_LIMIT,
        ),
    ).fetchall()
    blocked_by_current_user = db.execute(
        '''
        SELECT 1
        FROM user_block
        WHERE blocker_id = ? AND blocked_id = ?
        ''',
        (
            g.current_user['id'],
            recipient['id'],
        ),
    ).fetchone() is not None
    return render_template(
        'direct_chat.html',
        recipient=recipient,
        messages=list(reversed(messages)),
        user=g.current_user,
        is_blocked=users_are_blocked(
            g.current_user['id'],
            recipient['id'],
        ),
        blocked_by_current_user=blocked_by_current_user,
        pagination=pagination,
    )


@app.route('/chat/<recipient_id>/block', methods=['POST'])
@login_required
@csrf_protected
def block_chat_user(recipient_id):
    recipient = get_chat_recipient_or_404(recipient_id)
    db = get_db()
    db.execute(
        '''
        INSERT OR IGNORE INTO user_block (blocker_id, blocked_id, created_at)
        VALUES (?, ?, ?)
        ''',
        (g.current_user['id'], recipient['id'], int(time.time())),
    )
    db.commit()
    flash('사용자를 차단했습니다.')
    return redirect(url_for('direct_chat', recipient_id=recipient['id']))


@app.route('/chat/<recipient_id>/unblock', methods=['POST'])
@login_required
@csrf_protected
def unblock_chat_user(recipient_id):
    recipient = get_chat_recipient_or_404(recipient_id)
    db = get_db()
    db.execute(
        '''
        DELETE FROM user_block
        WHERE blocker_id = ? AND blocked_id = ?
        ''',
        (g.current_user['id'], recipient['id']),
    )
    db.commit()
    flash('사용자 차단을 해제했습니다.')
    return redirect(url_for('direct_chat', recipient_id=recipient['id']))


# 신고하기
@app.route('/report', methods=['GET', 'POST'])
@login_required
def report():
    if request.method == 'POST':
        return report_post()
    return render_template('report.html')


@csrf_protected
def report_post():
    db = get_db()
    cursor = db.cursor()
    now = int(time.time())
    source_ip_hash = get_client_ip_hash()

    ip_allowed, should_log_ip_block = consume_report_rate_limit(
        cursor,
        'ip',
        source_ip_hash,
        MAX_REPORT_ATTEMPTS_PER_IP,
        now,
    )
    if not ip_allowed:
        if should_log_ip_block:
            add_report_audit_log(
                cursor,
                'report_rejected_ip_rate',
                g.current_user['id'],
                None,
                None,
                now,
                source_ip_hash,
            )
        db.commit()
        abort(429)

    user_allowed, should_log_user_block = consume_report_rate_limit(
        cursor,
        'user',
        g.current_user['id'],
        MAX_REPORT_ATTEMPTS_PER_USER,
        now,
    )
    if not user_allowed:
        if should_log_user_block:
            add_report_audit_log(
                cursor,
                'report_rejected_user_rate',
                g.current_user['id'],
                None,
                None,
                now,
                source_ip_hash,
            )
        db.commit()
        abort(429)

    report_data, validation_error = validate_report_input(
        request.form.get('target_type', ''),
        request.form.get('target_id', ''),
        request.form.get('reason', ''),
        g.current_user['id'],
        db,
    )
    if validation_error:
        event_type = (
            'report_rejected_sensitive_data'
            if validation_error == REPORT_SENSITIVE_DATA_ERROR
            else 'report_rejected_validation'
        )
        add_report_audit_log(
            cursor,
            event_type,
            g.current_user['id'],
            None,
            None,
            now,
            source_ip_hash,
        )
        db.commit()
        flash(validation_error)
        return redirect(url_for('report'))

    report_count = db.execute(
        '''
        SELECT COUNT(*)
        FROM report
        WHERE reporter_id = ? AND created_at >= ?
        ''',
        (
            g.current_user['id'],
            now - REPORT_RATE_WINDOW_SECONDS,
        ),
    ).fetchone()[0]
    if report_count >= MAX_REPORTS_PER_WINDOW:
        add_report_audit_log(
            cursor,
            'report_rejected_user_rate',
            g.current_user['id'],
            report_data['target_type'],
            report_data['target_id'],
            now,
            source_ip_hash,
        )
        db.commit()
        abort(429)

    if report_data['target_type'] == 'user':
        duplicate_report = db.execute(
            '''
            SELECT 1
            FROM report
            WHERE reporter_id = ? AND target_user_id = ?
            ''',
            (g.current_user['id'], report_data['target_user_id']),
        ).fetchone()
    else:
        duplicate_report = db.execute(
            '''
            SELECT 1
            FROM report
            WHERE reporter_id = ? AND target_product_id = ?
            ''',
            (g.current_user['id'], report_data['target_product_id']),
        ).fetchone()
    if duplicate_report is not None:
        add_report_audit_log(
            cursor,
            'report_rejected_duplicate',
            g.current_user['id'],
            report_data['target_type'],
            report_data['target_id'],
            now,
            source_ip_hash,
        )
        db.commit()
        abort(429)

    try:
        cursor.execute(
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
            (
                str(uuid.uuid4()),
                g.current_user['id'],
                report_data['target_type'],
                report_data['target_user_id'],
                report_data['target_product_id'],
                report_data['reason'],
                now,
            ),
        )
        add_report_audit_log(
            cursor,
            'report_created',
            g.current_user['id'],
            report_data['target_type'],
            report_data['target_id'],
            now,
            source_ip_hash,
        )
        db.commit()
    except sqlite3.IntegrityError as error:
        db.rollback()
        if str(error) in {
            'duplicate report',
            'report rate limit exceeded',
        }:
            abort(429)
        abort(400)

    flash('신고가 접수되었습니다.')
    return redirect(url_for('dashboard'))

def get_authenticated_socket_user():
    user_id = session.get('user_id')
    now = int(time.time())
    if user_id is None or not session_timestamps_are_valid(now):
        session.clear()
        return None

    user = get_db().execute(
        '''
        SELECT id, username, session_version
        FROM user
        WHERE
            id = ?
            AND deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM user_dormancy
                WHERE user_dormancy.user_id = user.id
            )
        ''',
        (user_id,),
    ).fetchone()
    session_version = session.get('session_version', 0)
    if (
        user is None
        or not isinstance(session_version, int)
        or session_version != user['session_version']
    ):
        session.clear()
        return None

    session['last_activity'] = now
    return user


def socket_csrf_is_valid(auth):
    expected_token = session.get(CSRF_SESSION_KEY, '')
    submitted_token = (
        auth.get('csrf_token', '')
        if isinstance(auth, dict)
        else ''
    )
    return (
        isinstance(submitted_token, str)
        and expected_token
        and submitted_token
        and hmac.compare_digest(expected_token, submitted_token)
    )


def validate_chat_message(data):
    if not isinstance(data, dict) or set(data) != {'message'}:
        return None
    raw_message = data.get('message')
    if not isinstance(raw_message, str):
        return None

    message = unicodedata.normalize('NFKC', raw_message.strip())
    if not CHAT_MESSAGE_MIN_LENGTH <= len(message) <= CHAT_MESSAGE_MAX_LENGTH:
        return None
    if any(
        unicodedata.category(character).startswith('C')
        for character in message
    ):
        return None
    return message


def validate_direct_chat_message(data):
    if not isinstance(data, dict) or set(data) != {'recipient_id', 'message'}:
        return None, None
    recipient_id = normalize_uuid_identifier(data.get('recipient_id'))
    message = validate_chat_message({'message': data.get('message')})
    if recipient_id is None or message is None:
        return None, None
    return recipient_id, message


def direct_chat_room(user_id):
    return f'direct-chat-user:{user_id}'


def disconnect_user_sockets(user_id):
    participants = list(
        socketio.server.manager.get_participants(
            '/',
            direct_chat_room(user_id),
        )
    )
    for participant in participants:
        socket_id = (
            participant[0]
            if isinstance(participant, tuple)
            else participant
        )
        socketio.server.disconnect(socket_id, namespace='/')


def prune_chat_rate_limit_state(now):
    windows = {
        'user': CHAT_USER_RATE_WINDOW_SECONDS,
        'ip': CHAT_IP_RATE_WINDOW_SECONDS,
    }
    for scope_type, entries in chat_rate_limit_state.items():
        cutoff = now - windows[scope_type]
        for scope_key, timestamps in list(entries.items()):
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if not timestamps:
                entries.pop(scope_key, None)

    duplicate_cutoff = now - CHAT_DUPLICATE_WINDOW_SECONDS
    for user_id, (_, sent_at) in list(chat_duplicate_state.items()):
        if sent_at <= duplicate_cutoff:
            chat_duplicate_state.pop(user_id, None)


def consume_chat_rate_limit(user_id, source_ip_hash, now):
    with chat_rate_limit_lock:
        prune_chat_rate_limit_state(now)
        user_timestamps = chat_rate_limit_state['user'].setdefault(
            user_id,
            deque(),
        )
        ip_timestamps = chat_rate_limit_state['ip'].setdefault(
            source_ip_hash,
            deque(),
        )
        if (
            len(user_timestamps) >= CHAT_USER_RATE_LIMIT
            or len(ip_timestamps) >= CHAT_IP_RATE_LIMIT
        ):
            return False
        user_timestamps.append(now)
        ip_timestamps.append(now)
        return True


def chat_message_is_duplicate(user_id, message, now):
    with chat_rate_limit_lock:
        previous_message = chat_duplicate_state.get(user_id)
        if (
            previous_message is not None
            and previous_message[0] == message
            and now - previous_message[1] < CHAT_DUPLICATE_WINDOW_SECONDS
        ):
            return True
        chat_duplicate_state[user_id] = (message, now)
        return False


def reject_chat_event(
    code,
    message,
    should_disconnect=False,
    event_name='chat_error',
):
    emit(event_name, {'code': code, 'message': message})
    if should_disconnect:
        disconnect()
    return {'ok': False, 'error': code}


@socketio.on('connect')
def handle_socket_connect(auth=None):
    if not socket_csrf_is_valid(auth):
        return False
    user = get_authenticated_socket_user()
    if user is None:
        return False
    db = get_db()
    connection_allowed = consume_security_rate_limit(
        db.cursor(),
        'socket_ip',
        get_client_ip_hash(),
        SOCKET_CONNECT_IP_RATE_LIMIT,
        SOCKET_CONNECT_RATE_WINDOW_SECONDS,
        int(time.time()),
    )
    db.commit()
    if not connection_allowed:
        return False
    current_connections = list(
        socketio.server.manager.get_participants(
            '/',
            direct_chat_room(user['id']),
        )
    )
    if len(current_connections) >= SOCKET_MAX_CONNECTIONS_PER_USER:
        return False
    join_room(direct_chat_room(user['id']))
    return True


@socketio.on('send_message')
def handle_send_message_event(data):
    user = get_authenticated_socket_user()
    if user is None:
        return reject_chat_event(
            'authentication_required',
            '로그인이 필요합니다.',
            should_disconnect=True,
        )

    now = int(time.time())
    rate_limit_time = time.monotonic()
    source_ip_hash = get_client_ip_hash()
    if not consume_chat_rate_limit(
        user['id'],
        source_ip_hash,
        rate_limit_time,
    ):
        return reject_chat_event(
            'rate_limited',
            '메시지를 너무 빠르게 보내고 있습니다.',
        )

    message = validate_chat_message(data)
    if message is None:
        return reject_chat_event(
            'invalid_message',
            '메시지 형식을 확인해주세요.',
        )
    if chat_message_is_duplicate(
        user['id'],
        message,
        rate_limit_time,
    ):
        return reject_chat_event(
            'duplicate_message',
            '같은 메시지를 연속으로 보낼 수 없습니다.',
        )

    outbound_message = {
        'message_id': str(uuid.uuid4()),
        'username': user['username'],
        'message': message,
        'sent_at': now,
    }
    send(outbound_message, broadcast=True)
    return {'ok': True, 'message_id': outbound_message['message_id']}


@socketio.on('send_direct_message')
def handle_send_direct_message_event(data):
    user = get_authenticated_socket_user()
    if user is None:
        return reject_chat_event(
            'authentication_required',
            '로그인이 필요합니다.',
            should_disconnect=True,
            event_name='direct_chat_error',
        )

    rate_limit_time = time.monotonic()
    if not consume_chat_rate_limit(
        user['id'],
        get_client_ip_hash(),
        rate_limit_time,
    ):
        return reject_chat_event(
            'rate_limited',
            '메시지를 너무 빠르게 보내고 있습니다.',
            event_name='direct_chat_error',
        )

    recipient_id, message = validate_direct_chat_message(data)
    if recipient_id is None or message is None or recipient_id == user['id']:
        return reject_chat_event(
            'invalid_message',
            '메시지 형식을 확인해주세요.',
            event_name='direct_chat_error',
        )
    if users_are_blocked(user['id'], recipient_id):
        return reject_chat_event(
            'recipient_blocked',
            '차단 상태에서는 메시지를 보낼 수 없습니다.',
            event_name='direct_chat_error',
        )

    db = get_db()
    recipient = db.execute(
        '''
        SELECT id
        FROM user
        WHERE
            id = ?
            AND deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM user_dormancy
                WHERE user_dormancy.user_id = user.id
            )
        ''',
        (recipient_id,),
    ).fetchone()
    if recipient is None:
        return reject_chat_event(
            'invalid_recipient',
            '대화 상대를 확인할 수 없습니다.',
            event_name='direct_chat_error',
        )

    duplicate_scope = f'direct:{user["id"]}:{recipient_id}'
    if chat_message_is_duplicate(
        duplicate_scope,
        message,
        rate_limit_time,
    ):
        return reject_chat_event(
            'duplicate_message',
            '같은 메시지를 연속으로 보낼 수 없습니다.',
            event_name='direct_chat_error',
        )

    now = int(time.time())
    message_id = str(uuid.uuid4())
    try:
        db.execute(
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
            (message_id, user['id'], recipient_id, message, now),
        )
        db.commit()
    except sqlite3.Error:
        db.rollback()
        return reject_chat_event(
            'message_not_sent',
            '메시지를 전송할 수 없습니다.',
            event_name='direct_chat_error',
        )

    outbound_message = {
        'message_id': message_id,
        'sender_id': user['id'],
        'sender_username': user['username'],
        'recipient_id': recipient_id,
        'message': message,
        'sent_at': now,
    }
    emit(
        'direct_message',
        outbound_message,
        to=direct_chat_room(user['id']),
    )
    emit(
        'direct_message',
        outbound_message,
        to=direct_chat_room(recipient_id),
    )
    return {'ok': True, 'message_id': message_id}


@app.errorhandler(400)
def bad_request(error):
    if isinstance(error, SecurityError):
        return 'Bad Request', 400, {'Content-Type': 'text/plain; charset=utf-8'}
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
