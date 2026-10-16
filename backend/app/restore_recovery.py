import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4


def restore_marker_path(database_path: Path) -> Path:
    return database_path.with_name(f".{database_path.name}.restore-pending")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def begin_restore(database_path: Path, safety_backup: Path) -> None:
    marker = restore_marker_path(database_path)
    if marker.exists():
        raise RuntimeError("An interrupted restore must be recovered before another restore.")
    temporary = marker.with_name(f"{marker.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(
                {"safety_backup": safety_backup.name, "sha256": file_digest(safety_backup)}, output
            )
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)


def finish_restore(database_path: Path) -> None:
    restore_marker_path(database_path).unlink(missing_ok=True)


def recover_interrupted_restore(database_path: Path, backup_directory: Path) -> bool:
    marker = restore_marker_path(database_path)
    if not marker.exists():
        return False
    payload = json.loads(marker.read_text(encoding="utf-8"))
    filename = payload["safety_backup"]
    if (
        not isinstance(filename, str)
        or not filename.startswith("cathedra-backup-before-restore-")
        or not filename.endswith(".db")
        or Path(filename).name != filename
    ):
        raise RuntimeError("The interrupted restore marker is invalid.")
    safety_backup = (backup_directory / filename).resolve()
    if (
        safety_backup.parent != backup_directory.resolve()
        or not safety_backup.is_file()
        or file_digest(safety_backup) != payload["sha256"]
    ):
        raise RuntimeError("The interrupted restore safety backup is missing or changed.")
    temporary = database_path.with_name(f".{database_path.name}.recovery-{uuid4().hex}.tmp")
    try:
        with closing(sqlite3.connect(f"{safety_backup.as_uri()}?mode=ro", uri=True)) as source:
            if (
                source.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or source.execute("PRAGMA foreign_key_check").fetchone() is not None
            ):
                raise RuntimeError("The interrupted restore safety backup is invalid.")
            with closing(sqlite3.connect(temporary)) as target:
                source.backup(target)
                if (
                    target.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or target.execute("PRAGMA foreign_key_check").fetchone() is not None
                ):
                    raise RuntimeError("Interrupted restore recovery failed verification.")
        for suffix in ("-wal", "-shm", "-journal"):
            database_path.with_name(f"{database_path.name}{suffix}").unlink(missing_ok=True)
        os.replace(temporary, database_path)
        finish_restore(database_path)
    finally:
        temporary.unlink(missing_ok=True)
    return True
