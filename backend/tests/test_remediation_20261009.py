import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

import app.api.auth as auth_api
import app.main as main
from app.db import Base
from app.faculty_status import KNOWN_TERM_STARTS, workload_term_status_conflict
from app.migrations import migrate_case_insensitive_usernames, run_migrations
from app.models import ActivityEvent, FacultyProfile, LocalSession, LocalUser


def profile_and_workload(
    client, category="Regular Faculty", hours=24, rank="Instructor I", term="First Semester"
):
    response = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Synthetic Faculty",
            "rank": rank,
            "employment_status": "Full-time",
            "college": "CAS",
            "department": "Mathematics",
        },
    )
    assert response.status_code == 201, response.text
    profile = response.json()
    response = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": profile["id"],
            "academic_year": "2026-2027",
            "term": term,
            "compensation_category": category,
            "assignments": [
                {
                    "course_code": "SYN101",
                    "course_title": "Synthetic Course",
                    "year_section": "1A",
                    "lecture_hours": hours,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return profile, response.json()


def transition(client, workload, action):
    return client.post(
        f"/api/v1/workloads/{workload['id']}/{action}",
        headers={"If-Match": str(workload["revision"])},
    )


@pytest.mark.parametrize("category,hours", [("Regular Faculty", 24), ("Internal Part-time", 6)])
@pytest.mark.parametrize("action", ["review", "approve"])
def test_missing_salary_blocks_paid_work_without_changing_workflow(client, category, hours, action):
    profile, workload = profile_and_workload(client, category, hours)
    if action == "approve":
        response = transition(client, workload, "review")
        assert response.status_code == 200
        workload = response.json()
    with main.SessionLocal() as db:
        db.execute(
            text("UPDATE faculty_profiles SET monthly_salary=NULL WHERE id=:id"),
            {"id": profile["id"]},
        )
        db.commit()
    response = transition(client, workload, action)
    assert response.status_code == 409
    assert "monthly salary" in response.json()["detail"]
    unchanged = client.get(f"/api/v1/workloads/{workload['id']}").json()
    assert unchanged["workflow_status"] == workload["workflow_status"]
    assert unchanged["revision"] == workload["revision"]
    assert unchanged["approval_snapshot"] is None
    assert client.get("/api/v1/workloads/approved-summary").json()["workloads"] == 0


@pytest.mark.parametrize("category,hours", [("Regular Faculty", 21), ("External Part-time", 6)])
def test_salary_independent_work_remains_approvable(client, category, hours):
    profile, workload = profile_and_workload(
        client, category, hours, rank="Unmapped Synthetic Rank"
    )
    assert profile["monthly_salary"] is None
    reviewed = transition(client, workload, "review")
    assert reviewed.status_code == 200
    approved = transition(client, reviewed.json(), "approve")
    assert approved.status_code == 200
    pay = approved.json()["approval_snapshot"]["workload"]["estimated_teaching_pay_term"]
    assert pay == 0 if category == "Regular Faculty" else pay > 0


def test_confirmed_imported_overload_requires_salary_even_with_few_course_hours(client):
    _, workload = profile_and_workload(client, hours=6, rank="Unmapped Synthetic Rank")
    with main.SessionLocal() as db:
        db.execute(
            text("UPDATE faculty_workloads SET imported_overload_hours=2 WHERE id=:id"),
            {"id": workload["id"]},
        )
        db.commit()
    assert transition(client, workload, "review").status_code == 409


@pytest.mark.parametrize("term", ["First Semester", "Second Semester", "Summer"])
@pytest.mark.parametrize("action", ["review", "approve"])
@pytest.mark.parametrize("office_selected", [False, True])
@pytest.mark.parametrize("eligible", [False, True])
def test_term_eligibility_is_checked_without_matching_office_period(
    client, term, action, office_selected, eligible
):
    profile, workload = profile_and_workload(client, term=term)
    if office_selected:
        response = client.put(
            "/api/v1/expenses/active-period",
            headers={"If-Match": "0"},
            json={
                "academic_year": "2026-2027",
                "term": "Second Semester" if term == "First Semester" else "First Semester",
            },
        )
        assert response.status_code == 200
    if action == "approve":
        reviewed = transition(client, workload, "review")
        assert reviewed.status_code == 200
        workload = reviewed.json()
    start = KNOWN_TERM_STARTS[("2026-2027", term)]
    effective = start + timedelta(days=1 if eligible else -1)
    changed = client.put(
        f"/api/v1/faculty-profiles/{profile['id']}",
        headers={"If-Match": str(profile["revision"])},
        json={
            **profile,
            "service_status": "Retired",
            "service_status_effective_date": effective.isoformat(),
        },
    )
    assert changed.status_code == 200, changed.text
    response = transition(client, workload, action)
    assert response.status_code == (200 if eligible else 409), response.text
    if not eligible:
        unchanged = client.get(f"/api/v1/workloads/{workload['id']}").json()
        assert unchanged["revision"] == workload["revision"]
        assert unchanged["workflow_status"] == workload["workflow_status"]


def test_historical_reapproval_preserves_original_snapshot(client):
    profile, workload = profile_and_workload(client)
    reviewed = transition(client, workload, "review").json()
    approved = transition(client, reviewed, "approve")
    assert approved.status_code == 200
    original = approved.json()
    changed = client.put(
        f"/api/v1/faculty-profiles/{profile['id']}",
        headers={"If-Match": str(profile["revision"])},
        json={
            **profile,
            "service_status": "Retired",
            "service_status_effective_date": "2027-01-01",
        },
    )
    assert changed.status_code == 200
    reopened = client.post(
        f"/api/v1/workloads/{workload['id']}/reopen",
        headers={"If-Match": str(original["revision"])},
        json={"reason": "Correct historical teaching details"},
    )
    assert reopened.status_code == 200, reopened.text
    reviewed = transition(client, reopened.json(), "review")
    assert reviewed.status_code == 200
    corrected = transition(client, reviewed.json(), "approve")
    assert corrected.status_code == 200
    with main.SessionLocal() as db:
        snapshots = (
            db.execute(text("SELECT snapshot FROM workload_approval_revisions ORDER BY id"))
            .scalars()
            .all()
        )
        assert len(snapshots) == 2
        assert json.loads(snapshots[0]) == original["approval_snapshot"]


@pytest.mark.parametrize("status", ["Inactive", "Retired", "Resigned"])
def test_missing_effective_date_requires_confirmation(status):
    profile = FacultyProfile(service_status=status, service_status_effective_date=None)
    assert workload_term_status_conflict(profile, "2026-2027", "Second Semester")


def test_unknown_calendar_retains_year_fallback():
    profile = FacultyProfile(
        service_status="Retired", service_status_effective_date=date(2027, 1, 1)
    )
    assert workload_term_status_conflict(profile, "2027-2028", "Second Semester")
    assert not workload_term_status_conflict(profile, "2025-2026", "First Semester")


def test_account_case_variant_race_has_one_success(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "accounts.db").as_posix())
    Base.metadata.create_all(engine)
    barrier = Barrier(2)
    original_hash = auth_api.password_hash

    def synchronized_hash(password):
        barrier.wait(timeout=10)
        return original_hash(password)

    monkeypatch.setattr(auth_api, "password_hash", synchronized_hash)

    def create(username):
        with Session(engine) as db:
            try:
                auth_api.create_user(
                    auth_api.UserCreate(
                        username=username, password="Synthetic-password-123", role="staff"
                    ),
                    db,
                    None,
                )
                return 201
            except HTTPException as caught:
                return caught.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            assert sorted(executor.map(create, ("OfficeStaff", "officestaff"))) == [201, 409]
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(LocalUser)) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("username", ["CASESTAFF", "CaseStaff", "casestaff"])
def test_login_and_duplicate_check_share_ascii_normalization(client, username):
    payload = {"username": "CaseStaff", "password": "Synthetic-password-123", "role": "staff"}
    assert client.post("/api/v1/auth/users", json=payload).status_code == 201
    assert (
        client.post("/api/v1/auth/login", json={**payload, "username": username}).status_code == 200
    )
    assert (
        client.post("/api/v1/auth/users", json={**payload, "username": username}).status_code == 409
    )


