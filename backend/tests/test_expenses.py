import pytest

import app.main as main
from app.models import FacultyProfile


def test_active_projection_period_persists_and_validates(client):
    assert client.get("/api/v1/expenses/active-period").json() is None
    value = {"academic_year": "2025-2026", "term": "Second Semester"}
    assert (
        client.put(
            "/api/v1/expenses/active-period", json=value, headers={"If-Match": "0"}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/expenses/active-period").json() == {**value, "revision": 1}
    for invalid in [
        {**value, "academic_year": "2025-2027"},
        {**value, "academic_year": "invalid"},
        {**value, "term": "Summer"},
    ]:
        assert client.put("/api/v1/expenses/active-period", json=invalid).status_code == 422
    assert client.get("/api/v1/expenses/active-period").json() == {**value, "revision": 1}
    client.headers.clear()
    assert client.put("/api/v1/expenses/active-period", json=value).status_code == 401


def test_semester_overload_budgets_are_scoped_editable_and_removable(client):
    endpoint = "/api/v1/expenses/overload-budgets"
    assert client.get(endpoint).json() == []
    first = {"academic_year": "2026-2027", "term": "First Semester", "amount": "16076804.24"}
    response = client.put(endpoint, json=first, headers={"If-Match": "0"})
    assert response.status_code == 200
    budget = response.json()
    assert budget["amount"] == 16076804.24
    second = {**first, "term": "Second Semester", "amount": "12000000.00"}
    assert client.put(endpoint, json=second, headers={"If-Match": "0"}).status_code == 200
    assert len(client.get(endpoint).json()) == 2
    assert (
        client.put(
            endpoint,
            json={**first, "amount": "15000000.25"},
            headers={"If-Match": str(budget["revision"])},
        ).json()["id"]
        == budget["id"]
    )
    assert client.get(endpoint).json()[0]["amount"] == 15000000.25
    for invalid in [
        {**first, "amount": "0"},
        {**first, "amount": "-1"},
        {**first, "amount": "1.234"},
        {**first, "academic_year": "2026-2028"},
        {**first, "term": "Summer"},
    ]:
        assert client.put(endpoint, json=invalid).status_code == 422
    assert client.delete(f"{endpoint}/{budget['id']}", headers={"If-Match": "2"}).status_code == 204
    assert client.delete(f"{endpoint}/{budget['id']}").status_code == 404
    assert len(client.get(endpoint).json()) == 1
    client.headers.clear()
    assert client.get(endpoint).status_code == 401
    assert client.put(endpoint, json=first, headers={"If-Match": "0"}).status_code == 401


def test_staff_cannot_manage_semester_overload_budgets(client):
    created = client.post(
        "/api/v1/auth/users",
        json={
            "username": "budget-staff",
            "password": "staff-password-123",
            "role": "staff",
        },
    )
    assert created.status_code == 201
    session = client.post(
        "/api/v1/auth/login",
        json={
            "username": "budget-staff",
            "password": "staff-password-123",
        },
    ).json()
    client.headers.update({"Authorization": f"Bearer {session['token']}"})
    endpoint = "/api/v1/expenses/overload-budgets"
    assert client.get(endpoint).status_code == 403
    assert (
        client.put(
            endpoint,
            json={
                "academic_year": "2026-2027",
                "term": "First Semester",
                "amount": "16076804.24",
            },
        ).status_code
        == 403
    )


def test_saved_estimate_is_immutable_after_salary_change(client):
    faculty = create_faculty(client, name="Snapshot Faculty")
    workload = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": faculty["id"],
            "academic_year": "2026-2027",
            "term": "First Semester",
            "compensation_category": "Regular Faculty",
            "assignments": [
                {
                    "course_code": "HIST",
                    "course_title": "History",
                    "year_section": "1A",
                    "lecture_hours": 23,
                    "laboratory_hours": 0,
                }
            ],
        },
    )
    assert workload.status_code == 201
    scope = {
        "academic_year": "2026-2027",
        "term": "First Semester",
        "period": "semester",
        "as_of": "2026-09-30",
    }
    saved_response = client.post("/api/v1/expenses/saved-projections", json=scope)
    assert saved_response.status_code == 201
    saved = saved_response.json()
    assert saved["projection"]["filters"]["academic_year"] == "2026-2027"
    assert saved["projection"]["status_as_of"] == "2026-09-30"
    original_salary = saved["projection"]["records"][0]["monthly_salary"]
    original_teaching_cost = saved["projection"]["teaching_cost"]["total_term_pay"]
    assert original_teaching_cost > 0
    with main.SessionLocal() as db:
        db.get(FacultyProfile, faculty["id"]).monthly_salary = original_salary + 1000
        db.commit()
    live = client.get("/api/v1/expenses/monthly-projection", params=scope).json()
    assert live["records"][0]["monthly_salary"] == original_salary + 1000
    assert live["teaching_cost"]["total_term_pay"] > original_teaching_cost
    retrieved = client.get(f"/api/v1/expenses/saved-projections/{saved['id']}").json()
    assert retrieved["projection"] == saved["projection"]
    assert client.get("/api/v1/expenses/saved-projections").json()[0]["id"] == saved["id"]
    assert client.get("/api/v1/expenses/saved-projections/99999").status_code == 404
    assert (
        client.post(
            "/api/v1/expenses/saved-projections", json={**scope, "term": "Summer"}
        ).status_code
        == 422
    )


