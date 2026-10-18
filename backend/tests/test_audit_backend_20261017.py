import json
from datetime import date

import pytest
from fastapi import HTTPException

import app.main as main
import app.services.projection as projection_service
from app.expense_schemas import MonthlySalaryProjectionRead
from app.models import FacultyProfile, FacultyWorkload, SavedProjection, WorkloadApprovalRevision
from app.services.snapshots import load_approval_snapshot
from tests.test_expenses import create_faculty

SCOPE = {
    "academic_year": "2026-2027",
    "term": "First Semester",
    "period": "semester",
    "as_of": "2026-10-01",
}


def create_workload(client, faculty, *, term="First Semester", category="Regular Faculty"):
    response = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": faculty["id"],
            "academic_year": SCOPE["academic_year"],
            "term": term,
            "compensation_category": category,
            "assignments": [
                {
                    "course_code": "TEST",
                    "course_title": "Teaching",
                    "year_section": "1A",
                    "lecture_hours": 23,
                    "laboratory_hours": 0,
                }
            ],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_saved_projection_versions_and_legacy_defaults_preserve_values(client):
    saved = client.post("/api/v1/expenses/saved-projections", json=SCOPE).json()
    with main.SessionLocal() as db:
        record = db.get(SavedProjection, saved["id"])
        versioned = json.loads(record.projection_json)
        assert versioned.pop("schema_version") == 1
        assert versioned == saved["projection"]
        # This is also the pre-audit reader: the schema itself has not changed.
        assert (
            MonthlySalaryProjectionRead.model_validate_json(record.projection_json).model_dump(
                mode="json"
            )
            == saved["projection"]
        )
        record.projection_json = json.dumps(
            {"schema_version": 1, "projection": saved["projection"]}
        )
        db.commit()
    assert (
        client.get(f"/api/v1/expenses/saved-projections/{saved['id']}").json()["projection"]
        == saved["projection"]
    )
    with main.SessionLocal() as db:
        record = db.get(SavedProjection, saved["id"])
        legacy = saved["projection"].copy()
        legacy.pop("warnings")
        legacy.pop("teaching_details")
        record.projection_json = json.dumps(legacy)
        db.commit()
    result = client.get(f"/api/v1/expenses/saved-projections/{saved['id']}")
    assert result.status_code == 200
    assert result.json()["projection"] == {
        **saved["projection"],
        "warnings": [],
        "teaching_details": [],
    }
    assert client.get("/api/v1/expenses/saved-projections").status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        "broken",
        "[]",
        "null",
        "{}",
        '{"schema_version":2,"projection":{}}',
        '{"schema_version":true,"projection":{}}',
        '{"schema_version":1,"projection":{"included_count":3}}',
        '{"schema_version":1,"projection":NaN}',
    ],
)
def test_corrupt_saved_estimates_fail_explicitly_in_every_reader(client, payload):
    saved = client.post(
        "/api/v1/expenses/closeout-estimates",
        json={key: value for key, value in SCOPE.items() if key != "period"},
    ).json()
    with main.SessionLocal() as db:
        db.get(SavedProjection, saved["id"]).projection_json = payload
        db.commit()
    for endpoint, query in [
        (f"/api/v1/expenses/saved-projections/{saved['id']}", {}),
        ("/api/v1/expenses/saved-projections", {}),
        (
            "/api/v1/expenses/closeout-estimates",
            {
                "academic_year": SCOPE["academic_year"],
                "term": SCOPE["term"],
            },
        ),
    ]:
        result = client.get(endpoint, params=query)
        assert result.status_code == 409
        assert f"#{saved['id']}" in result.json()["detail"]
    with main.SessionLocal() as db:
        assert db.get(SavedProjection, saved["id"]).projection_json == payload


