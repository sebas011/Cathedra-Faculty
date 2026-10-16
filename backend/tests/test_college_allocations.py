import json
from types import SimpleNamespace

import pytest

import app.main as main
from app.api.expenses import teaching_allocations
from app.api.workload import frozen_teaching_allocations
from app.models import FacultyWorkload, WorkloadApprovalRevision
from tests.test_expenses import create_faculty


def allocation_result(provenance, hours=17.75, term_pay=31950):
    return teaching_allocations(
        SimpleNamespace(import_provenance=provenance),
        SimpleNamespace(college="COEd", name="Example Faculty"),
        SimpleNamespace(
            compensation_category="Regular Faculty",
            overload_weekly_hours=hours,
            estimated_teaching_pay_weekly=hours * 100,
            estimated_teaching_pay_term=term_pay,
        ),
    )


def test_frozen_allocation_requires_paid_hours_to_reconcile():
    snapshot = {
        "teaching_allocation": {
            "allocations": [
                {"college": "CAS", "paid_hours": 1, "weekly_pay": 50, "term_pay": 900},
            ]
        }
    }
    allocations, basis, warning = frozen_teaching_allocations(snapshot, "CAS", 50, 900, 2)
    assert basis.startswith("Legacy approval")
    assert allocations[0]["paid_hours"] == 2
    assert warning


@pytest.mark.parametrize(
    "components",
    [
        [{"college": "COEd", "hours": 9.25}, {"college": "CIT", "hours": 9}],
        [{"college": "Unknown", "hours": 17.75}],
        [{"college": "CIT", "hours": -1}],
        [{"college": "CIT", "hours": True}],
        [{"college": "CIT", "hours": float("nan")}],
        [{"college": "CIT", "hours": float("inf")}],
        [{"college": "CIT", "hours": "17.75"}],
        [],
        None,
    ],
)
def test_invalid_allocations_preserve_pay_with_warning(components):
    allocations, basis, warning = allocation_result(
        json.dumps({"confirmed_course_resolution": {"overload_components": components}})
    )
    assert allocations == [
        {"college": "COEd", "paid_hours": 17.75, "weekly_pay": 1775, "term_pay": 31950}
    ]
    assert warning and "home college" in warning
    assert "Home college" in basis


@pytest.mark.parametrize(
    "provenance", ["broken", "[]", "null", '{"confirmed_course_resolution":null}']
)
def test_malformed_provenance_does_not_break_projection(provenance):
    allocations, _, warning = allocation_result(provenance)
    assert allocations[0]["term_pay"] == 31950
    assert warning


def test_combines_college_aliases_and_retains_unconfigured_term():
    provenance = json.dumps(
        {
            "confirmed_course_resolution": {
                "overload_components": [
                    {"college": "coed", "hours": 4},
                    {"college": "COEd", "hours": 5.25},
                    {"college": "CIT", "hours": 8.5},
                ]
            }
        }
    )
    allocations, _, warning = allocation_result(provenance, term_pay=None)
    assert warning is None
    assert len(allocations) == 2
    assert allocations[0]["paid_hours"] == 9.25
    assert all(entry["term_pay"] is None for entry in allocations)
    assert sum(entry["weekly_pay"] for entry in allocations) == 1775
    zero, _, warning = allocation_result("{}", hours=0, term_pay=0)
    assert zero[0]["term_pay"] == 0
    assert warning is None


