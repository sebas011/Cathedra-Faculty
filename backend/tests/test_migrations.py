from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

import app.main as main
import app.models  # noqa: F401
from app.db import Base
from app.migrations import (
    migrate_faculty_campus,
    migrate_faculty_no_teaching_confirmations,
    migrate_faculty_profile_roster_fields,
    migrate_faculty_status_effective_date,
    migrate_other_professional_credential,
    migrate_semester_overload_budgets,
    migrate_structured_activity,
    run_migrations,
)


def test_activity_upgrade_preserves_legacy_history():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE activity_events (id INTEGER PRIMARY KEY, username VARCHAR(80), action VARCHAR(160), area VARCHAR(80))"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO activity_events (id, username, action, area) VALUES (1, 'admin', 'Old action', 'Faculty Profiles')"
                )
            )
            migrate_structured_activity(connection)
            migrate_structured_activity(connection)
            row = connection.execute(
                text(
                    "SELECT action, record_type, record_id, operation, changed_fields FROM activity_events WHERE id = 1"
                )
            ).one()
            assert tuple(row) == ("Old action", None, None, None, None)
    finally:
        engine.dispose()


def test_other_credential_upgrade_preserves_existing_records():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE faculty_workloads (id INTEGER PRIMARY KEY, professional_qualification VARCHAR(30))"
                )
            )
            connection.execute(text("INSERT INTO faculty_workloads VALUES (1, 'Doctor')"))
            migrate_other_professional_credential(connection)
            migrate_other_professional_credential(connection)
            assert tuple(
                connection.execute(
                    text(
                        "SELECT professional_qualification, professional_qualification_other FROM faculty_workloads"
                    )
                ).one()
            ) == ("Doctor", None)
    finally:
        engine.dispose()


def test_current_schema_migration_is_recorded_once() -> None:
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(bind=engine)

        with engine.begin() as connection:
            run_migrations(connection)
            run_migrations(connection)
            migrations = connection.execute(
                text("SELECT version, name FROM schema_migrations ORDER BY version")
            ).all()

        assert migrations == [
            (1, "current-schema"),
            (2, "workload-approval-workflow"),
            (3, "scholar-requirements"),
            (4, "standard-teaching-weeks"),
            (5, "workload-source-values"),
            (6, "other-professional-credential"),
            (7, "qualification-rate-drafts"),
            (8, "participation-institution"),
            (9, "approval-revisions"),
            (10, "record-revisions"),
            (11, "account-lifecycle"),
            (12, "structured-activity"),
            (13, "faculty-campus"),
            (14, "semester-overload-budgets"),
            (15, "faculty-no-teaching-confirmations"),
            (16, "confirmation-period-index"),
            (17, "faculty-profile-roster-fields"),
            (18, "faculty-status-effective-date"),
            (19, "saved-projections"),
            (20, "semester-closeout-estimates"),
            (21, "remove-retired-feature-tables"),
            (22, "shared-setting-revisions"),
            (23, "deleted-resource-revisions"),
            (24, "case-insensitive-usernames"),
        ]
        with engine.connect() as connection:
            columns = connection.execute(
                text("PRAGMA table_info(faculty_no_teaching_confirmations)")
            ).all()
            assert next(column for column in columns if column[1] == "confirmed_at")[4] is not None
    finally:
        engine.dispose()


def test_no_teaching_confirmation_migration_preserves_existing_faculty():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE faculty_profiles (id INTEGER PRIMARY KEY, name VARCHAR(200))")
            )
            connection.execute(text("INSERT INTO faculty_profiles VALUES (7, 'Existing faculty')"))
            migrate_faculty_no_teaching_confirmations(connection)
            migrate_faculty_no_teaching_confirmations(connection)
            assert connection.execute(text("SELECT id, name FROM faculty_profiles")).all() == [
                (7, "Existing faculty")
            ]
            assert (
                connection.execute(
                    text("SELECT COUNT(*) FROM faculty_no_teaching_confirmations")
                ).scalar_one()
                == 0
            )
    finally:
        engine.dispose()


def test_overload_budget_upgrade_seeds_only_matching_office_period():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE projection_settings (id INTEGER PRIMARY KEY, academic_year VARCHAR(20), term VARCHAR(40))"
                )
            )
            connection.execute(
                text("INSERT INTO projection_settings VALUES (1, '2026-2027', 'First Semester')")
            )
            migrate_semester_overload_budgets(connection)
            migrate_semester_overload_budgets(connection)
            assert connection.execute(
                text("SELECT academic_year, term, amount_centavos FROM semester_overload_budgets")
            ).all() == [("2026-2027", "First Semester", 1607680424)]
            connection.execute(
                text("UPDATE semester_overload_budgets SET amount_centavos = 1500000000")
            )
            migrate_semester_overload_budgets(connection)
            assert (
                connection.execute(
                    text("SELECT amount_centavos FROM semester_overload_budgets")
                ).scalar_one()
                == 1500000000
            )
            connection.execute(text("DELETE FROM semester_overload_budgets"))
            connection.execute(text("UPDATE projection_settings SET academic_year = '2027-2028'"))
            migrate_semester_overload_budgets(connection)
            assert (
                connection.execute(
                    text("SELECT COUNT(*) FROM semester_overload_budgets")
                ).scalar_one()
                == 0
            )
    finally:
        engine.dispose()


def test_faculty_campus_upgrade_preserves_existing_profiles():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE faculty_profiles (id INTEGER PRIMARY KEY, name VARCHAR(200))")
            )
            connection.execute(text("INSERT INTO faculty_profiles VALUES (1, 'Existing faculty')"))
            migrate_faculty_campus(connection)
            migrate_faculty_campus(connection)
            assert tuple(
                connection.execute(
                    text("SELECT name, campus FROM faculty_profiles WHERE id = 1")
                ).one()
            ) == ("Existing faculty", None)
    finally:
        engine.dispose()


