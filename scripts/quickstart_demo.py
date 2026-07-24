#!/usr/bin/env python3

import argparse
import os
import secrets
import sqlite3
import sys
import tempfile
import time
import uuid
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ADMIN_USERNAME = 'quick_admin'
USER_USERNAME = 'user1'
RECIPIENT_USERNAME = 'user2'
DEMO_WALLET_BALANCE = 100_000


def generate_temporary_password():
    return f'Q{secrets.token_urlsafe(18)}7!'


def load_application():
    os.environ.setdefault('MARKET_SECRET_KEY', secrets.token_urlsafe(48))
    os.environ.setdefault('MARKET_COOKIE_SECURE', 'false')
    os.environ.setdefault('MARKET_DEBUG', 'false')
    os.environ.setdefault('MARKET_REQUIRE_HTTPS', 'false')
    os.environ.setdefault(
        'MARKET_TRUSTED_HOSTS',
        'localhost,127.0.0.1,[::1]',
    )
    repository_path = str(REPOSITORY_ROOT)
    if repository_path not in sys.path:
        sys.path.insert(0, repository_path)
    import app as market

    return market


def seed_demo_database(market):
    market.init_db()
    admin_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    recipient_id = str(uuid.uuid4())
    apple_product_id = str(uuid.uuid4())
    banana_product_id = str(uuid.uuid4())
    admin_password = generate_temporary_password()
    user_password = generate_temporary_password()
    recipient_password = generate_temporary_password()
    created_at = int(time.time())

    connection = sqlite3.connect(market.DATABASE)
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        connection.execute(
            '''
            INSERT INTO user (id, username, password, is_admin)
            VALUES (?, ?, ?, 1)
            ''',
            (
                admin_id,
                ADMIN_USERNAME,
                market.password_hasher.hash(admin_password),
            ),
        )
        connection.execute(
            '''
            INSERT INTO user (id, username, password, is_admin)
            VALUES (?, ?, ?, 0)
            ''',
            (
                user_id,
                USER_USERNAME,
                market.password_hasher.hash(user_password),
            ),
        )
        connection.execute(
            '''
            INSERT INTO user (id, username, password, is_admin)
            VALUES (?, ?, ?, 0)
            ''',
            (
                recipient_id,
                RECIPIENT_USERNAME,
                market.password_hasher.hash(recipient_password),
            ),
        )
        for wallet_user_id in (user_id, recipient_id):
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
                    wallet_user_id,
                    DEMO_WALLET_BALANCE,
                    created_at,
                ),
            )
        connection.execute(
            '''
            INSERT INTO admin_role_audit (
                id,
                operator_name,
                target_user_id,
                target_username_snapshot,
                action_type,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?, 'admin_granted', ?, ?)
            ''',
            (
                str(uuid.uuid4()),
                'quickstart-demo',
                admin_id,
                ADMIN_USERNAME,
                '격리된 빠른 실행 데모에서 관리자 권한을 부여했습니다.',
                created_at,
            ),
        )
        connection.execute(
            '''
            INSERT INTO product (id, title, description, price, seller_id)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (
                apple_product_id,
                '사과 한 상자',
                '깨끗하게 보관한 중고거래 테스트용 사과 한 상자입니다.',
                15000,
                user_id,
            ),
        )
        connection.execute(
            '''
            INSERT INTO product (id, title, description, price, seller_id)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (
                banana_product_id,
                '바나나 한 송이',
                '송금과 상품 목록을 확인하기 위한 테스트용 바나나입니다.',
                5000,
                recipient_id,
            ),
        )
        report_targets = (
            (
                str(uuid.uuid4()),
                'user',
                user_id,
                None,
                '빠른 실행 사용자 신고 처리 흐름을 확인합니다.',
                user_id,
            ),
            (
                str(uuid.uuid4()),
                'product',
                None,
                apple_product_id,
                '사과 상품의 신고 처리 흐름을 확인합니다.',
                apple_product_id,
            ),
        )
        for (
            report_id,
            target_type,
            target_user_id,
            target_product_id,
            reason,
            audit_target_id,
        ) in report_targets:
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
                (
                    report_id,
                    admin_id,
                    target_type,
                    target_user_id,
                    target_product_id,
                    reason,
                    created_at,
                ),
            )
            market.add_report_audit_log(
                connection,
                'report_created',
                admin_id,
                target_type,
                audit_target_id,
                created_at,
            )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        raise
    finally:
        connection.close()

    return {
        'admin_username': ADMIN_USERNAME,
        'admin_password': admin_password,
        'user_username': USER_USERNAME,
        'user_password': user_password,
        'recipient_username': RECIPIENT_USERNAME,
        'recipient_password': recipient_password,
        'wallet_balance': DEMO_WALLET_BALANCE,
        'apple_product_id': apple_product_id,
        'banana_product_id': banana_product_id,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            'Git과 일반 실행 DB에서 분리된 임시 DB에 빠른 테스트 계정을 만들고 '
            '로컬 서버를 실행합니다.'
        )
    )
    parser.add_argument('--port', type=int, default=5000)
    return parser


def main():
    arguments = build_parser().parse_args()
    if not 1 <= arguments.port <= 65535:
        raise SystemExit('포트는 1~65535 범위여야 합니다.')

    market = load_application()
    with tempfile.TemporaryDirectory(
        prefix='secure-coding-quickstart-'
    ) as temporary_directory:
        database_path = Path(temporary_directory) / 'quickstart.db'
        market.DATABASE = str(database_path)
        accounts = seed_demo_database(market)

        print()
        print('빠른 실행용 임시 환경을 준비했습니다.')
        print(f'임시 DB: {database_path}')
        print(
            f'관리자 계정: {accounts["admin_username"]} / '
            f'{accounts["admin_password"]}'
        )
        print(
            f'일반 사용자 1 계정: {accounts["user_username"]} / '
            f'{accounts["user_password"]}'
        )
        print(
            f'일반 사용자 2 계정: {accounts["recipient_username"]} / '
            f'{accounts["recipient_password"]}'
        )
        print(
            f'두 일반 계정의 학습용 송금 잔액: '
            f'{accounts["wallet_balance"]:,}원'
        )
        print(f'접속 주소: http://127.0.0.1:{arguments.port}')
        print(f'송금 페이지: http://127.0.0.1:{arguments.port}/transfers')
        print(
            '간단 송금 테스트: user1로 로그인 → 송금 → user2 선택 '
            '(반대 방향도 가능)'
        )
        print(
            f'관리자 페이지: '
            f'http://127.0.0.1:{arguments.port}/admin'
        )
        print('Ctrl+C로 종료하면 임시 DB와 테스트 계정이 삭제됩니다.')
        print('이 계정은 로컬 실습에서만 사용하세요.')
        print()

        try:
            market.socketio.run(
                market.app,
                host='127.0.0.1',
                port=arguments.port,
                debug=False,
                allow_unsafe_werkzeug=True,
            )
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