def test_non_ascii_usernames_follow_sqlite_identity_rules(client):
    for username in ("ÉStaff", "éstaff"):
        payload = {"username": username, "password": "Synthetic-password-123", "role": "staff"}
        assert client.post("/api/v1/auth/users", json=payload).status_code == 201
        assert (
            client.post("/api/v1/auth/login", json=payload).json()["user"]["username"] == username
        )


def test_username_migration_preserves_legacy_accounts_and_is_idempotent():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as db:
            db.exec_driver_sql(
                "CREATE TABLE local_users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT)"
            )
            db.exec_driver_sql(
                "INSERT INTO local_users VALUES (7, 'OfficeStaff', 'Preserved hash')"
            )
            migrate_case_insensitive_usernames(db)
            migrate_case_insensitive_usernames(db)
            assert tuple(db.exec_driver_sql("SELECT * FROM local_users").one()) == (
                7,
                "OfficeStaff",
                "Preserved hash",
            )
            with pytest.raises(IntegrityError):
                db.exec_driver_sql(
                    "INSERT INTO local_users VALUES (8, 'officestaff', 'Other hash')"
                )
    finally:
        engine.dispose()


def test_schema_23_collision_blocks_upgrade_without_merging_accounts():
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as db:
            run_migrations(db)
            db.exec_driver_sql("DELETE FROM schema_migrations WHERE version=24")
            db.exec_driver_sql("DROP INDEX uq_local_users_login_name")
            db.exec_driver_sql(
                "INSERT INTO local_users (username,password_hash,role,created_at) "
                "VALUES ('OfficeStaff','Hash1','staff',CURRENT_TIMESTAMP),"
                "('officestaff','Hash2','staff',CURRENT_TIMESTAMP)"
            )
            before = db.exec_driver_sql(
                "SELECT id,username,password_hash FROM local_users ORDER BY id"
            ).all()
        with pytest.raises(RuntimeError, match="account names conflict"):
            with engine.begin() as db:
                run_migrations(db)
        with engine.connect() as db:
            assert (
                db.exec_driver_sql(
                    "SELECT id,username,password_hash FROM local_users ORDER BY id"
                ).all()
                == before
            )
            assert (
                db.exec_driver_sql(
                    "SELECT COUNT(*) FROM schema_migrations WHERE version=24"
                ).scalar_one()
                == 0
            )
    finally:
        engine.dispose()


