import pytest

import app.main as main
from app.models import FacultyWorkload
from tests.test_workload_preparations import assignment, create_workload, faculty_payload


@pytest.mark.parametrize(
    "category", ["Regular Faculty", "Internal Part-time", "External Part-time"]
)
@pytest.mark.parametrize("qualification", [None, "", "   ", "None", "Doctor", "Lawyer"])
def test_legacy_qualification_round_trip(client, category, qualification):
    faculty = client.post(
        "/api/v1/faculty-profiles", json=faculty_payload("Qualification Test")
    ).json()
    workload = create_workload(client, faculty["id"], [assignment("TEST101", "1A", 23)])
    with main.SessionLocal() as db:
        record = db.get(FacultyWorkload, workload["id"])
        record.professional_qualification = qualification
        record.compensation_category = category
        db.commit()
    saved = client.get(f"/api/v1/workloads/{workload['id']}").json()
    response = client.put(
        f"/api/v1/workloads/{workload['id']}",
        headers={"If-Match": str(saved["revision"])},
        json={
            "faculty_profile_id": faculty["id"],
            "academic_year": saved["academic_year"],
            "term": saved["term"],
            "compensation_category": category,
            "professional_qualification": saved["professional_qualification"],
            "assignments": saved["assignments"],
            "remarks": "Edited successfully",
        },
    )
    assert response.status_code == 200
    assert response.json()["professional_qualification"] == (
        qualification if qualification and qualification.strip() else "None"
    )
    assert response.json()["estimated_teaching_pay_weekly"] == pytest.approx(
        saved["estimated_teaching_pay_weekly"]
    )


def test_invalid_professional_qualification_is_rejected(client):
    faculty = client.post(
        "/api/v1/faculty-profiles", json=faculty_payload("Invalid Qualification")
    ).json()
    response = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": faculty["id"],
            "academic_year": "2026-2027",
            "term": "First Semester",
            "professional_qualification": "Unverified title",
            "assignments": [assignment("TEST101", "1A", 23)],
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("credential,other", [("CPA", None), ("Other", "Licensed engineer")])
def test_new_credentials_persist_without_rate_additions(client, credential, other):
    faculty = client.post(
        "/api/v1/faculty-profiles", json=faculty_payload("Credential Test")
    ).json()
    payload = {
        "faculty_profile_id": faculty["id"],
        "academic_year": "2026-2027",
        "term": "First Semester",
        "compensation_category": "External Part-time",
        "highest_qualification": "Masters",
        "professional_qualification": credential,
        "professional_qualification_other": other,
        "assignments": [assignment("TEST101", "1A", 3)],
    }
    response = client.post("/api/v1/workloads", json=payload)
    assert response.status_code == 201
    workload = response.json()
    settings = client.get("/api/v1/workloads/cost-settings").json()
    assert workload["compensation_hourly_rate"] == pytest.approx(
        settings["external_base_hourly_rate"] + settings["external_masters_increment"]
    )
    saved = client.get(f"/api/v1/workloads/{workload['id']}").json()
    assert saved["professional_qualification"] == credential
    assert saved["professional_qualification_other"] == other
    assert saved["highest_qualification"] == "Masters"
    updated = client.put(
        f"/api/v1/workloads/{workload['id']}",
        json={**payload, "professional_qualification": "None"},
        headers={"If-Match": str(saved["revision"])},
    )
    assert updated.status_code == 200
    assert updated.json()["professional_qualification_other"] is None


@pytest.mark.parametrize("other", [None, "", "   ", "x" * 201])
def test_other_credential_requires_bounded_description(client, other):
    faculty = client.post(
        "/api/v1/faculty-profiles", json=faculty_payload("Other Credential")
    ).json()
    response = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": faculty["id"],
            "academic_year": "2026-2027",
            "term": "First Semester",
            "professional_qualification": "Other",
            "professional_qualification_other": other,
            "assignments": [assignment("TEST101", "1A", 3)],
        },
    )
    assert response.status_code == 422
