import pytest


def faculty_payload(name: str) -> dict[str, object]:
    return {
        "name": name,
        "rank": "Instructor I",
        "employment_status": "Full-time",
        "salary_grade": "SG 12",
        "salary_step": 1,
        "college": "CIT",
        "department": "Information Technology",
    }


def create_workload(
    client, faculty_id: int, assignments: list[dict[str, object]], term: str = "First Semester"
) -> dict[str, object]:
    response = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": faculty_id,
            "academic_year": "2026-2027",
            "term": term,
            "remarks": "",
            "assignments": assignments,
        },
    )
    assert response.status_code == 201
    return response.json()


def assignment(code: str, section: str, hours: float) -> dict[str, object]:
    return {
        "course_code": code,
        "course_title": code,
        "year_section": section,
        "lecture_hours": hours,
        "laboratory_hours": 0,
    }


def test_two_preparations_have_a_21_hour_regular_load(client) -> None:
    faculty = client.post("/api/v1/faculty-profiles", json=faculty_payload("Ada Cruz"))
    workload = create_workload(
        client,
        faculty.json()["id"],
        [
            assignment("HIST101", "1A", 10),
            assignment("hist101", "1B", 5),
            assignment("MATH101", "1A", 8),
        ],
    )

    assert workload["preparation_count"] == 2
    assert workload["regular_weekly_hours"] == 21
    assert workload["total_weekly_hours"] == 23
    assert workload["overload_weekly_hours"] == 2


def test_summer_defaults_to_six_weeks_and_projects_pay(client):
    settings = client.get("/api/v1/workloads/cost-settings").json()
    assert (
        settings["first_semester_weeks"],
        settings["second_semester_weeks"],
        settings["summer_weeks"],
    ) == (18, 18, 6)
    faculty = client.post("/api/v1/faculty-profiles", json=faculty_payload("Summer Test")).json()
    workload = create_workload(
        client, faculty["id"], [assignment("SUM101", "1A", 23)], term="Summer"
    )
    expected = faculty["monthly_salary"] * 12 * 0.000781 * 2 * 6
    assert workload["projection_weeks"] == 6
    assert workload["estimated_teaching_pay_term"] == pytest.approx(expected)
    projection = client.get("/api/v1/workloads/cost-projection?term=Summer").json()
    assert projection["total_term_pay"] == pytest.approx(expected)


def test_three_preparations_have_an_18_hour_regular_load(client) -> None:
    faculty = client.post("/api/v1/faculty-profiles", json=faculty_payload("Bela Cruz"))
    workload = create_workload(
        client,
        faculty.json()["id"],
        [
            assignment("HIST101", "1A", 6),
            assignment("MATH101", "1A", 6),
            assignment("SCI101", "1A", 9),
        ],
    )

    assert workload["preparation_count"] == 3
    assert workload["regular_weekly_hours"] == 18
    assert workload["total_weekly_hours"] == 21
    assert workload["overload_weekly_hours"] == 3


def test_faculty_profile_workload_history_returns_its_records(client) -> None:
    faculty = client.post("/api/v1/faculty-profiles", json=faculty_payload("Dina Cruz"))
    faculty_id = faculty.json()["id"]
    create_workload(client, faculty_id, [assignment("ENG101", "1A", 6)])

    response = client.get(f"/api/v1/faculty-profiles/{faculty_id}/workloads")

    assert response.status_code == 200
    records = response.json()
    assert len(records) == 1
    assert records[0]["faculty_profile_id"] == faculty_id
    assert records[0]["assignments"][0]["course_code"] == "ENG101"


def test_legacy_fixed_rate_does_not_override_salary_based_estimate(client) -> None:
    settings = client.get("/api/v1/workloads/cost-settings").json()
    assert settings["overload_hourly_rate"] == 0
    settings["overload_hourly_rate"] = 250
    updated = client.put(
        "/api/v1/workloads/cost-settings",
        json={key: value for key, value in settings.items() if key != "updated_at"},
        headers={"If-Match": str(settings["revision"])},
    )
    assert updated.status_code == 200
    assert updated.json()["overload_hourly_rate"] == 250

    faculty = client.post("/api/v1/faculty-profiles", json=faculty_payload("Cora Cruz"))
    workload = create_workload(
        client,
        faculty.json()["id"],
        [assignment("HIST101", "1A", 12), assignment("MATH101", "1A", 11)],
        term="1st Semester",
    )

    assert workload["overload_weekly_hours"] == 2
    assert workload["estimated_overload_pay_weekly"] == pytest.approx(
        faculty.json()["monthly_salary"] * 12 * 0.000781 * 2
    )