def test_saved_estimates_require_admin(client):
    created = client.post(
        "/api/v1/auth/users",
        json={
            "username": "snapshot-staff",
            "password": "staff-password-123",
            "role": "staff",
        },
    )
    assert created.status_code == 201
    session = client.post(
        "/api/v1/auth/login",
        json={
            "username": "snapshot-staff",
            "password": "staff-password-123",
        },
    ).json()
    client.headers.update({"Authorization": f"Bearer {session['token']}"})
    assert client.get("/api/v1/expenses/saved-projections").status_code == 403
    assert client.get("/api/v1/expenses/saved-projections/1").status_code == 403
    assert (
        client.post(
            "/api/v1/expenses/saved-projections",
            json={
                "academic_year": "2026-2027",
                "term": "First Semester",
                "period": "semester",
            },
        ).status_code
        == 403
    )


def test_projection_warns_when_workloads_are_missing(client):
    create_faculty(client)
    params = {"academic_year": "2026-2027", "term": "First Semester", "period": "semester"}
    response = client.get("/api/v1/expenses/monthly-projection", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["teaching_details"] == []
    assert data["records"][0]["period_overload_pay"] is None
    assert data["records"][0]["regular_weekly_hours"] is None
    assert data["records"][0]["overload_weekly_hours"] is None
    assert data["records"][0]["teaching_status"] == "No workload in selected period"
    assert any("no workload" in message for message in data["warnings"])
    report = client.get("/api/v1/expenses/monthly-projection.csv", params=params)
    assert "Scope warnings" in report.text
    assert "Teaching calculation" in report.text


def test_overload_coverage_links_missing_and_excluded_records(client):
    from app.models import FacultyProfile

    missing = create_faculty(client, name="Missing workload")
    excluded = create_faculty(client, name="Excluded workload")
    workload = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": excluded["id"],
            "academic_year": "2026-2027",
            "term": "First Semester",
            "compensation_category": "Regular Faculty",
            "assignments": [
                {
                    "course_code": "TEST",
                    "course_title": "Test",
                    "year_section": "1A",
                    "lecture_hours": 23,
                    "laboratory_hours": 0,
                }
            ],
        },
    )
    assert workload.status_code == 201
    with main.SessionLocal() as db:
        db.get(FacultyProfile, excluded["id"]).college = ""
        db.commit()
    response = client.get(
        "/api/v1/expenses/monthly-projection",
        params={
            "academic_year": "2026-2027",
            "term": "First Semester",
            "period": "semester",
        },
    )
    assert response.status_code == 200
    coverage = response.json()["overload_coverage"]
    assert coverage["provisional"] is True
    assert coverage["missing_workloads"] == 1
    assert coverage["excluded_workloads"] == 1
    assert coverage["regular_workloads"] == 1
    assert coverage["included_workloads"] == 0
    assert {item["action_path"] for item in coverage["issues"]} == {
        f"/faculty-profiles/{missing['id']}",
        f"/faculty-profiles/{excluded['id']}",
    }