def test_faculty_roster_upgrade_preserves_existing_profiles():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE faculty_profiles (id INTEGER PRIMARY KEY, name VARCHAR(200))")
            )
            connection.execute(text("INSERT INTO faculty_profiles VALUES (1, 'Existing faculty')"))
            migrate_faculty_profile_roster_fields(connection)
            migrate_faculty_profile_roster_fields(connection)
            row = connection.execute(
                text(
                    "SELECT name, service_status, item_number, bachelors_degree, masters_degree, doctoral_degree, eligibility, remarks FROM faculty_profiles WHERE id=1"
                )
            ).one()
            assert tuple(row) == ("Existing faculty", "Active", None, None, None, None, None, None)
    finally:
        engine.dispose()


def test_faculty_status_date_upgrade_preserves_existing_profiles():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE faculty_profiles (id INTEGER PRIMARY KEY, service_status VARCHAR(20))"
                )
            )
            connection.execute(text("INSERT INTO faculty_profiles VALUES (1, 'Retired')"))
            migrate_faculty_status_effective_date(connection)
            migrate_faculty_status_effective_date(connection)
            assert tuple(
                connection.execute(
                    text(
                        "SELECT service_status, service_status_effective_date FROM faculty_profiles WHERE id=1"
                    )
                ).one()
            ) == ("Retired", None)
    finally:
        engine.dispose()


def test_teaching_weeks_upgrade_preserves_custom_schedules():
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            run_migrations(connection)
            connection.execute(
                text(
                    "INSERT INTO workload_cost_settings (id, overload_hourly_rate, internal_monthly_equivalent_hours, external_base_hourly_rate, external_masters_increment, external_doctorate_increment, external_doctor_increment, external_lawyer_increment, first_semester_weeks, second_semester_weeks, summer_weeks, updated_at) VALUES (1, 0, 173.33, 273.77, 0, 0, 0, 0, 18, 20, 0, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(text("DELETE FROM schema_migrations WHERE version = 4"))
            run_migrations(connection)
            assert tuple(
                connection.execute(
                    text(
                        "SELECT first_semester_weeks, second_semester_weeks, summer_weeks FROM workload_cost_settings"
                    )
                ).one()
            ) == (18, 20, 6)
            connection.execute(text("UPDATE workload_cost_settings SET summer_weeks = 8"))
            run_migrations(connection)
            assert (
                connection.execute(
                    text("SELECT summer_weeks FROM workload_cost_settings")
                ).scalar_one()
                == 8
            )
    finally:
        engine.dispose()


def test_confirmation_period_index_upgrade_preserves_records() -> None:
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            run_migrations(connection)
            connection.execute(
                text(
                    "INSERT INTO faculty_profiles "
                    "(id, name, rank, employment_status, college, department, data_source, created_at, updated_at) "
                    "VALUES (1, 'Example Faculty', 'Instructor I', 'Full-time', 'CAS', 'BSAM', "
                    "'Cathedra', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO faculty_no_teaching_confirmations "
                    "(faculty_id, academic_year, term, confirmed_by) "
                    "VALUES (1, '2026-2027', 'First Semester', 'admin')"
                )
            )
            connection.execute(
                text("DROP INDEX ix_faculty_no_teaching_confirmations_period_faculty")
            )
            connection.execute(text("DELETE FROM schema_migrations WHERE version = 16"))
            run_migrations(connection)
            run_migrations(connection)
            assert connection.execute(
                text(
                    "SELECT faculty_id, academic_year, term FROM faculty_no_teaching_confirmations"
                )
            ).all() == [(1, "2026-2027", "First Semester")]
            plan = connection.execute(
                text(
                    "EXPLAIN QUERY PLAN SELECT faculty_id FROM faculty_no_teaching_confirmations "
                    "WHERE academic_year = '2026-2027' AND term = 'First Semester'"
                )
            ).all()
            assert any(
                "ix_faculty_no_teaching_confirmations_period_faculty" in row[3] for row in plan
            )
    finally:
        engine.dispose()


def test_newer_database_blocks_startup_before_schema_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "cathedra.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL)"
            )
        )
        connection.execute(text("INSERT INTO schema_migrations VALUES (999, 'future-version')"))
    monkeypatch.setattr(main, "DB_PATH", database_path)
    monkeypatch.setattr(main, "engine", engine)
    with pytest.raises(RuntimeError, match="not supported"):
        main.initialize_database()
    assert inspect(engine).get_table_names() == ["schema_migrations"]
    engine.dispose()


def test_mismatched_migration_name_is_rejected() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL)"
                )
            )
            connection.execute(text("INSERT INTO schema_migrations VALUES (1, 'unexpected')"))
            with pytest.raises(RuntimeError, match="unexpected name"):
                run_migrations(connection)
    finally:
        engine.dispose()


def test_shutdown_releases_database_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_path = tmp_path / "cathedra.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        monkeypatch.setattr(main, "DB_PATH", database_path)
        monkeypatch.setattr(main, "engine", engine)
        from sqlalchemy.orm import sessionmaker

        monkeypatch.setattr(main, "SessionLocal", sessionmaker(bind=engine))
        with TestClient(main.app, base_url="http://127.0.0.1") as client:
            assert client.get("/api/v1/health").status_code == 200
        database_path.unlink()
        assert not database_path.exists()
    finally:
        engine.dispose()
