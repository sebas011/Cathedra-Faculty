import sqlite3

import pytest
from sqlalchemy import create_engine, inspect

from app import product
from app.db import Base
from app.migrations import RETIRED_TABLES, migrate_remove_retired_feature_tables, run_migrations


def test_faculty_router_boundaries(client):
    assert client.get("/api/v1/health").json()["product"] == "faculty"
    for path in ("/faculty-profiles", "/workloads"):
        assert client.get("/api/v1" + path).status_code == 200
    for path in ("/fsdp", "/fsdp/summary", "/fsdp/grant-reviews", "/maintenance/exports/fsdp.csv"):
        assert client.get("/api/v1" + path).status_code == 404
    assert not any("fsdp" in path for path in client.get("/openapi.json").json()["paths"])


def test_wrong_product_backup_rejected():
    with sqlite3.connect(":memory:") as database:
        database.execute("CREATE TABLE cathedra_product (id INTEGER PRIMARY KEY, product TEXT)")
        database.execute("INSERT INTO cathedra_product VALUES (1, 'other-product')")
        with pytest.raises(ValueError, match="different"):
            product.verify_product(database)


def test_unmarked_backup_rejected():
    with sqlite3.connect(":memory:") as database:
        with pytest.raises(ValueError, match="verified Cathedra Faculty"):
            product.verify_product(database)


def test_fresh_schema_excludes_retired_tables():
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            run_migrations(connection)
            run_migrations(connection)
            assert not set(RETIRED_TABLES) & set(inspect(connection).get_table_names())
            assert (
                connection.exec_driver_sql("SELECT COUNT(*) FROM schema_migrations").scalar() == 24
            )
    finally:
        engine.dispose()


def test_cleanup_preserves_faculty_and_checks_all_tables_before_dropping():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE faculty_profiles (id INTEGER PRIMARY KEY, name TEXT)"
            )
            connection.exec_driver_sql(
                "INSERT INTO faculty_profiles VALUES (19, 'Synthetic Faculty')"
            )
            for table in RETIRED_TABLES:
                connection.exec_driver_sql(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
            connection.exec_driver_sql("INSERT INTO scholars VALUES (7)")
            with pytest.raises(RuntimeError, match="Preserve and export"):
                migrate_remove_retired_feature_tables(connection)
            assert set(RETIRED_TABLES) <= set(inspect(connection).get_table_names())
            connection.exec_driver_sql("DELETE FROM scholars")
            migrate_remove_retired_feature_tables(connection)
            migrate_remove_retired_feature_tables(connection)
            assert not set(RETIRED_TABLES) & set(inspect(connection).get_table_names())
            assert connection.exec_driver_sql("SELECT id, name FROM faculty_profiles").all() == [
                (19, "Synthetic Faculty")
            ]
    finally:
        engine.dispose()