def test_overload_coverage_flags_missing_rate_and_weeks(client):
    from app.models import FacultyProfile, WorkloadCostSettings

    faculty = create_faculty(client)
    workload = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": faculty["id"],
            "academic_year": "2026-2027",
            "term": "First Semester",
            "compensation_category": "Regular Faculty",
            "assignments": [
                {
                    "course_code": "TEST",
                    "course_title": "Test",
                    "year_section": "1A",
                    "lecture_hours": 23,
                    "laboratory_hours": 0,
                }
            ],
        },
    )
    assert workload.status_code == 201
    params = {"academic_year": "2026-2027", "term": "First Semester", "period": "semester"}
    complete = client.get("/api/v1/expenses/monthly-projection", params=params).json()[
        "overload_coverage"
    ]
    assert complete["provisional"] is False
    assert complete["issues"] == []
    with main.SessionLocal() as db:
        db.get(FacultyProfile, faculty["id"]).monthly_salary = 0
        db.get(WorkloadCostSettings, 1).first_semester_weeks = 0
        db.commit()
    incomplete = client.get("/api/v1/expenses/monthly-projection", params=params).json()[
        "overload_coverage"
    ]
    assert incomplete["provisional"] is True
    assert incomplete["missing_rates"] == 1
    assert incomplete["missing_weeks"] == 1
    assert {item["action_path"] for item in incomplete["issues"]} == {
        f"/faculty-profiles/{faculty['id']}",
        f"/workload/{workload.json()['id']}",
    }


def test_no_teaching_confirmation_is_scoped_reversible_and_keeps_workload_data(client):
    missing = create_faculty(client, name="Confirmed no teaching")
    taught = create_faculty(client, name="Teaching faculty")
    workload = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": taught["id"],
            "academic_year": "2026-2027",
            "term": "1st Semester",
            "compensation_category": "Regular Faculty",
            "assignments": [
                {
                    "course_code": "TEST",
                    "course_title": "Test",
                    "year_section": "1A",
                    "lecture_hours": 23,
                    "laboratory_hours": 0,
                }
            ],
        },
    )
    assert workload.status_code == 201
    period = {"academic_year": "2026-2027", "term": "First Semester"}
    endpoint = f"/api/v1/expenses/no-teaching-confirmations/{missing['id']}"
    taught_endpoint = f"/api/v1/expenses/no-teaching-confirmations/{taught['id']}"
    assert client.put(taught_endpoint, json=period).status_code == 409
    params = {**period, "period": "semester"}
    before = client.get("/api/v1/expenses/monthly-projection", params=params).json()
    assert before["overload_coverage"]["missing_workloads"] == 1
    saved = client.put(endpoint, json=period)
    assert saved.status_code == 200
    assert saved.json()["confirmed_by"] == "test-admin"
    assert client.put(endpoint, json=period).json()["confirmed_at"] == saved.json()["confirmed_at"]
    after = client.get("/api/v1/expenses/monthly-projection", params=params).json()
    assert after["overload_coverage"]["missing_workloads"] == 0
    assert after["overload_coverage"]["confirmed_not_teaching"] == 1
    assert after["overload_coverage"]["provisional"] is False
    assert after["records"][0]["teaching_status"] == "Confirmed not teaching this semester"
    assert after["teaching_cost"] == before["teaching_cost"]
    assert (
        client.delete(
            f"/api/v1/faculty-profiles/{missing['id']}",
            headers={"If-Match": str(missing["revision"])},
        ).status_code
        == 409
    )
    next_term = client.get(
        "/api/v1/expenses/monthly-projection", params={**params, "term": "Second Semester"}
    ).json()
    assert next_term["overload_coverage"]["missing_workloads"] == 2
    assert next_term["overload_coverage"]["confirmed_not_teaching"] == 0
    assert client.delete(endpoint, params=period).status_code == 204
    restored = client.get("/api/v1/expenses/monthly-projection", params=params).json()
    assert restored["overload_coverage"]["missing_workloads"] == 1
    assert client.get(f"/api/v1/workloads/{workload.json()['id']}").status_code == 200


