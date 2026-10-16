import json
from datetime import date, timedelta

from sqlalchemy import select

import app.main as main
from app.models import (
    FacultyNoTeachingConfirmation,
    FacultyProfile,
    FacultyWorkload,
    ProjectionSettings,
)


def test_verification_queue_identifies_current_gaps_without_changing_records(client):
    with main.SessionLocal() as db:
        profile = FacultyProfile(
            name="Profile Needs Details",
            rank="Instructor I",
            employment_status="",
            college="",
            department="",
            salary_step=1,
        )
        db.add(profile)
        db.flush()
        workload = FacultyWorkload(
            faculty_profile_id=profile.id,
            academic_year="2026-2027",
            term="First Semester",
            workflow_status="Reopened",
            import_provenance=json.dumps({"batch_id": "example", "projection_rows": []}),
        )
        db.add(workload)
        db.commit()
        profile_id, workload_id = profile.id, workload.id

    response = client.get("/api/v1/verification")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"] == {"Faculty Profile": 1, "Faculty Workload": 1}
    assert body["total"] == 2
    assert {item["action_path"] for item in body["items"]} == {
        f"/faculty-profiles/{profile_id}",
        f"/workload/{workload_id}",
    }
    assert any(
        "No reliable overload-projection source row linked" in item["issues"]
        for item in body["items"]
    )
    assert client.get("/api/v1/verification").json() == body


def test_verification_queue_requires_sign_in_and_does_not_claim_clean_on_bad_provenance(client):
    with main.SessionLocal() as db:
        profile = FacultyProfile(
            name="Valid Profile",
            rank="Instructor I",
            employment_status="Full-time",
            college="CAS",
            department="BSAM",
            salary_step=1,
            monthly_salary=34000,
        )
        db.add(profile)
        db.flush()
        db.add(
            FacultyWorkload(
                faculty_profile_id=profile.id,
                academic_year="2026-2027",
                term="Second Semester",
                import_provenance="{broken",
                workflow_status="Draft",
            )
        )
        db.commit()
    items = client.get("/api/v1/verification").json()["items"]
    assert len(items) == 1
    assert items[0]["issues"] == ["Import source information could not be read"]
    client.headers.clear()
    assert client.get("/api/v1/verification").status_code == 401


