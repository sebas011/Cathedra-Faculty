import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event

from app.db import Base
from app.migrations import run_migrations
from app.restore_recovery import begin_restore, recover_interrupted_restore, restore_marker_path


def test_interrupted_restore_recovers_safety_copy_before_startup(tmp_path: Path) -> None:
    database_path = tmp_path / "cathedra.db"
    backup_directory = tmp_path / "backups"
    backup_directory.mkdir()
    safety_backup = backup_directory / "cathedra-backup-before-restore-test.db"
    with closing(sqlite3.connect(database_path)) as database:
        database.execute("CREATE TABLE records (name TEXT NOT NULL)")
        database.execute("INSERT INTO records VALUES ('original')")
        database.commit()
        with closing(sqlite3.connect(safety_backup)) as backup:
            database.backup(backup)
    begin_restore(database_path, safety_backup)
    with closing(sqlite3.connect(database_path)) as database:
        database.execute("DELETE FROM records")
        database.execute("INSERT INTO records VALUES ('incomplete restore')")
        database.commit()

    assert recover_interrupted_restore(database_path, backup_directory)
    with closing(sqlite3.connect(database_path)) as database:
        assert database.execute("SELECT name FROM records").fetchall() == [("original",)]
    assert not restore_marker_path(database_path).exists()
    assert not recover_interrupted_restore(database_path, backup_directory)


def test_interrupted_restore_refuses_changed_safety_copy(tmp_path: Path) -> None:
    database_path = tmp_path / "cathedra.db"
    backup_directory = tmp_path / "backups"
    backup_directory.mkdir()
    safety_backup = backup_directory / "cathedra-backup-before-restore-test.db"
    with closing(sqlite3.connect(safety_backup)) as backup:
        backup.execute("CREATE TABLE records (name TEXT)")
        backup.commit()
    begin_restore(database_path, safety_backup)
    safety_backup.write_bytes(b"damaged")

    with pytest.raises(RuntimeError, match="missing or changed"):
        recover_interrupted_restore(database_path, backup_directory)
    assert restore_marker_path(database_path).exists()
    assert not database_path.exists()


def test_interrupted_restore_recovers_unreadable_target(tmp_path: Path) -> None:
    database_path = tmp_path / "cathedra.db"
    backup_directory = tmp_path / "backups"
    backup_directory.mkdir()
    safety_backup = backup_directory / "cathedra-backup-before-restore-test.db"
    with closing(sqlite3.connect(safety_backup)) as backup:
        backup.execute("CREATE TABLE records (name TEXT)")
        backup.execute("INSERT INTO records VALUES ('original')")
        backup.commit()
    begin_restore(database_path, safety_backup)
    database_path.write_bytes(b"incomplete database")

    assert recover_interrupted_restore(database_path, backup_directory)
    with closing(sqlite3.connect(database_path)) as database:
        assert database.execute("SELECT name FROM records").fetchall() == [("original",)]


def test_crashed_process_recovers_before_application_startup(tmp_path: Path) -> None:
    database_path = tmp_path / "cathedra.db"
    backup_directory = tmp_path / "backups"
    backup_directory.mkdir()
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    event.listen(
        engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        run_migrations(connection)
    engine.dispose()
    with closing(sqlite3.connect(database_path)) as database:
        database.execute("CREATE TABLE recovery_probe (value TEXT NOT NULL)")
        database.execute("INSERT INTO recovery_probe VALUES ('before restore')")
        database.commit()
        safety_backup = backup_directory / "cathedra-backup-before-restore-process.db"
        with closing(sqlite3.connect(safety_backup)) as backup:
            database.backup(backup)

    environment = {**os.environ, "CATHEDRA_DATA_DIR": str(tmp_path)}
    crash = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, sqlite3; from pathlib import Path; "
            "from app.restore_recovery import begin_restore; "
            "data = Path(os.environ['CATHEDRA_DATA_DIR']); "
            "begin_restore(data / 'cathedra.db', data / 'backups' / 'cathedra-backup-before-restore-process.db'); "
            "db = sqlite3.connect(data / 'cathedra.db'); "
            "db.execute(\"UPDATE recovery_probe SET value = 'interrupted'\"); db.commit(); db.close(); os._exit(23)",
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert crash.returncode == 23, crash.stderr
    startup = subprocess.run(
        [
            sys.executable,
            "-c",
            "from fastapi.testclient import TestClient; from app.main import app; "
            "client = TestClient(app); "
            "client.__enter__(); "
            "assert client.get('/api/v1/health').status_code == 200; "
            "client.__exit__(None, None, None); print('started')",
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert startup.returncode == 0, startup.stderr
    assert "started" in startup.stdout
    with closing(sqlite3.connect(database_path)) as database:
        assert database.execute("SELECT value FROM recovery_probe").fetchone() == (
            "before restore",
        )
    assert not restore_marker_path(database_path).exists()


def test_import_has_no_database_side_effects(tmp_path: Path) -> None:
    environment = {**os.environ, "CATHEDRA_DATA_DIR": str(tmp_path / "new-data")}
    imported = subprocess.run(
        [sys.executable, "-c", "import app.main; print('imported')"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stderr
    assert "imported" in imported.stdout
    assert not (tmp_path / "new-data").exists()

    started = subprocess.run(
        [
            sys.executable,
            "-c",
            "from fastapi.testclient import TestClient; from app.main import app; "
            "client = TestClient(app); "
            "client.__enter__(); "
            "assert client.get('/api/v1/health').status_code == 200; "
            "client.__exit__(None, None, None)",
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert started.returncode == 0, started.stderr
    assert (tmp_path / "new-data" / "cathedra.db").is_file()


def test_migration_failure_prevents_startup(tmp_path: Path) -> None:
    environment = {**os.environ, "CATHEDRA_DATA_DIR": str(tmp_path / "failed-data")}
    failed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from fastapi.testclient import TestClient; import app.main as main; "
            "main.run_migrations = lambda connection: (_ for _ in ()).throw(RuntimeError('migration failed')); "
            "client = TestClient(main.app); client.__enter__()",
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0
    assert "migration failed" in failed.stderr