def test_no_teaching_confirmation_requires_admin_and_full_time(client):
    full_time = create_faculty(client, name="Full time")
    part_time = create_faculty(client, name="Part time", employment_status="Part-time")
    period = {"academic_year": "2026-2027", "term": "First Semester"}
    assert (
        client.put(
            f"/api/v1/expenses/no-teaching-confirmations/{part_time['id']}", json=period
        ).status_code
        == 409
    )
    staff = client.post(
        "/api/v1/auth/users",
        json={"username": "office-staff", "password": "test-password-123", "role": "staff"},
    )
    assert staff.status_code == 201
    login = client.post(
        "/api/v1/auth/login", json={"username": "office-staff", "password": "test-password-123"}
    )
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"
    endpoint = f"/api/v1/expenses/no-teaching-confirmations/{full_time['id']}"
    assert client.put(endpoint, json=period).status_code == 403
    assert client.delete(endpoint, params=period).status_code == 403


def faculty_payload(
    name: str,
    *,
    rank: str = "Instructor I",
    employment_status: str = "Full-time",
    college: str = "CIT",
    department: str = "Information Technology",
) -> dict[str, object]:
    return {
        "name": name,
        "rank": rank,
        "employment_status": employment_status,
        "salary_grade": "SG 12",
        "salary_step": 1,
        "college": college,
        "department": department,
    }


def create_faculty(client, **overrides: object) -> dict[str, object]:
    payload = faculty_payload("Faculty Member")
    payload.update(overrides)
    response = client.post("/api/v1/faculty-profiles", json=payload)
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize(
    "category", ["Regular Faculty", "Internal Part-time", "External Part-time"]
)
def test_faculty_compensation_columns_and_missing_weeks(client, category):
    from app.models import FacultyWorkload, WorkloadCostSettings

    faculty = create_faculty(client)
    response = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": faculty["id"],
            "academic_year": "2026-2027",
            "term": "First Semester",
            "compensation_category": category,
            "assignments": [
                {
                    "course_code": "TEST",
                    "course_title": "Test",
                    "year_section": "1A",
                    "lecture_hours": 23,
                    "laboratory_hours": 0,
                }
            ],
        },
    )
    assert response.status_code == 201
    with main.SessionLocal() as db:
        db.get(FacultyWorkload, response.json()["id"]).imported_overload_hours = 9.25
        db.commit()
    expected = client.get(f"/api/v1/workloads/{response.json()['id']}").json()[
        "estimated_teaching_pay_term"
    ]
    params = {"academic_year": "2026-2027", "term": "First Semester", "period": "semester"}
    row = client.get("/api/v1/expenses/monthly-projection", params=params).json()["records"][0]
    assert row["period_overload_pay"] == pytest.approx(
        expected if category == "Regular Faculty" else 0
    )
    assert row["period_part_time_pay"] == pytest.approx(
        0 if category == "Regular Faculty" else expected
    )
    assert row["teaching_status"] == "Calculated"
    assert row["regular_weekly_hours"] == (21 if category == "Regular Faculty" else None)
    assert row["overload_weekly_hours"] == (9.25 if category == "Regular Faculty" else None)
    assert (
        "Period overload compensation"
        in client.get("/api/v1/expenses/monthly-projection.csv", params=params).text
    )
    with main.SessionLocal() as db:
        db.get(WorkloadCostSettings, 1).first_semester_weeks = 0
        db.commit()
    row = client.get("/api/v1/expenses/monthly-projection", params=params).json()["records"][0]
    assert row["period_overload_pay"] is None
    assert row["period_part_time_pay"] is None
    assert row["teaching_status"] == "Incomplete"


def test_monthly_salary_projection_groups_faculty_by_college(client) -> None:
    create_faculty(client, name="Ada Cruz", college="CIT")
    create_faculty(client, name="Bela Cruz", college="CAS")

    response = client.get("/api/v1/expenses/monthly-projection")

    assert response.status_code == 200
    body = response.json()
    assert body["included_count"] == 2
    assert body["incomplete_count"] == 0
    assert body["total_monthly_salary"] == 67894
    assert body["total_yearly_salary"] == 814728
    assert body["combined_annual_estimate"] == 814728
    assert body["records"][0]["faculty_name"] == "Bela Cruz"
    totals = {item["college"]: item["monthly_salary_total"] for item in body["college_totals"]}
    assert totals["CAS"] == 33947
    assert totals["CIT"] == 33947
    assert body["employment_status_totals"] == [
        {"label": "Full-time", "included_count": 2, "monthly_salary_total": 67894}
    ]
    assert body["salary_grade_totals"] == [
        {"label": "SG 12", "included_count": 2, "monthly_salary_total": 67894}
    ]
    assert body["teaching_cost"] == {
        "workloads": 0,
        "total_weekly_pay": 0,
        "total_term_pay": 0,
        "unconfigured_term_count": 0,
    }
    report = client.get("/api/v1/expenses/monthly-projection.csv")
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/csv")
    assert "Combined annual estimate" in report.content.decode()