def test_part_time_teaching_uses_internal_and_external_rules(client) -> None:
    settings = client.get("/api/v1/workloads/cost-settings").json()
    settings.update(
        {
            "internal_monthly_equivalent_hours": 160,
            "external_base_hourly_rate": 273.77,
            "external_masters_increment": 20,
            "external_doctorate_increment": 40,
            "external_doctor_increment": 30,
            "external_lawyer_increment": 25,
        }
    )
    assert (
        client.put(
            "/api/v1/workloads/cost-settings",
            json={key: value for key, value in settings.items() if key != "updated_at"},
            headers={"If-Match": str(settings["revision"])},
        ).status_code
        == 200
    )

    internal = client.post("/api/v1/faculty-profiles", json=faculty_payload("Dina Cruz"))
    internal_workload = create_workload(
        client,
        internal.json()["id"],
        [assignment("HIST101", "1A", 10)],
    )
    internal_workload = client.put(
        f"/api/v1/workloads/{internal_workload['id']}",
        headers={"If-Match": str(internal_workload["revision"])},
        json={
            "faculty_profile_id": internal.json()["id"],
            "academic_year": "2026-2027",
            "term": "First Semester",
            "remarks": "",
            "compensation_category": "Internal Part-time",
            "highest_qualification": None,
            "professional_qualification": "None",
            "assignments": [assignment("HIST101", "1A", 10)],
        },
    ).json()
    assert internal_workload["compensation_hourly_rate"] == 212.16875
    assert internal_workload["estimated_teaching_pay_weekly"] == 2121.6875

    external = client.post("/api/v1/faculty-profiles", json=faculty_payload("Erin Cruz"))
    external_workload = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": external.json()["id"],
            "academic_year": "2026-2027",
            "term": "Second Semester",
            "remarks": "",
            "compensation_category": "External Part-time",
            "highest_qualification": "Masters",
            "professional_qualification": "Lawyer",
            "assignments": [assignment("LAW101", "1A", 6)],
        },
    )
    assert external_workload.status_code == 201
    assert external_workload.json()["compensation_hourly_rate"] == 318.77
    assert external_workload.json()["estimated_teaching_pay_weekly"] == 1912.62


def test_cost_projection_uses_configured_term_weeks(client) -> None:
    settings = client.get("/api/v1/workloads/cost-settings").json()
    settings.update(
        {
            "overload_hourly_rate": 100,
            "first_semester_weeks": 18,
            "second_semester_weeks": 18,
            "summer_weeks": 0,
        }
    )
    assert (
        client.put(
            "/api/v1/workloads/cost-settings",
            json={key: value for key, value in settings.items() if key != "updated_at"},
            headers={"If-Match": str(settings["revision"])},
        ).status_code
        == 200
    )

    faculty = client.post("/api/v1/faculty-profiles", json=faculty_payload("Faye Cruz"))
    workload = create_workload(
        client,
        faculty.json()["id"],
        [assignment("HIST101", "1A", 12), assignment("MATH101", "1A", 11)],
    )

    weekly = faculty.json()["monthly_salary"] * 12 * 0.000781 * 2
    term_total = weekly * 18
    assert workload["projection_weeks"] == 18
    assert workload["estimated_teaching_pay_weekly"] == pytest.approx(weekly)
    assert workload["estimated_teaching_pay_term"] == pytest.approx(term_total)

    projection = client.get(
        "/api/v1/workloads/cost-projection?academic_year=2026-2027&term=First%20Semester"
    )
    assert projection.status_code == 200
    result = projection.json()
    assert result["total_weekly_pay"] == pytest.approx(weekly)
    assert result["total_term_pay"] == pytest.approx(term_total)
    assert result["category_totals"] == [
        {
            "label": "Regular Faculty",
            "workloads": 1,
            "weekly_pay": pytest.approx(weekly),
            "term_pay": pytest.approx(term_total),
        }
    ]
    assert result["college_totals"] == [
        {
            "label": "CIT",
            "workloads": 1,
            "weekly_pay": pytest.approx(weekly),
            "term_pay": pytest.approx(term_total),
        }
    ]