def test_staff_can_review_gaps_without_receiving_salary_values(client):
    with main.SessionLocal() as db:
        db.add(
            FacultyProfile(
                name="Staff Visible Gap",
                rank="Instructor I",
                employment_status="Full-time",
                college="CAS",
                department="",
                salary_step=1,
                monthly_salary=54371,
            )
        )
        db.commit()
    created = client.post(
        "/api/v1/auth/users",
        json={
            "username": "verification-staff",
            "password": "temporary-password-123",
            "role": "staff",
        },
    )
    assert created.status_code == 201
    session = client.post(
        "/api/v1/auth/login",
        json={
            "username": "verification-staff",
            "password": "temporary-password-123",
        },
    ).json()
    token = session["token"]
    changed = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "temporary-password-123",
            "new_password": "permanent-password-123",
        },
    )
    assert changed.status_code == 204
    token = client.post(
        "/api/v1/auth/login",
        json={
            "username": "verification-staff",
            "password": "permanent-password-123",
        },
    ).json()["token"]
    response = client.get("/api/v1/verification", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert "54371" not in response.text
    assert "monthly_salary" not in response.text


def test_complete_records_do_not_get_false_verification_flags(client):
    with main.SessionLocal() as db:
        profile = FacultyProfile(
            name="Complete Faculty",
            rank="Instructor I",
            employment_status="Full-time",
            college="CAS",
            department="BSAM",
            salary_step=1,
            monthly_salary=54371,
        )
        db.add(profile)
        db.flush()
        db.add(
            FacultyWorkload(
                faculty_profile_id=profile.id,
                academic_year="2026-2027",
                term="First Semester",
                workflow_status="Approved",
                import_provenance=json.dumps(
                    {
                        "batch_id": "example",
                        "projection_rows": [{"row": 1}],
                    }
                ),
            )
        )
        db.commit()
    assert client.get("/api/v1/verification").json()["total"] == 0


def test_active_faculty_without_current_workload_is_marked_for_review(client):
    with main.SessionLocal() as db:
        db.add(ProjectionSettings(id=1, academic_year="2026-2027", term="First Semester"))
        db.add_all(
            [
                FacultyProfile(
                    name="Needs workload review",
                    rank="Instructor I",
                    employment_status="Full-time",
                    college="CAS",
                    department="BSAM",
                    monthly_salary=34000,
                    service_status="Active",
                ),
                FacultyProfile(
                    name="Retired colleague",
                    rank="Instructor I",
                    employment_status="Full-time",
                    college="CAS",
                    department="BSAM",
                    monthly_salary=34000,
                    service_status="Retired",
                ),
                FacultyProfile(
                    name="Confirmed not teaching",
                    rank="Instructor I",
                    employment_status="Full-time",
                    college="CAS",
                    department="BSAM",
                    monthly_salary=34000,
                    service_status="Active",
                ),
            ]
        )
        db.flush()
        confirmed_id = db.scalar(
            select(FacultyProfile.id).where(FacultyProfile.name == "Confirmed not teaching")
        )
        db.add(
            FacultyNoTeachingConfirmation(
                faculty_id=confirmed_id,
                academic_year="2026-2027",
                term="First Semester",
                confirmed_by="test-admin",
            )
        )
        db.commit()
    items = client.get("/api/v1/verification", params={"area": "Faculty Profile"}).json()["items"]
    assert [item["name"] for item in items] == ["Needs workload review", "Retired colleague"]
    assert "Faculty status effective date needs confirmation" in next(
        item["issues"] for item in items if item["name"] == "Retired colleague"
    )
    assert "No workload recorded for 2026-2027 First Semester" in items[0]["issues"]


def test_verification_queue_paginates_and_filters_without_changing_overall_counts(client):
    with main.SessionLocal() as db:
        db.add_all(
            [
                FacultyProfile(
                    name=f"Gap {number:02d}",
                    rank="Instructor I",
                    employment_status="",
                    college="",
                    department="",
                    salary_step=1,
                )
                for number in range(11)
            ]
        )
        db.commit()

    first = client.get("/api/v1/verification", params={"page_size": 10}).json()
    second = client.get("/api/v1/verification", params={"page_size": 10, "page": 2}).json()
    assert first["total"] == first["matching_total"] == 11
    assert first["counts"] == {"Faculty Profile": 11, "Faculty Workload": 0}
    assert len(first["items"]) == 10
    assert [item["name"] for item in second["items"]] == ["Gap 10"]
    assert second["page"] == 2

    filtered = client.get(
        "/api/v1/verification",
        params={
            "area": "Faculty Profile",
            "search": "Gap 10",
            "page_size": 10,
        },
    ).json()
    assert filtered["total"] == 11
    assert filtered["matching_total"] == 1
    assert [item["name"] for item in filtered["items"]] == ["Gap 10"]
    other_area = client.get("/api/v1/verification", params={"area": "Faculty Workload"}).json()
    assert other_area["total"] == 11
    assert other_area["matching_total"] == 0
    assert other_area["items"] == []
    assert client.get("/api/v1/verification", params={"page": 0}).status_code == 422
    assert client.get("/api/v1/verification", params={"page_size": 101}).status_code == 422


def test_effectively_inactive_faculty_leave_all_verification_areas(client):
    yesterday = date.today() - timedelta(days=1)
    tomorrow = date.today() + timedelta(days=1)
    with main.SessionLocal() as db:
        db.add_all(
            [
                FacultyProfile(
                    name=f"Past {status}",
                    rank="Instructor I",
                    employment_status="",
                    college="",
                    department="",
                    service_status=status,
                    service_status_effective_date=yesterday,
                )
                for status in ("Inactive", "Retired", "Resigned")
            ]
        )
        db.add(
            FacultyProfile(
                name="Future Retirement",
                rank="Instructor I",
                employment_status="",
                college="",
                department="",
                service_status="Retired",
                service_status_effective_date=tomorrow,
            )
        )
        db.add(
            FacultyProfile(
                name="Retirement Date Missing",
                rank="Instructor I",
                employment_status="",
                college="",
                department="",
                service_status="Retired",
            )
        )
        db.flush()
        retired_id = db.scalar(
            select(FacultyProfile.id).where(FacultyProfile.name == "Past Retired")
        )
        db.add(
            FacultyWorkload(
                faculty_profile_id=retired_id,
                academic_year="2025-2026",
                term="First Semester",
                workflow_status="Reopened",
            )
        )
        db.commit()

    result = client.get("/api/v1/verification").json()
    assert result["counts"] == {"Faculty Profile": 2, "Faculty Workload": 0}
    assert [item["name"] for item in result["items"] if item["area"] == "Faculty Profile"] == [
        "Future Retirement",
        "Retirement Date Missing",
    ]
    assert all(item["name"] != "Past Retired" for item in result["items"])
    assert (
        client.get("/api/v1/verification", params={"search": "Past Inactive"}).json()[
            "matching_total"
        ]
        == 0
    )