def test_monthly_salary_projection_filters_and_excludes_incomplete_profiles(client) -> None:
    create_faculty(client, name="Ada Cruz", college="CIT")
    create_faculty(
        client,
        name="Bela Cruz",
        employment_status="Part-time",
        college="CAS",
    )
    with main.SessionLocal() as db:
        db.add(
            FacultyProfile(
                name="Cara Cruz",
                rank="Instructor I",
                employment_status="Full-time",
                salary_grade="SG 12",
                salary_step=1,
                monthly_salary=None,
                college="CCS",
                department="Computer Studies",
            )
        )
        db.commit()

    filtered = client.get(
        "/api/v1/expenses/monthly-projection?college=CAS&employment_status=Part-time"
    )
    all_profiles = client.get("/api/v1/expenses/monthly-projection")

    assert filtered.status_code == 200
    assert filtered.json()["filters"] == {
        "college": "CAS",
        "employment_status": "Part-time",
        "academic_year": None,
        "term": None,
    }
    assert filtered.json()["included_count"] == 1
    assert filtered.json()["total_monthly_salary"] == 33947
    assert [record["faculty_name"] for record in filtered.json()["records"]] == ["Bela Cruz"]
    assert all_profiles.json()["included_count"] == 2
    assert all_profiles.json()["incomplete_count"] == 1
    assert all_profiles.json()["total_monthly_salary"] == 67894


def test_monthly_salary_projection_rejects_anonymous_and_staff_users(client) -> None:
    created = client.post(
        "/api/v1/auth/users",
        json={"username": "office-staff", "password": "staff-password-123", "role": "staff"},
    )
    assert created.status_code == 201

    client.headers.clear()
    anonymous = client.get("/api/v1/expenses/monthly-projection")
    assert anonymous.status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "office-staff", "password": "staff-password-123"},
    )
    client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})
    assert client.get("/api/v1/expenses/monthly-projection").status_code == 403


def test_projection_readiness_identifies_missing_salary_details(client) -> None:
    create_faculty(client, name="Ada Cruz")
    with main.SessionLocal() as db:
        db.add(
            FacultyProfile(
                name="Bela Cruz",
                rank="Instructor I",
                employment_status="Full-time",
                salary_grade=None,
                salary_step=1,
                monthly_salary=None,
                college="CAS",
                department="General Education",
            )
        )
        db.commit()

    response = client.get("/api/v1/expenses/projection-readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    items = {item["key"]: item["count"] for item in body["items"]}
    assert items["salary-profiles"] == 1
    assert items["term-weeks"] == 0


def test_monthly_projection_filters_teaching_cost_by_period(client) -> None:
    faculty = create_faculty(client, name="Ada Cruz")
    created = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": faculty["id"],
            "academic_year": "2026-2027",
            "term": "1st Semester",
            "remarks": "",
            "assignments": [
                {
                    "course_code": "HIST101",
                    "course_title": "History",
                    "year_section": "1A",
                    "lecture_hours": 6,
                    "laboratory_hours": 0,
                }
            ],
        },
    )
    assert created.status_code == 201

    selected = client.get(
        "/api/v1/expenses/monthly-projection?academic_year=2026-2027&term=1st%20Semester"
    )
    unmatched = client.get(
        "/api/v1/expenses/monthly-projection?academic_year=2025-2026&term=1st%20Semester"
    )

    assert selected.status_code == 200
    assert selected.json()["filters"]["academic_year"] == "2026-2027"
    assert selected.json()["teaching_cost"]["workloads"] == 1
    assert unmatched.json()["teaching_cost"]["workloads"] == 0


