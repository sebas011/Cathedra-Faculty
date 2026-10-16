"""Shared target checks for the historical, operator-reviewed maintenance tools."""

import os
import sqlite3
from pathlib import Path

from app.migrations import MIGRATIONS


def validate_target(database: Path, *, allow_rehearsal: bool = False) -> Path:
    database = database.expanduser().resolve(strict=True)
    root = Path(__file__).resolve().parents[1]
    known = {
        (root / "data/cathedra.db").resolve(),
        (Path.home() / "Cathedra-Faculty/data/cathedra.db").resolve(),
        (Path.home() / "AppData/Local/Cathedra/cathedra.db").resolve(),
    }
    if os.environ.get("CATHEDRA_DATA_DIR"):
        known.add((Path(os.environ["CATHEDRA_DATA_DIR"]).expanduser() / "cathedra.db").resolve())
    if database not in known and not (
        allow_rehearsal and database.is_relative_to((root / "backups").resolve())
    ):
        raise ValueError(
            "Select the current Cathedra data folder with CATHEDRA_DATA_DIR, or an allowed rehearsal copy."
        )
    # Read-only validation precedes backups, reports and write transactions.
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "cathedra_product" not in tables or connection.execute(
            "SELECT product FROM cathedra_product WHERE id=1"
        ).fetchone() != ("faculty",):
            raise ValueError("Maintenance requires a verified Cathedra Faculty database.")
        expected = [(version, name) for version, name, _ in MIGRATIONS]
        if (
            "schema_migrations" not in tables
            or connection.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            ).fetchall()
            != expected
        ):
            raise ValueError(
                "Open a disposable copy with this Cathedra version to complete migrations before maintenance."
            )
    return database
