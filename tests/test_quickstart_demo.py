import os
import sqlite3


os.environ.setdefault(
    'MARKET_SECRET_KEY',
    'pytest-only-market-secret-key-with-more-than-32-characters',
)
os.environ.setdefault('MARKET_COOKIE_SECURE', 'false')

import app as market
from scripts import quickstart_demo


def test_quickstart_demo_uses_isolated_database_and_seeds_accounts(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / 'quickstart.db'
    monkeypatch.setattr(market, 'DATABASE', str(database_path))

    accounts = quickstart_demo.seed_demo_database(market)

    assert database_path.is_file()
    assert os.stat(database_path).st_mode & 0o777 == 0o600
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        users = {
            row['username']: row
            for row in connection.execute(
                'SELECT id, username, password, is_admin, account_type FROM user'
            ).fetchall()
        }
        assert set(users) == {
            quickstart_demo.ADMIN_USERNAME,
            quickstart_demo.USER_USERNAME,
            quickstart_demo.RECIPIENT_USERNAME,
            quickstart_demo.BUSINESS_USERNAME,
        }
        assert users[accounts['admin_username']]['is_admin'] == 1
        assert users[accounts['user_username']]['is_admin'] == 0
        assert users[accounts['recipient_username']]['is_admin'] == 0
        assert users[accounts['business_username']]['account_type'] == 'business'
        assert market.password_hasher.verify(
            users[accounts['admin_username']]['password'],
            accounts['admin_password'],
        )
        assert market.password_hasher.verify(
            users[accounts['user_username']]['password'],
            accounts['user_password'],
        )
        assert market.password_hasher.verify(
            users[accounts['recipient_username']]['password'],
            accounts['recipient_password'],
        )
        assert market.password_hasher.verify(
            users[accounts['business_username']]['password'],
            accounts['business_password'],
        )
        assert connection.execute(
            'SELECT COUNT(*) FROM wallet_adjustment'
        ).fetchone()[0] == 2
        for username in (
            accounts['user_username'],
            accounts['recipient_username'],
        ):
            assert market.get_wallet_balance(
                connection,
                users[username]['id'],
            ) == quickstart_demo.DEMO_WALLET_BALANCE
        assert market.get_wallet_balance(
            connection,
            users[accounts['admin_username']]['id'],
        ) == 0
        assert market.get_wallet_balance(
            connection, users[accounts['business_username']]['id']
        ) == 0
        products = {
            row['title']: row
            for row in connection.execute(
                '''
                SELECT product.id, product.title, product.price, user.username
                FROM product
                JOIN user ON user.id = product.seller_id
                '''
            ).fetchall()
        }
        assert set(products) == {'사과 한 상자', '바나나 한 송이'}
        assert products['사과 한 상자']['price'] == 15000
        assert products['사과 한 상자']['username'] == (
            accounts['business_username']
        )
        assert products['바나나 한 송이']['price'] == 5000
        assert products['바나나 한 송이']['username'] == accounts['business_username']
        assert connection.execute(
            'SELECT COUNT(*) FROM report'
        ).fetchone()[0] == 2
        assert connection.execute(
            'SELECT COUNT(*) FROM report_audit_log'
        ).fetchone()[0] == 2
        role_audit = connection.execute(
            '''
            SELECT action_type, target_username_snapshot
            FROM admin_role_audit
            '''
        ).fetchone()
        assert role_audit['action_type'] == 'admin_granted'
        assert role_audit['target_username_snapshot'] == (
            quickstart_demo.ADMIN_USERNAME
        )
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        connection.close()
