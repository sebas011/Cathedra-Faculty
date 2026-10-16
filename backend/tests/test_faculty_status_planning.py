def faculty(name: str, status: str = "Active", effective_date: str | None = None) -> dict:
    return {
        "name": name,
        "rank": "Instructor I",
        "employment_status": "Full-time",
        "college": "CAS",
        "department": "BSAM",
        "service_status": status,
        "service_status_effective_date": effective_date,
    }


def test_uncertain_status_is_separate_and_effective_dates_control_salary(client):
    endpoint = "/api/v1/faculty-profiles"
    active = client.post(endpoint, json=faculty("Active Faculty"))
    uncertain = client.post(endpoint, json=faculty("Uncertain Faculty", "To verify"))
    retired = client.post(endpoint, json=faculty("Retired Faculty", "Retired", "2026-09-01"))
    future = client.post(endpoint, json=faculty("Future Retirement", "Retired", "2027-01-01"))
    assert all(response.status_code == 201 for response in (active, uncertain, retired, future))

    current = client.get(
        "/api/v1/expenses/monthly-projection",
        params={
            "academic_year": "2026-2027",
            "term": "First Semester",
            "period": "semester",
            "as_of": "2026-09-29",
        },
    ).json()
    assert current["included_count"] == 2
    assert current["provisional_status_count"] == 1
    assert current["provisional_monthly_salary_total"] == uncertain.json()["monthly_salary"]
    assert current["provisional_period_salary_total"] == uncertain.json()["monthly_salary"] * 4.5
    assert current["excluded_status_count"] == 1
    assert (
        current["total_monthly_salary"]
        == active.json()["monthly_salary"] + future.json()["monthly_salary"]
    )

    earlier = client.get(
        "/api/v1/expenses/monthly-projection",
        params={
            "academic_year": "2026-2027",
            "term": "First Semester",
            "period": "semester",
            "as_of": "2026-08-01",
        },
    ).json()
    assert earlier["included_count"] == 3
    assert earlier["excluded_status_count"] == 0
    assert (
        client.get(
            "/api/v1/expenses/monthly-projection", params={"as_of": "not-a-date"}
        ).status_code
        == 422
    )
    csv = client.get("/api/v1/expenses/monthly-projection.csv", params={"as_of": "2026-09-29"}).text
    assert "Provisional monthly salary cost" in csv
    assert "2026-09-29" in csv
    profile_export = client.get("/api/v1/maintenance/exports/faculty-profiles.csv").text
    assert "Status Effective Date" in profile_export
    assert "2026-09-01" in profile_export


def test_legacy_inactive_without_date_is_provisional_and_needs_review(client):
    import app.main as main
    from app.models import FacultyProfile

    with main.SessionLocal() as db:
        db.add(
            FacultyProfile(
                name="Legacy Retired",
                rank="Instructor I",
                employment_status="Full-time",
                salary_grade="SG 12",
                salary_step=1,
                monthly_salary=33947,
                college="CAS",
                department="BSAM",
                service_status="Retired",
            )
        )
        db.commit()
    projection = client.get(
        "/api/v1/expenses/monthly-projection", params={"as_of": "2026-09-29"}
    ).json()
    assert projection["provisional_status_count"] == 1
    assert projection["included_count"] == 0
    queue = client.get("/api/v1/verification").json()
    assert "Faculty status effective date needs confirmation" in str(queue)


