import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.main as main
from app.models import FacultyProfile, FacultyWorkload, SavedProjection, SemesterCloseoutEstimate

ENDPOINT = "/api/v1/expenses/closeout-estimates"
SCOPE = {"academic_year": "2026-2027", "term": "First Semester", "as_of": "2026-10-01"}


def add_workload(client, term="First Semester"):
    response = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Closeout Faculty",
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "salary_grade": "SG 12",
            "salary_step": 1,
            "college": "CAS",
            "department": "BSAM",
        },
    )
    assert response.status_code == 201
    faculty = response.json()
    response = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": faculty["id"],
            "academic_year": "2026-2027",
            "term": term,
            "compensation_category": "Regular Faculty",
            "assignments": [
                {
                    "course_code": "MATH",
                    "course_title": "Mathematics",
                    "year_section": "1A",
                    "lecture_hours": 23,
                    "laboratory_hours": 0,
                }
            ],
        },
    )
    assert response.status_code == 201
    return faculty, response.json()


def test_closeout_captures_once_and_keeps_original_estimate(client):
    faculty, workload = add_workload(client)
    query = {"academic_year": SCOPE["academic_year"], "term": SCOPE["term"]}
    assert client.get(ENDPOINT, params=query).json() is None
    response = client.post(ENDPOINT, json=SCOPE)
    assert response.status_code == 201
    captured = response.json()
    assert captured["closeout"] is True
    assert captured["projection"]["filters"]["college"] is None
    assert captured["projection"]["status_as_of"] == "2026-10-01"
    assert captured["projection"]["teaching_cost"]["total_term_pay"] > 0
    with main.SessionLocal() as db:
        db.get(FacultyProfile, faculty["id"]).monthly_salary += 1000
        assert db.get(FacultyWorkload, workload["id"]).workflow_status == "Draft"
        db.commit()
    assert client.post(ENDPOINT, json=SCOPE).status_code == 409
    assert client.get(ENDPOINT, params=query).json() == captured
    saved_endpoint = f"/api/v1/expenses/saved-projections/{captured['id']}"
    assert client.get(saved_endpoint).json() == captured
    assert client.get("/api/v1/expenses/saved-projections").json()[0]["closeout"] is True
    with main.SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SavedProjection)) == 1
        assert db.scalar(select(func.count()).select_from(SemesterCloseoutEstimate)) == 1
    assert client.get(ENDPOINT, params={**query, "term": "Second Semester"}).json() is None
    assert client.get(ENDPOINT, params={**query, "academic_year": "2027-2028"}).json() is None


def test_summer_closeout_uses_summer_basis_and_retains_warnings(client):
    add_workload(client, "Summer")
    response = client.post(ENDPOINT, json={**SCOPE, "term": "Summer"})
    assert response.status_code == 201
    saved = response.json()
    assert saved["period"] == "summer"
    assert saved["projection"]["salary_months"] == 0
    assert saved["projection"]["total_period_salary"] == 0
    assert saved["projection"]["teaching_details"][0]["weeks"] == 6
    assert saved["projection"]["warnings"]


def test_failed_closeout_link_rolls_back_snapshot(client, monkeypatch):
    original_commit = Session.commit

    def fail_closeout_commit(session):
        if any(isinstance(record, SemesterCloseoutEstimate) for record in session.new):
            raise IntegrityError("closeout insert", {}, Exception("conflict"))
        return original_commit(session)

    monkeypatch.setattr(Session, "commit", fail_closeout_commit)
    assert client.post(ENDPOINT, json=SCOPE).status_code == 409
    with main.SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SavedProjection)) == 0
        assert db.scalar(select(func.count()).select_from(SemesterCloseoutEstimate)) == 0


def test_staff_cannot_read_or_capture_closeout_estimates(client):
    response = client.post(
        "/api/v1/auth/users",
        json={
            "username": "closeout-staff",
            "password": "staff-password-123",
            "role": "staff",
        },
    )
    assert response.status_code == 201
    session = client.post(
        "/api/v1/auth/login",
        json={
            "username": "closeout-staff",
            "password": "staff-password-123",
        },
    ).json()
    client.headers.update({"Authorization": f"Bearer {session['token']}"})
    assert client.get(ENDPOINT, params={"academic_year": "2026-2027"}).status_code == 403
    assert client.post(ENDPOINT, json=SCOPE).status_code == 403
    client.headers.clear()
    assert client.post(ENDPOINT, json=SCOPE).status_code == 401


@pytest.mark.parametrize(
    "changes",
    [
        {"academic_year": "2026-2028"},
        {"academic_year": "invalid"},
        {"term": "yearly"},
        {"as_of": "invalid"},
        {"as_of": None},
    ],
)
def test_closeout_rejects_invalid_scope(client, changes):
    assert client.post(ENDPOINT, json={**SCOPE, **changes}).status_code == 422


def test_closeout_migration_preserves_saved_estimate():
    from sqlalchemy import create_engine, text

    from app.migrations import migrate_semester_closeout_estimates

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE saved_projections (id INTEGER PRIMARY KEY, projection_json TEXT)")
        )
        connection.execute(text("INSERT INTO saved_projections VALUES (1, 'original snapshot')"))
        migrate_semester_closeout_estimates(connection)
        migrate_semester_closeout_estimates(connection)
        assert (
            connection.execute(text("SELECT projection_json FROM saved_projections")).scalar_one()
            == "original snapshot"
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM semester_closeout_estimates")
            ).scalar_one()
            == 0
        )
    engine.dispose()
