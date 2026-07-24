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
                'SELECT username, password, is_admin FROM user'
            ).fetchall()
        }
        assert set(users) == {
            quickstart_demo.ADMIN_USERNAME,
            quickstart_demo.USER_USERNAME,
        }
        assert users[accounts['admin_username']]['is_admin'] == 1
        assert users[accounts['user_username']]['is_admin'] == 0
        assert market.password_hasher.verify(
            users[accounts['admin_username']]['password'],
            accounts['admin_password'],
        )
        assert market.password_hasher.verify(
            users[accounts['user_username']]['password'],
            accounts['user_password'],
        )
        assert connection.execute(
            'SELECT COUNT(*) FROM product'
        ).fetchone()[0] == 1
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
