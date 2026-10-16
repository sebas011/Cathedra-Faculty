import os
from pathlib import Path

_configuration = Path(__file__).resolve().parents[2] / "APP_PRODUCT"
PRODUCT = "faculty"
if os.environ.get("CATHEDRA_PRODUCT", PRODUCT) != PRODUCT:
    raise RuntimeError("This application supports Cathedra Faculty only.")
if _configuration.exists() and _configuration.read_text(encoding="utf-8").strip() != PRODUCT:
    raise RuntimeError("Invalid Cathedra Faculty product configuration.")
PRODUCT_NAME = "Cathedra Faculty"


def verify_product(database) -> None:
    tables = {
        row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "cathedra_product" not in tables:
        raise ValueError(
            "This database has not been prepared for this Cathedra app. Use a verified Cathedra Faculty database."
        )
    identity = database.execute("SELECT product FROM cathedra_product WHERE id=1").fetchone()
    if identity != (PRODUCT,):
        raise ValueError("This database belongs to a different Cathedra app.")


def bind_empty_database(connection) -> None:
    tables = set(
        connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").scalars()
    )
    if "cathedra_product" in tables:
        identity = connection.exec_driver_sql(
            "SELECT product FROM cathedra_product WHERE id=1"
        ).scalar()
        if identity != PRODUCT:
            raise RuntimeError("This data directory belongs to another Cathedra app.")
        return
    for table in ("faculty_profiles", "local_users"):
        if (
            table in tables
            and connection.exec_driver_sql(f'SELECT COUNT(*) FROM "{table}"').scalar()
        ):
            raise RuntimeError(
                "Existing records need a verified Faculty database identity before startup."
            )
    connection.exec_driver_sql(
        "CREATE TABLE cathedra_product (id INTEGER PRIMARY KEY CHECK(id=1), product TEXT NOT NULL)"
    )
    connection.exec_driver_sql(
        "INSERT INTO cathedra_product (id, product) VALUES (1, ?)", (PRODUCT,)
    )
