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
from flask_socketio import SocketIO, disconnect, emit, send
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
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 15 * 60
SESSION_IDLE_SECONDS = 30 * 60
SESSION_ABSOLUTE_SECONDS = 8 * 60 * 60
CSRF_SESSION_KEY = '_csrf_token'
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


def socket_origin_is_allowed(origin, environ):
    if origin is None:
        return True
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
    if 'session_version' not in columns:
        cursor.execute(
            '''
            ALTER TABLE user
            ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0
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
                locked_until INTEGER
            )
        """)
        # 상품 테이블 생성
        create_product_table(cursor)
        add_user_security_columns(cursor)
        migrate_plaintext_passwords(cursor)
        migrate_product_schema(cursor)
        # 상품 스키마 마이그레이션 이후 신고 외래키를 생성한다.
        create_report_table(cursor)
        create_report_audit_table(cursor)
        migrate_report_schema(cursor)
        migrate_report_audit_schema(cursor)
        create_report_rate_limit_table(cursor)
        ensure_report_schema_objects(cursor)
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


def consume_report_rate_limit(
    cursor,
    scope_type,
    scope_key,
    maximum_attempts,
    now,
):
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
            'SELECT id FROM user WHERE id = ?',
            (target_id,),
        ).fetchone()
        if target_user is None or target_user['id'] == reporter_id:
            return None, '신고 대상을 확인해주세요.'
        target_user_id = target_id
    else:
        target_product = db.execute(
            'SELECT id, seller_id FROM product WHERE id = ?',
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
        'SELECT * FROM user WHERE id = ?',
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
    session['session_version'] = user['session_version']
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


@app.route('/profile/password', methods=['POST'])
@login_required
@csrf_protected
def update_password():
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if (
        len(current_password) > PASSWORD_MAX_LENGTH
        or not verify_password(g.current_user['password'], current_password)
    ):
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
    return redirect(url_for('dashboard'))


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
        'SELECT id, username, session_version FROM user WHERE id = ?',
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


def reject_chat_event(code, message, should_disconnect=False):
    emit('chat_error', {'code': code, 'message': message})
    if should_disconnect:
        disconnect()
    return {'ok': False, 'error': code}


@socketio.on('connect')
def handle_socket_connect(auth=None):
    if not socket_csrf_is_valid(auth):
        return False
    return get_authenticated_socket_user() is not None


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
