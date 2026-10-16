import sqlite3
from pathlib import Path

from app.migrations import MIGRATIONS
from create_install_seed import PERSONNEL_TABLES, create_install_seed


def test_installation_seed_has_schema_but_no_office_data(tmp_path: Path) -> None:
    destination = tmp_path / "cathedra-seed.db"
    create_install_seed(destination)
    with sqlite3.connect(destination) as database:
        assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            database.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            == MIGRATIONS[-1][0]
        )
        assert all(
            database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            for table in PERSONNEL_TABLES
        )