def test_status_change_requires_date_and_does_not_erase_approved_workload(client):
    profile = client.post("/api/v1/faculty-profiles", json=faculty("History Faculty")).json()
    workload_payload = {
        "faculty_profile_id": profile["id"],
        "academic_year": "2025-2026",
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
    }
    workload = client.post("/api/v1/workloads", json=workload_payload)
    assert workload.status_code == 201
    record = workload.json()
    reviewed = client.post(
        f"/api/v1/workloads/{record['id']}/review", headers={"If-Match": str(record["revision"])}
    )
    assert reviewed.status_code == 200
    approved = client.post(
        f"/api/v1/workloads/{record['id']}/approve",
        headers={"If-Match": str(reviewed.json()["revision"])},
    )
    assert approved.status_code == 200
    snapshot = approved.json()["approval_snapshot"]

    endpoint = f"/api/v1/faculty-profiles/{profile['id']}"
    missing_date = client.put(
        endpoint,
        json={**profile, "service_status": "Retired"},
        headers={"If-Match": str(profile["revision"])},
    )
    assert missing_date.status_code == 422
    changed = client.put(
        endpoint,
        json={
            **profile,
            "service_status": "Retired",
            "service_status_effective_date": "2026-09-01",
        },
        headers={"If-Match": str(profile["revision"])},
    )
    assert changed.status_code == 200
    assert client.get(f"/api/v1/workloads/{record['id']}").json()["approval_snapshot"] == snapshot
    assert (
        client.post(
            "/api/v1/workloads", json={**workload_payload, "academic_year": "2027-2028"}
        ).status_code
        == 409
    )

    other = client.post("/api/v1/faculty-profiles", json=faculty("Other Faculty")).json()
    editable = client.post(
        "/api/v1/workloads", json={**workload_payload, "faculty_profile_id": other["id"]}
    ).json()
    reassignment = client.put(
        f"/api/v1/workloads/{editable['id']}",
        json={**workload_payload, "academic_year": "2027-2028"},
        headers={"If-Match": str(editable["revision"])},
    )
    assert reassignment.status_code == 409


def test_current_period_review_and_approval_check_faculty_status(client):
    profile = client.post("/api/v1/faculty-profiles", json=faculty("Current Faculty")).json()
    assert (
        client.put(
            "/api/v1/expenses/active-period",
            json={"academic_year": "2026-2027", "term": "First Semester"},
            headers={"If-Match": "0"},
        ).status_code
        == 200
    )
    workload = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": profile["id"],
            "academic_year": "2026-2027",
            "term": "First Semester",
            "assignments": [
                {
                    "course_code": "MATH101",
                    "course_title": "Mathematics",
                    "year_section": "1A",
                    "lecture_hours": 23,
                    "laboratory_hours": 0,
                }
            ],
        },
    ).json()
    reviewed = client.post(
        f"/api/v1/workloads/{workload['id']}/review",
        headers={"If-Match": str(workload["revision"])},
    ).json()
    changed = client.put(
        f"/api/v1/faculty-profiles/{profile['id']}",
        json={
            **profile,
            "service_status": "Retired",
            "service_status_effective_date": "2026-09-01",
        },
        headers={"If-Match": str(profile["revision"])},
    )
    assert changed.status_code == 200
    assert (
        client.post(
            f"/api/v1/workloads/{workload['id']}/approve",
            headers={"If-Match": str(reviewed["revision"])},
        ).status_code
        == 409
    )
    assert client.get(f"/api/v1/workloads/{workload['id']}").json()["workflow_status"] == "Reviewed"


def test_inactive_faculty_cannot_be_confirmed_as_currently_not_teaching(client):
    profile = client.post(
        "/api/v1/faculty-profiles", json=faculty("Retired Coverage", "Retired", "2026-09-01")
    ).json()
    response = client.put(
        f"/api/v1/expenses/no-teaching-confirmations/{profile['id']}",
        json={"academic_year": "2026-2027", "term": "First Semester"},
    )
    assert response.status_code == 409