def test_workload_review_flags_high_load_and_duplicate_section(client) -> None:
    faculty = client.post("/api/v1/faculty-profiles", json=faculty_payload("Gail Cruz"))
    create_workload(
        client,
        faculty.json()["id"],
        [assignment("HIST101", "1A", 16), assignment("HIST101", "1A", 16)],
    )

    review = client.get("/api/v1/workloads/review?academic_year=2026-2027")

    assert review.status_code == 200
    result = review.json()
    assert result["workloads"] == 1
    assert result["high_load_count"] == 1
    assert result["duplicate_assignment_count"] == 1
    assert result["items"][0]["flags"] == [
        "Above 30 weekly teaching hours",
        "Duplicate-looking course section",
    ]
    exported = client.get("/api/v1/workloads/review.csv")
    assert exported.status_code == 200
    assert "Duplicate-looking course section" in exported.content.decode()


def test_workload_approval_requires_review_and_preserves_a_snapshot(client) -> None:
    faculty = client.post("/api/v1/faculty-profiles", json=faculty_payload("Hana Cruz"))
    workload = create_workload(client, faculty.json()["id"], [assignment("ENG101", "1A", 6)])

    review = client.post(
        f"/api/v1/workloads/{workload['id']}/review",
        headers={"If-Match": str(workload["revision"])},
    )
    assert review.status_code == 200
    assert review.json()["workflow_status"] == "Reviewed"

    approved = client.post(
        f"/api/v1/workloads/{workload['id']}/approve",
        headers={"If-Match": str(review.json()["revision"])},
    )
    assert approved.status_code == 200
    assert approved.json()["workflow_status"] == "Approved"
    assert approved.json()["approval_snapshot"]["workload"]["total_weekly_hours"] == 6

    locked = client.put(f"/api/v1/workloads/{workload['id']}", json=workload)
    assert locked.status_code == 409

    reopened = client.post(
        f"/api/v1/workloads/{workload['id']}/reopen",
        json={"reason": "Correct course section"},
        headers={"If-Match": str(approved.json()["revision"])},
    )
    assert reopened.status_code == 200
    assert reopened.json()["workflow_status"] == "Reopened"
    assert reopened.json()["approval_snapshot"] is not None


def test_approved_summary_uses_the_frozen_approval_snapshot(client) -> None:
    faculty = client.post("/api/v1/faculty-profiles", json=faculty_payload("Iris Cruz"))
    workload = create_workload(client, faculty.json()["id"], [assignment("ENG101", "1A", 8)])
    assert (
        client.post(
            f"/api/v1/workloads/{workload['id']}/review",
            headers={"If-Match": str(workload["revision"])},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/workloads/{workload['id']}/approve",
            headers={"If-Match": str(workload["revision"] + 1)},
        ).status_code
        == 200
    )

    assert (
        client.put(
            f"/api/v1/faculty-profiles/{faculty.json()['id']}",
            json=faculty_payload("Changed Name"),
            headers={"If-Match": str(faculty.json()["revision"])},
        ).status_code
        == 200
    )
    response = client.get("/api/v1/workloads/approved-summary?academic_year=2026-2027&college=CIT")

    assert response.status_code == 200
    result = response.json()
    assert result["workloads"] == 1
    assert result["weekly_hours"] == 8
    assert result["items"][0]["faculty_name"] == "Iris Cruz"


@pytest.mark.parametrize(
    "salary,overload,expected", [(54371, 2, 18344.340432), (54371, 0, 0), (None, 2, 0)]
)
def test_salary_overload_formula_example(salary, overload, expected):
    from app.models import FacultyProfile, FacultyWorkload, WorkloadCostSettings
    from app.workload_read import calculate_teaching_cost

    faculty = FacultyProfile(monthly_salary=salary)
    workload = FacultyWorkload(compensation_category="Regular Faculty")
    settings = WorkloadCostSettings(overload_hourly_rate=999)
    category, hourly, weekly = calculate_teaching_cost(
        workload, faculty, 21 + overload, overload, settings
    )
    assert category == "Regular Faculty"
    assert hourly == pytest.approx((salary or 0) * 12 * 0.000781)
    assert weekly * 18 == pytest.approx(expected)
