import argparse
import sqlite3
import sys
from pathlib import Path


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
            '관리자 스키마가 없습니다. 먼저 Version 3.0 애플리케이션을 실행하세요.'
        )
    return connection


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


def set_admin_role(connection, username, grant):
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

    connection.execute(
        'UPDATE user SET is_admin = ? WHERE id = ?',
        (1 if grant else 0, user['id']),
    )
    connection.commit()
    return user


def parse_args():
    parser = argparse.ArgumentParser(
        description='로컬 SQLite 사용자의 관리자 역할을 관리합니다.',
    )
    parser.add_argument('--database', default='market.db')
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('list')
    for command in ('grant', 'revoke'):
        role_parser = subparsers.add_parser(command)
        role_parser.add_argument('--username', required=True)
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
            user = set_admin_role(
                connection,
                args.username,
                grant=args.command == 'grant',
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
