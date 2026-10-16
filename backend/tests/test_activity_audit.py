import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import app.main as main
from app.models import ActivityEvent, FacultyProfile


def test_activity_has_record_identity_and_only_changed_field_names(client):
    created = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Audit faculty",
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "college": "CAS",
            "department": "Mathematics",
        },
    )
    assert created.status_code == 201
    faculty = created.json()
    payload = {
        key: faculty[key]
        for key in (
            "name",
            "rank",
            "employment_status",
            "college",
            "department",
            "salary_grade",
            "salary_step",
            "monthly_salary",
        )
    }
    payload["rank"] = "Instructor II"
    updated = client.put(
        f"/api/v1/faculty-profiles/{faculty['id']}",
        json=payload,
        headers={"If-Match": str(faculty["revision"])},
    )
    assert updated.status_code == 200
    events = client.get("/api/v1/activity").json()
    change = next(
        event
        for event in events
        if event["record_type"] == "faculty_profiles" and event["operation"] == "Updated"
    )
    assert change["record_id"] == faculty["id"]
    assert "rank" in change["changed_fields"]
    assert "Instructor II" not in json.dumps(change)


def test_audit_insert_failure_rolls_back_record_change(client):
    with main.SessionLocal() as db:
        db.execute(
            text(
                "CREATE TRIGGER reject_activity BEFORE INSERT ON activity_events "
                "BEGIN SELECT RAISE(ABORT, 'activity unavailable'); END"
            )
        )
        db.commit()
        db.info["audit_actor"] = (1, "test-admin")
        db.add(
            FacultyProfile(
                name="Uncommitted faculty",
                rank="Instructor I",
                employment_status="Full-time",
                college="CAS",
                department="Mathematics",
            )
        )
        with pytest.raises(DBAPIError):
            db.commit()
        db.rollback()
        db.execute(text("DROP TRIGGER reject_activity"))
        db.commit()
        assert db.query(FacultyProfile).filter_by(name="Uncommitted faculty").first() is None
        assert (
            db.query(ActivityEvent).filter_by(action="Created Faculty Profiles #1").first() is None
        )


def test_password_activity_never_contains_secret(client):
    response = client.post(
        "/api/v1/auth/users",
        json={
            "username": "audit-staff",
            "password": "private-password-123",
            "role": "staff",
        },
    )
    assert response.status_code == 201
    history = client.get("/api/v1/activity").json()
    event = next(item for item in history if item["area"] == "Local Accounts")
    assert "credentials" in event["changed_fields"]
    assert "password_hash" not in json.dumps(event)
    assert "private-password-123" not in json.dumps(event)