@pytest.mark.parametrize(
    "home,colleges,hours",
    [
        ("COEd", [("COEd", 9.25), ("CIT", 8.5)], 17.75),
        ("COF", [("COF", 1.5), ("CCS", 7.25)], 8.75),
        ("COEd", [("CIT", 17.75)], 17.75),
    ],
)
def test_projection_split_filters_salary_coverage_and_csv(client, home, colleges, hours):
    faculty = create_faculty(client, college=home)
    response = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": faculty["id"],
            "academic_year": "2026-2027",
            "term": "1st Semester",
            "assignments": [
                {
                    "course_code": "HIST101",
                    "course_title": "History",
                    "year_section": "1A",
                    "lecture_hours": 23,
                    "laboratory_hours": 0,
                }
            ],
        },
    )
    assert response.status_code == 201
    with main.SessionLocal() as db:
        workload = db.get(FacultyWorkload, response.json()["id"])
        workload.imported_overload_hours = hours
        workload.import_provenance = json.dumps(
            {
                "confirmed_course_resolution": {
                    "overload_components": [
                        {"college": code, "hours": value} for code, value in colleges
                    ]
                }
            }
        )
        db.commit()
    params = {"academic_year": "2026-2027", "term": "First Semester", "period": "semester"}
    data = client.get("/api/v1/expenses/monthly-projection", params=params).json()
    rate = faculty["monthly_salary"] * 12 * 0.000781
    assert data["included_count"] == 1
    assert data["total_period_salary"] == faculty["monthly_salary"] * 4.5
    assert data["teaching_cost"]["workloads"] == 1
    assert data["teaching_cost"]["total_term_pay"] == pytest.approx(hours * rate * 18)
    assert data["records"][0]["period_overload_pay"] == pytest.approx(hours * rate * 18)
    assert sum(entry["combined_estimate"] for entry in data["college_totals"]) == pytest.approx(
        data["combined_period_estimate"]
    )
    workload_cost = client.get("/api/v1/workloads/cost-projection", params=params).json()
    assert workload_cost["total_term_pay"] == pytest.approx(data["teaching_cost"]["total_term_pay"])
    assert sum(item["term_pay"] for item in workload_cost["college_totals"]) == pytest.approx(
        workload_cost["total_term_pay"]
    )
    for code, value in colleges:
        scoped = client.get(
            "/api/v1/expenses/monthly-projection", params={**params, "college": code}
        ).json()
        scoped_workload = client.get(
            "/api/v1/workloads/cost-projection", params={**params, "college": code}
        ).json()
        assert scoped["included_count"] == (1 if code == home else 0)
        assert scoped["teaching_cost"]["workloads"] == 1
        assert scoped["teaching_cost"]["total_term_pay"] == pytest.approx(value * rate * 18)
        assert scoped_workload["total_term_pay"] == pytest.approx(
            scoped["teaching_cost"]["total_term_pay"]
        )
        assert scoped_workload["college_totals"][0]["label"] == code
        assert scoped["teaching_details"][0]["paid_hours"] == value
        assert len(scoped["teaching_details"][0]["allocations"]) == 1
    home_data = client.get(
        "/api/v1/expenses/monthly-projection", params={**params, "college": home}
    ).json()
    assert home_data["records"][0]["period_overload_pay"] == pytest.approx(
        sum(value for code, value in colleges if code == home) * rate * 18
    )
    assert not any(
        "faculty profiles have no workload" in message for message in home_data["warnings"]
    )
    for excluded in [
        {"employment_status": "Part-time"},
        {"academic_year": "2025-2026"},
        {"term": "Second Semester"},
    ]:
        scoped = client.get(
            "/api/v1/expenses/monthly-projection", params={**params, **excluded}
        ).json()
        assert scoped["teaching_cost"]["workloads"] == 0
    report = client.get("/api/v1/expenses/monthly-projection.csv", params=params)
    assert report.status_code == 200
    assert "Home college,Teaching college,Allocation basis" in report.text
    assert report.text.count("Confirmed teaching college allocation") == len(colleges)
    reviewed = client.post(
        f"/api/v1/workloads/{response.json()['id']}/review",
        headers={"If-Match": str(response.json()["revision"])},
    )
    assert reviewed.status_code == 200
    approved = client.post(
        f"/api/v1/workloads/{response.json()['id']}/approve",
        headers={"If-Match": str(reviewed.json()["revision"])},
    )
    assert approved.status_code == 200
    frozen = approved.json()["approval_snapshot"]["teaching_allocation"]
    assert frozen["basis"] == "Confirmed teaching college allocation"
    assert [(part["college"], part["paid_hours"]) for part in frozen["allocations"]] == colleges
    assert sum(part["term_pay"] for part in frozen["allocations"]) == pytest.approx(
        hours * rate * 18
    )
    summary = client.get(
        "/api/v1/workloads/approved-summary",
        params={"academic_year": "2026-2027", "term": "First Semester"},
    ).json()
    assert summary["term_pay"] == pytest.approx(data["teaching_cost"]["total_term_pay"])
    assert sum(part["term_pay"] for part in summary["college_totals"]) == pytest.approx(
        summary["term_pay"]
    )
    for code, value in colleges:
        scoped_summary = client.get(
            "/api/v1/workloads/approved-summary",
            params={"academic_year": "2026-2027", "term": "First Semester", "college": code},
        ).json()
        assert scoped_summary["workloads"] == 1
        assert scoped_summary["term_pay"] == pytest.approx(value * rate * 18)
        assert scoped_summary["college_totals"][0]["college"] == code
    assert client.get("/api/v1/workloads/historical-allocation-review").json()["count"] == 0


def test_legacy_approval_without_frozen_allocation_is_flagged(client):
    faculty = create_faculty(client, college="COEd")
    created = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": faculty["id"],
            "academic_year": "2026-2027",
            "term": "First Semester",
            "assignments": [
                {
                    "course_code": "HIST101",
                    "course_title": "History",
                    "year_section": "1A",
                    "lecture_hours": 23,
                    "laboratory_hours": 0,
                }
            ],
        },
    ).json()
    reviewed = client.post(
        f"/api/v1/workloads/{created['id']}/review", headers={"If-Match": str(created["revision"])}
    ).json()
    approved = client.post(
        f"/api/v1/workloads/{created['id']}/approve",
        headers={"If-Match": str(reviewed["revision"])},
    ).json()
    with main.SessionLocal() as db:
        workload = db.get(FacultyWorkload, created["id"])
        snapshot = json.loads(workload.approval_snapshot)
        snapshot.pop("teaching_allocation")
        workload.approval_snapshot = json.dumps(snapshot)
        revision = db.query(WorkloadApprovalRevision).filter_by(workload_id=created["id"]).one()
        revision.snapshot = json.dumps(snapshot)
        db.commit()
    summary = client.get("/api/v1/workloads/approved-summary").json()
    assert summary["college_totals"][0]["college"] == "COEd"
    assert summary["term_pay"] == pytest.approx(approved["estimated_teaching_pay_term"])
    assert "not captured" in summary["allocation_warnings"][0]
    review = client.get("/api/v1/workloads/historical-allocation-review")
    assert review.status_code == 200
    assert review.json()["count"] == 1
    item = review.json()["items"][0]
    assert item["approval_revision_id"] == revision.id
    assert item["workload_id"] == created["id"]
    assert item["issue"] == "Allocation not captured"
    assert item["home_college"] == "COEd"
    assert item["course_codes"] == ["HIST101"]
    assert item["term_pay"] == pytest.approx(approved["estimated_teaching_pay_term"])
    reopened = client.post(
        f"/api/v1/workloads/{created['id']}/reopen",
        json={"reason": "Historical review"},
        headers={"If-Match": str(approved["revision"])},
    )
    assert reopened.status_code == 200
    after_reopen = client.get("/api/v1/workloads/historical-allocation-review").json()
    assert after_reopen["items"][0]["current_status"] == "Reopened"
    assert client.get("/api/v1/workloads/approved-summary").json()["workloads"] == 0