@pytest.mark.parametrize("payload", ["broken", "[]", "null", "{}", '{"faculty":{},"workload":{}}'])
def test_corrupt_approvals_fail_without_erasing_frozen_history(client, payload):
    faculty = create_faculty(client)
    workload = create_workload(client, faculty)
    with main.SessionLocal() as db:
        record = db.get(FacultyWorkload, workload["id"])
        record.workflow_status = "Approved"
        record.approval_snapshot = payload
        history = WorkloadApprovalRevision(
            workload_id=record.id,
            snapshot=payload,
            approved_by="test-admin",
            approved_at=date(2026, 10, 1),
        )
        db.add(history)
        db.commit()
        revision_id = history.id
    for endpoint in [
        f"/api/v1/workloads/{workload['id']}",
        f"/api/v1/workloads/{workload['id']}/approvals",
        "/api/v1/workloads",
        "/api/v1/workloads/page",
        "/api/v1/workloads/approved-summary",
    ]:
        response = client.get(endpoint)
        assert response.status_code == 409, (endpoint, response.text)
        assert "unreadable" in response.json()["detail"]
    with main.SessionLocal() as db:
        assert db.get(WorkloadApprovalRevision, revision_id).snapshot == payload
        assert db.get(FacultyWorkload, workload["id"]).approval_snapshot == payload


@pytest.mark.parametrize("value", [True, "12", [], float("inf"), 10**400])
def test_invalid_frozen_approval_numbers_fail_explicitly(value):
    payload = json.dumps(
        {
            "faculty": {"name": "Synthetic faculty"},
            "workload": {
                "total_weekly_hours": value,
                "overload_weekly_hours": 2,
                "estimated_teaching_pay_weekly": 100,
                "estimated_teaching_pay_term": 1800,
            },
        }
    )
    with pytest.raises(HTTPException) as caught:
        load_approval_snapshot(payload, label="Synthetic approval")
    assert caught.value.status_code == 409
    assert "unreadable" in caught.value.detail


def test_valid_legacy_approval_reads_preserve_frozen_values_and_bytes(client):
    faculty = create_faculty(client)
    workload = create_workload(client, faculty)
    endpoint = f"/api/v1/workloads/{workload['id']}"
    reviewed = client.post(f"{endpoint}/review", headers={"If-Match": str(workload["revision"])})
    assert reviewed.status_code == 200
    approved = client.post(
        f"{endpoint}/approve", headers={"If-Match": str(reviewed.json()["revision"])}
    )
    assert approved.status_code == 200
    snapshot = approved.json()["approval_snapshot"]
    snapshot.pop("teaching_allocation")
    snapshot.pop("correction_of_revision_id")
    snapshot.pop("correction_reason")
    payload = json.dumps(snapshot, indent=2)
    revision_id = client.get(f"{endpoint}/approvals").json()[0]["id"]
    with main.SessionLocal() as db:
        db.get(FacultyWorkload, workload["id"]).approval_snapshot = payload
        db.get(WorkloadApprovalRevision, revision_id).snapshot = payload
        db.get(FacultyProfile, faculty["id"]).monthly_salary = 1
        db.commit()
    assert client.get(endpoint).json()["approval_snapshot"] == snapshot
    assert client.get(f"{endpoint}/approvals").json()[0]["snapshot"] == snapshot
    summary = client.get("/api/v1/workloads/approved-summary").json()
    assert summary["term_pay"] == snapshot["workload"]["estimated_teaching_pay_term"]
    assert summary["items"][0]["allocation_basis"].startswith("Legacy approval")
    with main.SessionLocal() as db:
        assert db.get(FacultyWorkload, workload["id"]).approval_snapshot == payload
        assert db.get(WorkloadApprovalRevision, revision_id).snapshot == payload