def test_projection_period_salary_and_teaching_scope(client) -> None:
    faculty = create_faculty(client, name="Period Faculty", college="CAS")
    other = create_faculty(
        client, name="Other Faculty", college="CIT", employment_status="Part-time"
    )
    expected_terms = {}
    for profile, year, term in [
        (faculty, "2026-2027", "1st Semester"),
        (faculty, "2026-2027", "Second Semester"),
        (faculty, "2026-2027", "Summer"),
        (faculty, "2025-2026", "First Semester"),
        (other, "2026-2027", "First Semester"),
    ]:
        response = client.post(
            "/api/v1/workloads",
            json={
                "faculty_profile_id": profile["id"],
                "academic_year": year,
                "term": term,
                "remarks": "",
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
        if profile == faculty and year == "2026-2027":
            expected_terms[term] = response.json()["estimated_teaching_pay_term"]
    filters = {
        "academic_year": "2026-2027",
        "college": "CAS",
        "term": "First Semester",
        "period": "semester",
    }
    response = client.get("/api/v1/expenses/monthly-projection", params=filters)
    assert response.status_code == 200
    semester = response.json()
    assert semester["salary_months"] == 4.5
    assert semester["total_period_salary"] == 33947 * 4.5
    assert semester["teaching_cost"]["workloads"] == 1
    assert semester["teaching_cost"]["total_term_pay"] == expected_terms["1st Semester"]
    assert semester["records"][0]["period_overload_pay"] == expected_terms["1st Semester"]
    assert semester["records"][0]["period_part_time_pay"] == 0
    assert semester["records"][0]["teaching_status"] == "Calculated"
    detail = semester["teaching_details"][0]
    assert detail["hourly_rate"] == pytest.approx(33947 * 12 * 0.000781)
    assert detail["paid_hours"] == 2
    assert detail["weeks"] == 18
    assert detail["term_pay"] == pytest.approx(detail["hourly_rate"] * 2 * 18)
    assert semester["combined_period_estimate"] == pytest.approx(
        33947 * 4.5 + expected_terms["1st Semester"]
    )
    assert (
        sum(item["combined_estimate"] for item in semester["college_totals"])
        == semester["combined_period_estimate"]
    )
    report = client.get("/api/v1/expenses/monthly-projection.csv", params=filters)
    assert report.status_code == 200
    assert "Salary months,4.5" in report.text
    assert "Combined semester estimate" in report.text
    assert str(33947 * 4.5) in report.text
    yearly = client.get(
        "/api/v1/expenses/monthly-projection", params={**filters, "period": "yearly"}
    ).json()
    assert yearly["filters"]["term"] is None
    assert yearly["salary_months"] == 12
    assert yearly["total_period_salary"] == 33947 * 12
    assert yearly["teaching_cost"]["workloads"] == 3
    assert yearly["teaching_cost"]["total_term_pay"] == pytest.approx(sum(expected_terms.values()))
    assert yearly["records"][0]["period_overload_pay"] == pytest.approx(
        sum(expected_terms.values())
    )
    summer = client.get(
        "/api/v1/expenses/monthly-projection",
        params={**filters, "period": "summer", "term": "Summer"},
    ).json()
    assert summer["salary_months"] == 0
    assert summer["total_period_salary"] == 0
    assert summer["teaching_cost"]["workloads"] == 1
    assert summer["teaching_cost"]["total_term_pay"] == expected_terms["Summer"]
    assert summer["combined_period_estimate"] == expected_terms["Summer"]
    assert summer["teaching_details"][0]["weeks"] == 6
    assert any("teaching compensation only" in message for message in summer["warnings"])
    assert (
        "Summer teaching estimate"
        in client.get(
            "/api/v1/expenses/monthly-projection.csv",
            params={**filters, "period": "summer", "term": "Summer"},
        ).text
    )
    status_scope = client.get(
        "/api/v1/expenses/monthly-projection",
        params={
            "academic_year": "2026-2027",
            "period": "semester",
            "term": "First Semester",
            "employment_status": "Full-time",
        },
    ).json()
    assert status_scope["teaching_cost"]["workloads"] == 1
    for invalid in [
        {"period": "semester"},
        {**filters, "term": "Summer"},
        {**filters, "period": "invalid"},
    ]:
        assert client.get("/api/v1/expenses/monthly-projection", params=invalid).status_code == 422
