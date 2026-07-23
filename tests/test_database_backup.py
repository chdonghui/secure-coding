import os
import sqlite3
import stat

import pytest

from scripts.database_backup import (
    DatabaseBackupError,
    backup_database,
    restore_database_to_new_file,
    verify_database,
)


def create_database(path):
    connection = sqlite3.connect(path)
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        connection.execute(
            'CREATE TABLE parent (id INTEGER PRIMARY KEY, value TEXT NOT NULL)'
        )
        connection.execute(
            '''
            CREATE TABLE child (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL,
                FOREIGN KEY (parent_id) REFERENCES parent(id)
            )
            '''
        )
        connection.execute(
            'INSERT INTO parent (id, value) VALUES (1, ?)',
            ('original',),
        )
        connection.execute(
            'INSERT INTO child (id, parent_id) VALUES (1, 1)'
        )
        connection.commit()
    finally:
        connection.close()


def test_backup_and_restore_are_verified_without_overwriting(tmp_path):
    source = tmp_path / 'source.db'
    backup = tmp_path / 'safe.backup.db'
    restored = tmp_path / 'verified.restore.db'
    create_database(source)

    backup_result = backup_database(source, backup)
    assert backup_result['integrity_check'] == 'ok'
    assert backup_result['foreign_key_issues'] == 0
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600

    connection = sqlite3.connect(source)
    try:
        connection.execute(
            'UPDATE parent SET value = ? WHERE id = 1',
            ('changed-after-backup',),
        )
        connection.commit()
    finally:
        connection.close()

    restore_result = restore_database_to_new_file(backup, restored)
    assert restore_result['integrity_check'] == 'ok'
    assert stat.S_IMODE(restored.stat().st_mode) == 0o600

    connection = sqlite3.connect(restored)
    try:
        restored_value = connection.execute(
            'SELECT value FROM parent WHERE id = 1'
        ).fetchone()[0]
    finally:
        connection.close()
    assert restored_value == 'original'

    with pytest.raises(DatabaseBackupError, match='덮어쓰지 않습니다'):
        backup_database(source, backup)


def test_backup_output_inside_repository_is_rejected(tmp_path):
    source = tmp_path / 'source.db'
    create_database(source)

    with pytest.raises(DatabaseBackupError, match='저장소 밖'):
        backup_database(source, 'unsafe.backup.db')
    assert not os.path.exists('unsafe.backup.db')


def test_verification_rejects_foreign_key_violations(tmp_path):
    database = tmp_path / 'invalid-foreign-key.db'
    create_database(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute('PRAGMA foreign_keys = OFF')
        connection.execute(
            'INSERT INTO child (id, parent_id) VALUES (2, 999)'
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(DatabaseBackupError, match='외래키 무결성 위반'):
        verify_database(database)


def test_verification_rejects_non_database_file(tmp_path):
    invalid_file = tmp_path / 'not-a-database.db'
    invalid_file.write_text('not a sqlite database', encoding='utf-8')

    with pytest.raises(DatabaseBackupError, match='무결성을 검사할 수 없습니다'):
        verify_database(invalid_file)
