import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.migrations import RETIRED_TABLES, run_migrations
from app.product import verify_product


def retained_snapshot(database):
    tables = sorted(
        row[0]
        for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if row[0] not in {*RETIRED_TABLES, "schema_migrations", "sqlite_sequence"}
    )
    result = {}
    for table in tables:
        rows = database.execute(f'SELECT * FROM "{table}"').fetchall()
        serialized = json.dumps(sorted(rows, key=repr), ensure_ascii=False, default=str)
        result[table] = {
            "rows": len(rows),
            "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        }
    return result


def verify_cleanup(source: Path, destination: Path):
    if destination.exists():
        raise ValueError("Use a new rehearsal destination; existing data is never overwritten.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original:
        verify_product(original)
        before = retained_snapshot(original)
        with closing(sqlite3.connect(destination)) as copy:
            original.backup(copy)
    engine = create_engine(f"sqlite:///{destination.resolve().as_posix()}")
    try:
        with engine.begin() as connection:
            run_migrations(connection)
            run_migrations(connection)
    finally:
        engine.dispose()
    with closing(sqlite3.connect(destination)) as migrated:
        after = retained_snapshot(migrated)
        assert after == before, "Retained records changed during cleanup."
        assert migrated.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert migrated.execute("PRAGMA foreign_key_check").fetchone() is None
        tables = {
            row[0] for row in migrated.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert not tables.intersection(RETIRED_TABLES)
        version = migrated.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    return {"schema_version": version, "retained_tables": after, "records_unchanged": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(verify_cleanup(arguments.source, arguments.destination), indent=2))