def test_projection_calculates_each_workload_once_and_reconciles_college_splits(
    client, monkeypatch
):
    included = create_faculty(client, name="Included split", college="COEd")
    provisional = create_faculty(
        client, name="Uncertain status", college="CIT", service_status="To verify"
    )
    workload = create_workload(client, included)
    create_workload(client, provisional)
    with main.SessionLocal() as db:
        record = db.get(FacultyWorkload, workload["id"])
        record.imported_overload_hours = 17.75
        record.import_provenance = json.dumps(
            {
                "confirmed_course_resolution": {
                    "overload_components": [
                        {"college": "COEd", "hours": 9.25},
                        {"college": "CIT", "hours": 8.5},
                    ]
                }
            }
        )
        db.commit()
    calls = []
    original = projection_service.read_workload

    def counted(workload, faculty, settings):
        calls.append(workload.id)
        return original(workload, faculty, settings)

    monkeypatch.setattr(projection_service, "read_workload", counted)
    response = client.get("/api/v1/expenses/monthly-projection", params=SCOPE)
    assert response.status_code == 200
    result = response.json()
    assert len(calls) == len(set(calls)) == 2
    assert result["teaching_cost"]["workloads"] == 1
    assert result["provisional_teaching_cost"]["workloads"] == 1
    rate = included["monthly_salary"] * 12 * 0.000781
    colleges = {item["college"]: item for item in result["college_totals"]}
    assert colleges["COEd"]["term_teaching_cost"] == pytest.approx(9.25 * rate * 18)
    assert colleges["CIT"]["term_teaching_cost"] == pytest.approx(8.5 * rate * 18)
    assert (
        sum(item["term_teaching_cost"] for item in result["college_totals"])
        == result["teaching_cost"]["total_term_pay"]
    )
    filtered = client.get(
        "/api/v1/expenses/monthly-projection", params={**SCOPE, "college": "CIT"}
    ).json()
    assert filtered["included_count"] == 0
    assert filtered["teaching_cost"]["total_term_pay"] == colleges["CIT"]["term_teaching_cost"]


def test_verified_office_salary_and_grade_survive_unrelated_profile_edits(client):
    faculty = create_faculty(client)
    with main.SessionLocal() as db:
        record = db.get(FacultyProfile, faculty["id"])
        record.salary_source = "Office verified salary schedule"
        record.salary_grade = "SG 13"
        record.monthly_salary = 33333.33
        db.commit()
    current = client.get(f"/api/v1/faculty-profiles/{faculty['id']}").json()
    response = client.put(
        f"/api/v1/faculty-profiles/{faculty['id']}",
        json={**current, "remarks": "Contact details checked"},
        headers={"If-Match": str(current["revision"])},
    )
    assert response.status_code == 200
    assert response.json()["salary_grade"] == "SG 13"
    assert response.json()["monthly_salary"] == 33333.33
    assert response.json()["salary_source"] == current["salary_source"]


@pytest.mark.parametrize("changes", [{"salary_step": 2}, {"rank": "Professor I"}])
def test_verified_salary_rejects_appointment_drift_without_changing_revision(client, changes):
    faculty = create_faculty(client)
    with main.SessionLocal() as db:
        record = db.get(FacultyProfile, faculty["id"])
        record.salary_source = "Office verified salary schedule"
        record.monthly_salary = 33333.33
        db.commit()
    current = client.get(f"/api/v1/faculty-profiles/{faculty['id']}").json()
    response = client.put(
        f"/api/v1/faculty-profiles/{faculty['id']}",
        json={**current, **changes},
        headers={"If-Match": str(current["revision"])},
    )
    assert response.status_code == 409
    assert "office source" in response.json()["detail"]
    assert client.get(f"/api/v1/faculty-profiles/{faculty['id']}").json() == current


def test_verified_salary_rejects_unmapped_rank_grade_drift(client):
    faculty = create_faculty(client, rank="Special appointment", salary_grade="SG 12")
    with main.SessionLocal() as db:
        record = db.get(FacultyProfile, faculty["id"])
        record.salary_source = "Office verified salary schedule"
        record.monthly_salary = 33333.33
        db.commit()
    current = client.get(f"/api/v1/faculty-profiles/{faculty['id']}").json()
    response = client.put(
        f"/api/v1/faculty-profiles/{faculty['id']}",
        json={**current, "salary_grade": "SG 13"},
        headers={"If-Match": str(current["revision"])},
    )
    assert response.status_code == 409
    assert client.get(f"/api/v1/faculty-profiles/{faculty['id']}").json() == current
