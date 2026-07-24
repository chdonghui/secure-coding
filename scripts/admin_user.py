import argparse
import getpass
import sqlite3
import sys
import time
import unicodedata
import uuid
from pathlib import Path


DEFAULT_ROLE_CHANGE_REASON = '로컬 관리자 역할 변경 요청을 처리했습니다.'


def open_database(database_path):
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f'데이터베이스 파일을 찾을 수 없습니다: {path}')
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    columns = {
        row['name']
        for row in connection.execute('PRAGMA table_info(user)').fetchall()
    }
    if 'is_admin' not in columns:
        connection.close()
        raise ValueError(
            '관리자 스키마가 없습니다. 먼저 Version 3.1 애플리케이션을 실행하세요.'
        )
    if 'account_type' not in columns:
        connection.close()
        raise ValueError(
            '사업자 계정 스키마가 없습니다. 먼저 Version 6.0 애플리케이션을 실행하세요.'
        )
    role_audit_table = connection.execute(
        '''
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'admin_role_audit'
        '''
    ).fetchone()
    if role_audit_table is None:
        connection.close()
        raise ValueError(
            '관리자 역할 감사 스키마가 없습니다. '
            '먼저 Version 3.1 애플리케이션을 실행하세요.'
        )
    return connection


def list_businesses(connection):
    return connection.execute(
        '''
        SELECT id, username
        FROM user
        WHERE account_type = 'business' AND is_admin = 0 AND deleted_at IS NULL
        ORDER BY username, id
        '''
    ).fetchall()


