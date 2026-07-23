import argparse
import os
import sqlite3
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class DatabaseBackupError(RuntimeError):
    """안전한 데이터베이스 백업 또는 검증을 완료할 수 없는 경우."""


def resolved_output_path(path):
    output_path = Path(path).expanduser()
    resolved_path = output_path.parent.resolve() / output_path.name
    try:
        resolved_path.relative_to(REPOSITORY_ROOT)
    except ValueError:
        return resolved_path
    raise DatabaseBackupError(
        'DB 백업과 복구 검증 파일은 저장소 밖에 생성해야 합니다.'
    )


def open_read_only_database(path):
    database_path = Path(path).expanduser().resolve()
    if not database_path.is_file():
        raise DatabaseBackupError(
            f'데이터베이스 파일을 찾을 수 없습니다: {database_path}'
        )
    try:
        return sqlite3.connect(f'{database_path.as_uri()}?mode=ro', uri=True)
    except sqlite3.Error as error:
        raise DatabaseBackupError(
            f'데이터베이스를 읽기 전용으로 열 수 없습니다: {database_path}'
        ) from error


def verify_database(path):
    database_path = Path(path).expanduser().resolve()
    connection = open_read_only_database(database_path)
    try:
        integrity_results = [
            row[0]
            for row in connection.execute('PRAGMA quick_check').fetchall()
        ]
        foreign_key_issues = connection.execute(
            'PRAGMA foreign_key_check'
        ).fetchall()
    except sqlite3.Error as error:
        raise DatabaseBackupError(
            f'데이터베이스 무결성을 검사할 수 없습니다: {database_path}'
        ) from error
    finally:
        connection.close()

    if integrity_results != ['ok']:
        raise DatabaseBackupError(
            f'데이터베이스 무결성 검사에 실패했습니다: {integrity_results}'
        )
    if foreign_key_issues:
        raise DatabaseBackupError(
            f'외래키 무결성 위반이 {len(foreign_key_issues)}건 있습니다.'
        )
    return {
        'path': str(database_path),
        'integrity_check': 'ok',
        'foreign_key_issues': 0,
    }


def copy_verified_database(source, output):
    source_path = Path(source).expanduser().resolve()
    output_path = resolved_output_path(output)
    if source_path == output_path:
        raise DatabaseBackupError('원본과 출력 경로는 서로 달라야 합니다.')
    if output_path.exists():
        raise DatabaseBackupError(
            f'기존 파일을 덮어쓰지 않습니다: {output_path}'
        )

    verify_database(source_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        file_descriptor = os.open(
            output_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError as error:
        raise DatabaseBackupError(
            f'기존 파일을 덮어쓰지 않습니다: {output_path}'
        ) from error
    except OSError as error:
        raise DatabaseBackupError(
            f'출력 파일을 안전하게 생성할 수 없습니다: {output_path}'
        ) from error
    else:
        os.close(file_descriptor)

    source_connection = open_read_only_database(source_path)
    output_connection = None
    copy_error = None
    try:
        output_connection = sqlite3.connect(output_path)
        source_connection.backup(output_connection)
        output_connection.commit()
    except (OSError, sqlite3.Error) as error:
        copy_error = error
    finally:
        source_connection.close()
        if output_connection is not None:
            output_connection.close()

    if copy_error is not None:
        output_path.unlink(missing_ok=True)
        raise DatabaseBackupError(
            f'데이터베이스 복사에 실패했습니다: {output_path}'
        ) from copy_error

    try:
        os.chmod(output_path, 0o600)
        verification = verify_database(output_path)
    except (OSError, DatabaseBackupError):
        output_path.unlink(missing_ok=True)
        raise
    return verification


def backup_database(source, output):
    return copy_verified_database(source, output)


def restore_database_to_new_file(backup, output):
    return copy_verified_database(backup, output)


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            'SQLite DB를 저장소 밖에 안전하게 백업하고 복구를 검증합니다.'
        )
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    backup_parser = subparsers.add_parser('backup')
    backup_parser.add_argument('--source', default='market.db')
    backup_parser.add_argument('--output', required=True)

    verify_parser = subparsers.add_parser('verify')
    verify_parser.add_argument('--database', required=True)

    restore_parser = subparsers.add_parser('restore')
    restore_parser.add_argument('--backup', required=True)
    restore_parser.add_argument('--output', required=True)
    return parser


def main():
    arguments = build_parser().parse_args()
    try:
        if arguments.command == 'backup':
            result = backup_database(arguments.source, arguments.output)
        elif arguments.command == 'verify':
            result = verify_database(arguments.database)
        else:
            result = restore_database_to_new_file(
                arguments.backup,
                arguments.output,
            )
    except DatabaseBackupError as error:
        raise SystemExit(f'오류: {error}') from error

    print(
        f'검증 완료: {result["path"]} '
        f'(integrity={result["integrity_check"]}, '
        f'foreign_key_issues={result["foreign_key_issues"]})'
    )


if __name__ == '__main__':
    main()