def test_future_retirement_blocks_the_affected_semester_but_not_an_earlier_one(client):
    profile = client.post(
        "/api/v1/faculty-profiles", json=faculty("Future Teaching", "Retired", "2027-01-01")
    ).json()
    payload = {
        "faculty_profile_id": profile["id"],
        "academic_year": "2026-2027",
        "term": "First Semester",
        "assignments": [
            {
                "course_code": "MATH101",
                "course_title": "Mathematics",
                "year_section": "1A",
                "lecture_hours": 23,
                "laboratory_hours": 0,
            }
        ],
    }
    assert client.post("/api/v1/workloads", json=payload).status_code == 201
    assert (
        client.post("/api/v1/workloads", json={**payload, "term": "Second Semester"}).status_code
        == 409
    )
    assert (
        client.post("/api/v1/workloads", json={**payload, "term": "2nd Semester"}).status_code
        == 409
    )

    active = client.post("/api/v1/faculty-profiles", json=faculty("Active Future Teaching")).json()
    future = client.post(
        "/api/v1/workloads",
        json={**payload, "faculty_profile_id": active["id"], "term": "Second Semester"},
    ).json()
    assert (
        client.put(
            "/api/v1/expenses/active-period",
            json={"academic_year": "2026-2027", "term": "Second Semester"},
            headers={"If-Match": "0"},
        ).status_code
        == 200
    )
    changed = client.put(
        f"/api/v1/faculty-profiles/{active['id']}",
        json={**active, "service_status": "Retired", "service_status_effective_date": "2027-01-01"},
        headers={"If-Match": str(active["revision"])},
    )
    assert changed.status_code == 200
    assert (
        client.post(
            f"/api/v1/workloads/{future['id']}/review",
            headers={"If-Match": str(future["revision"])},
        ).status_code
        == 409
    )


def test_uncertain_workload_cost_and_salary_are_drillable_but_not_confirmed(client):
    profile = client.post(
        "/api/v1/faculty-profiles", json=faculty("Status Review Faculty", "To verify")
    ).json()
    workload = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": profile["id"],
            "academic_year": "2026-2027",
            "term": "First Semester",
            "assignments": [
                {
                    "course_code": "MATH101",
                    "course_title": "Mathematics",
                    "year_section": "1A",
                    "lecture_hours": 23,
                    "laboratory_hours": 0,
                }
            ],
        },
    )
    assert workload.status_code == 201
    params = {
        "academic_year": "2026-2027",
        "term": "First Semester",
        "period": "semester",
        "as_of": "2026-09-29",
    }
    report = client.get("/api/v1/expenses/monthly-projection", params=params)
    assert report.status_code == 200
    data = report.json()
    assert data["provisional_records"][0]["faculty_id"] == profile["id"]
    assert data["provisional_teaching_details"][0]["workload_id"] == workload.json()["id"]
    assert data["provisional_teaching_cost"]["total_term_pay"] > 0
    assert data["teaching_cost"]["total_term_pay"] == 0
    assert data["combined_period_estimate"] == 0
    csv = client.get("/api/v1/expenses/monthly-projection.csv", params=params).text
    assert "Faculty status review" in csv
    assert "Provisional teaching calculation" in csv
    assert "Status Review Faculty" in csv

    changed = client.put(
        f"/api/v1/faculty-profiles/{profile['id']}",
        json={**profile, "service_status": "Active"},
        headers={"If-Match": str(profile["revision"])},
    )
    assert changed.status_code == 200
    confirmed = client.get("/api/v1/expenses/monthly-projection", params=params).json()
    assert confirmed["provisional_records"] == []
    assert confirmed["provisional_teaching_details"] == []
    assert (
        confirmed["teaching_cost"]["total_term_pay"]
        == data["provisional_teaching_cost"]["total_term_pay"]
    )


def test_mid_semester_status_change_is_flagged_without_proration(client):
    profile = client.post(
        "/api/v1/faculty-profiles", json=faculty("Midterm Retirement", "Retired", "2026-09-01")
    )
    assert profile.status_code == 201
    data = client.get(
        "/api/v1/expenses/monthly-projection",
        params={
            "academic_year": "2026-2027",
            "term": "First Semester",
            "period": "semester",
            "as_of": "2026-09-29",
        },
    ).json()
    assert any("not automatically prorated" in warning for warning in data["warnings"])
    assert data["excluded_status_count"] == 1