def set_business_role(connection, username, grant, operator_name=None,
                      reason=DEFAULT_ROLE_CHANGE_REASON):
    operator_name = (operator_name or getpass.getuser()).strip()
    reason = unicodedata.normalize('NFKC', reason.strip())
    if not 1 <= len(operator_name) <= 100:
        raise ValueError('운영자 식별자는 1~100자여야 합니다.')
    if not 10 <= len(reason) <= 500:
        raise ValueError('역할 변경 사유는 10~500자여야 합니다.')
    user = connection.execute(
        '''SELECT id, username, is_admin, account_type, deleted_at,
                  (SELECT 1 FROM user_dormancy d WHERE d.user_id = user.id) AS dormant
           FROM user WHERE username = ?''', (username,)
    ).fetchone()
    if user is None or user['deleted_at'] is not None:
        raise ValueError('활성 사용자를 찾을 수 없습니다.')
    if user['is_admin'] == 1 or user['dormant']:
        raise ValueError('관리자 또는 휴면 사용자의 사업자 역할은 변경할 수 없습니다.')
    requested = 'business' if grant else 'user'
    if user['account_type'] == requested:
        raise ValueError('사용자가 이미 요청한 사업자 역할 상태입니다.')
    balance = connection.execute(
        '''SELECT COALESCE(SUM(amount), 0) FROM wallet_adjustment WHERE user_id = ?''',
        (user['id'],),
    ).fetchone()[0]
    balance += connection.execute(
        '''SELECT COALESCE(SUM(CASE WHEN recipient_id = ? THEN amount ELSE -amount END), 0)
           FROM money_transfer WHERE sender_id = ? OR recipient_id = ?''',
        (user['id'], user['id'], user['id']),
    ).fetchone()[0]
    if balance != 0:
        raise ValueError('사업자 역할을 변경하려면 잔액이 0원이어야 합니다.')
    try:
        connection.execute(
            'UPDATE user SET account_type = ?, session_version = session_version + 1 WHERE id = ?',
            (requested, user['id']),
        )
        connection.execute(
            '''INSERT INTO business_role_audit
               (id, operator_name, target_user_id, target_username_snapshot,
                action_type, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (str(uuid.uuid4()), operator_name, user['id'], user['username'],
             'business_granted' if grant else 'business_revoked', reason, int(time.time())),
        )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        raise
    return user


def list_admins(connection):
    return connection.execute(
        '''
        SELECT user.id, user.username
        FROM user
        LEFT JOIN user_dormancy ON user_dormancy.user_id = user.id
        WHERE
            user.is_admin = 1
            AND user.deleted_at IS NULL
            AND user_dormancy.user_id IS NULL
        ORDER BY user.username, user.id
        '''
    ).fetchall()


def set_admin_role(
    connection,
    username,
    grant,
    operator_name=None,
    reason=DEFAULT_ROLE_CHANGE_REASON,
):
    operator_name = (operator_name or getpass.getuser()).strip()
    reason = unicodedata.normalize('NFKC', reason.strip())
    if not 1 <= len(operator_name) <= 100 or any(
        unicodedata.category(character).startswith('C')
        for character in operator_name
    ):
        raise ValueError('운영자 식별자는 1~100자의 일반 문자여야 합니다.')
    if not 10 <= len(reason) <= 500 or any(
        unicodedata.category(character).startswith('C')
        and character not in {'\n', '\t'}
        for character in reason
    ):
        raise ValueError('역할 변경 사유는 10~500자의 일반 문자여야 합니다.')
    user = connection.execute(
        '''
        SELECT
            user.id,
            user.username,
            user.is_admin,
            user.deleted_at,
            user_dormancy.user_id AS dormant_user_id
        FROM user
        LEFT JOIN user_dormancy ON user_dormancy.user_id = user.id
        WHERE user.username = ?
        ''',
        (username,),
    ).fetchone()
    if user is None or user['deleted_at'] is not None:
        raise ValueError('활성 사용자를 찾을 수 없습니다.')
    if grant and user['dormant_user_id'] is not None:
        raise ValueError('휴면 사용자는 관리자로 지정할 수 없습니다.')
    if not grant and user['is_admin'] == 1 and len(list_admins(connection)) <= 1:
        raise ValueError('마지막 활성 관리자의 권한은 해제할 수 없습니다.')
    requested_role = 1 if grant else 0
    if user['is_admin'] == requested_role:
        raise ValueError('사용자가 이미 요청한 관리자 역할 상태입니다.')

    try:
        connection.execute(
            '''
            UPDATE user
            SET is_admin = ?, session_version = session_version + 1
            WHERE id = ?
            ''',
            (requested_role, user['id']),
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
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                str(uuid.uuid4()),
                operator_name,
                user['id'],
                user['username'],
                'admin_granted' if grant else 'admin_revoked',
                reason,
                int(time.time()),
            ),
        )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        raise
    return user


def parse_args():
    parser = argparse.ArgumentParser(
        description='로컬 SQLite 사용자의 관리자 역할을 관리합니다.',
    )
    parser.add_argument('--database', default='market.db')
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('list')
    subparsers.add_parser('list-businesses')
    for command in ('grant', 'revoke'):
        role_parser = subparsers.add_parser(command)
        role_parser.add_argument('--username', required=True)
        role_parser.add_argument('--reason', required=True)
        role_parser.add_argument('--operator')
    for command in ('business-grant', 'business-revoke'):
        role_parser = subparsers.add_parser(command)
        role_parser.add_argument('--username', required=True)
        role_parser.add_argument('--reason', required=True)
        role_parser.add_argument('--operator')
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        connection = open_database(args.database)
        try:
            if args.command == 'list':
                for admin in list_admins(connection):
                    print(f'{admin["username"]}\t{admin["id"]}')
                return 0
            if args.command == 'list-businesses':
                for business in list_businesses(connection):
                    print(f'{business["username"]}\t{business["id"]}')
                return 0
            if args.command.startswith('business-'):
                user = set_business_role(
                    connection, args.username,
                    grant=args.command == 'business-grant',
                    operator_name=args.operator, reason=args.reason,
                )
                print(f'{user["username"]}: 사업자 역할 변경 완료')
                return 0
            user = set_admin_role(
                connection,
                args.username,
                grant=args.command == 'grant',
                operator_name=args.operator,
                reason=args.reason,
            )
        finally:
            connection.close()
    except (sqlite3.Error, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1

    action = '부여' if args.command == 'grant' else '해제'
    print(f'{user["username"]} 관리자 권한 {action} 완료')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
