import os
import sqlite3
import sys
from contextlib import closing
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine

from app.db import Base
from app.migrations import run_migrations
from app.product import bind_empty_database

import_module("app.models")


PERSONNEL_TABLES = (
    "faculty_profiles",
    "faculty_workloads",
    "teaching_assignments",
    "local_users",
    "local_sessions",
    "activity_events",
    "workload_approval_revisions",
)


def create_install_seed(destination: Path) -> None:
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.stem}-{uuid4().hex}.db")
    engine = create_engine(f"sqlite:///{temporary.as_posix()}")
    try:
        Base.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            run_migrations(connection)
            bind_empty_database(connection)
        engine.dispose()
        with closing(sqlite3.connect(temporary)) as database:
            if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Installation seed failed integrity verification.")
            if any(
                database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in PERSONNEL_TABLES
            ):
                raise RuntimeError("Installation seed contains office or account records.")
        os.replace(temporary, destination)
    finally:
        engine.dispose()
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    create_install_seed(Path(sys.argv[1]))