def test_account_status_changes_have_one_event_and_noops_have_none(client):
    staff = client.post(
        "/api/v1/auth/users",
        json={"username": "AuditStaff", "password": "Synthetic-password-123", "role": "staff"},
    ).json()
    endpoint = f"/api/v1/auth/users/{staff['id']}/status"

    def events():
        return [
            item
            for item in client.get("/api/v1/activity").json()
            if item["record_type"] == "local_users"
            and item["record_id"] == staff["id"]
            and item["operation"] == "Updated"
        ]

    for active, expected_events in ((False, 1), (False, 1), (True, 2), (True, 2)):
        result = client.put(endpoint, json={"active": active})
        assert result.status_code == 200 and result.json()["is_active"] is active
        history = events()
        assert len(history) == expected_events
        assert history[0]["changed_fields"] == ["is_active"]
        assert "Synthetic-password" not in json.dumps(history)
    assert any("Disabled" in item["action"] for item in events())
    assert any("Enabled" in item["action"] for item in events())
    admin = client.get("/api/v1/auth/me").json()
    before = len(client.get("/api/v1/activity").json())
    assert (
        client.put(f"/api/v1/auth/users/{admin['id']}/status", json={"active": False}).status_code
        == 409
    )
    assert len(client.get("/api/v1/activity").json()) == before


def test_status_and_session_revocation_roll_back_if_activity_fails(client):
    staff = client.post(
        "/api/v1/auth/users",
        json={"username": "RollbackStaff", "password": "Synthetic-password-123", "role": "staff"},
    ).json()
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "RollbackStaff", "password": "Synthetic-password-123"},
        ).status_code
        == 200
    )
    with main.SessionLocal() as db:
        db.execute(
            text(
                "CREATE TRIGGER reject_activity BEFORE INSERT ON activity_events BEGIN SELECT RAISE(ABORT, 'activity unavailable'); END"
            )
        )
        db.commit()
        db.info["audit_actor"] = (1, "test-admin")
        with pytest.raises(DBAPIError):
            auth_api.set_account_status(
                staff["id"], auth_api.AccountStatusUpdate(active=False), db, None
            )
        db.rollback()
        assert db.get(LocalUser, staff["id"]).is_active
        assert (
            db.scalar(
                select(func.count())
                .select_from(LocalSession)
                .where(LocalSession.user_id == staff["id"])
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ActivityEvent)
                .where(ActivityEvent.action.like("Disabled%"))
            )
            == 0
        )
