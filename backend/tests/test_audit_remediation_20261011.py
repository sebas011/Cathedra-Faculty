import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.faculty_profiles import create_profile
from app.db import Base
from app.faculty_schemas import FacultyProfileCreate
from app.migrations import run_migrations
from app.models import FacultyProfile
from app.product import bind_empty_database
from maintenance_target import validate_target


def test_concurrent_profile_creation_returns_one_conflict(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'profiles.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    barrier = Barrier(2)

    class RacingSession(Session):
        checked = False

        def scalar(self, statement, *args, **kwargs):
            result = super().scalar(statement, *args, **kwargs)
            if not self.checked:
                self.checked = True
                barrier.wait(timeout=10)
            return result

    sessions = sessionmaker(bind=engine, class_=RacingSession, expire_on_commit=False)
    payload = FacultyProfileCreate(
        name="Concurrent Faculty",
        rank="Instructor I",
        employment_status="Full-time",
        college="CAS",
        department="BSAM",
    )

    def create():
        with sessions() as db:
            try:
                create_profile(payload, db, None)
                return 201
            except HTTPException as caught:
                assert "already exists" in caught.detail
                return caught.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: create(), range(2))) == [201, 409]
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(FacultyProfile)) == 1
    finally:
        engine.dispose()


def test_maintenance_explicit_current_folder_rejects_wrong_product_schema_and_path(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CATHEDRA_DATA_DIR", str(tmp_path))
    database = tmp_path / "cathedra.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        bind_empty_database(connection)
        run_migrations(connection)
    engine.dispose()
    assert validate_target(database) == database.resolve()
    other = tmp_path / "unrelated.db"
    other.write_bytes(database.read_bytes())
    with pytest.raises(ValueError, match="Select the current"):
        validate_target(other)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE cathedra_product SET product='other'")
    with pytest.raises(ValueError, match="verified Cathedra Faculty"):
        validate_target(database)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE cathedra_product SET product='faculty'")
        connection.execute("UPDATE schema_migrations SET name='unsupported' WHERE version=24")
    before = database.read_bytes()
    with pytest.raises(ValueError, match="complete migrations"):
        validate_target(database)
    assert database.read_bytes() == before
