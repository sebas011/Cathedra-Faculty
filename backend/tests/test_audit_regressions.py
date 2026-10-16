def test_password_change_revokes_previous_session(client):
    old_token = client.headers["Authorization"]
    assert (
        client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "test-password-123", "new_password": "new-test-password-123"},
        ).status_code
        == 204
    )
    assert (
        client.get("/api/v1/faculty-profiles", headers={"Authorization": old_token}).status_code
        == 401
    )


def test_referenced_faculty_cannot_be_deleted(client):
    faculty = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Linked faculty",
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "salary_grade": "SG 12",
            "college": "CAS",
            "department": "Mathematics",
        },
    )
    assert faculty.status_code == 201
    workload = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": faculty.json()["id"],
            "academic_year": "2026-2027",
            "term": "First Semester",
            "assignments": [
                {
                    "course_code": "TEST101",
                    "course_title": "Test course",
                    "year_section": "A",
                    "lecture_hours": 3,
                }
            ],
        },
    )
    assert workload.status_code == 201
    assert (
        client.delete(
            f"/api/v1/faculty-profiles/{faculty.json()['id']}",
            headers={"If-Match": str(faculty.json()["revision"])},
        ).status_code
        == 409
    )
    assert client.get(f"/api/v1/workloads/{workload.json()['id']}").status_code == 200


def test_approval_history_survives_reopen_and_second_approval(client):
    faculty = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Approval faculty",
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "college": "CAS",
            "department": "Mathematics",
        },
    ).json()
    workload_payload = {
        "faculty_profile_id": faculty["id"],
        "academic_year": "2026-2027",
        "term": "First Semester",
        "assignments": [
            {
                "course_code": "MATH101",
                "course_title": "Mathematics",
                "year_section": "A",
                "lecture_hours": 24,
            }
        ],
    }
    workload_id = client.post("/api/v1/workloads", json=workload_payload).json()["id"]
    assert (
        client.post(
            f"/api/v1/workloads/{workload_id}/review", headers={"If-Match": "0"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/workloads/{workload_id}/approve", headers={"If-Match": "1"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/workloads/{workload_id}/reopen",
            json={"reason": "Correct course hours"},
            headers={"If-Match": "2"},
        ).status_code
        == 200
    )
    workload_payload["assignments"][0]["lecture_hours"] = 25
    assert (
        client.put(
            f"/api/v1/workloads/{workload_id}", json=workload_payload, headers={"If-Match": "3"}
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"/api/v1/workloads/{workload_id}",
            headers={
                "If-Match": str(client.get(f"/api/v1/workloads/{workload_id}").json()["revision"])
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/workloads/{workload_id}/review", headers={"If-Match": "4"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/workloads/{workload_id}/approve", headers={"If-Match": "5"}
        ).status_code
        == 200
    )
    history = client.get(f"/api/v1/workloads/{workload_id}/approvals")
    assert history.status_code == 200
    assert [item["snapshot"]["workload"]["total_weekly_hours"] for item in history.json()] == [
        24,
        25,
    ]
    assert history.json()[1]["snapshot"]["correction_of_revision_id"] == history.json()[0]["id"]
    assert history.json()[1]["snapshot"]["correction_reason"] == "Correct course hours"


def test_approved_college_totals_are_independent(client):
    for college, name in (("CAS", "First totals faculty"), ("CIT", "Second totals faculty")):
        faculty = client.post(
            "/api/v1/faculty-profiles",
            json={
                "name": name,
                "rank": "Instructor I",
                "employment_status": "Full-time",
                "college": college,
                "department": "General",
            },
        ).json()
        workload = client.post(
            "/api/v1/workloads",
            json={
                "faculty_profile_id": faculty["id"],
                "academic_year": "2026-2027",
                "term": "First Semester",
                "assignments": [
                    {
                        "course_code": "T101",
                        "course_title": "Test course",
                        "year_section": "A",
                        "lecture_hours": 24,
                    }
                ],
            },
        ).json()
        assert (
            client.post(
                f"/api/v1/workloads/{workload['id']}/review", headers={"If-Match": "0"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/v1/workloads/{workload['id']}/approve", headers={"If-Match": "1"}
            ).status_code
            == 200
        )
    summary = client.get("/api/v1/workloads/approved-summary").json()
    assert len(summary["college_totals"]) == 2
    assert sum(item["term_pay"] for item in summary["college_totals"]) == summary["term_pay"]
    activity = client.get("/api/v1/activity").json()
    assert any(
        item["action"] == f"Approved Faculty Workload #{workload['id']}" for item in activity
    )


def test_period_aliases_cannot_create_duplicate_workloads(client):
    faculty = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Alias faculty",
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "college": "CAS",
            "department": "General",
        },
    ).json()
    workload = {
        "faculty_profile_id": faculty["id"],
        "academic_year": "2026-2027",
        "term": "1st Semester",
        "assignments": [
            {
                "course_code": "T101",
                "course_title": "Test course",
                "year_section": "A",
                "lecture_hours": 3,
            }
        ],
    }
    first = client.post("/api/v1/workloads", json=workload)
    assert first.status_code == 201
    assert first.json()["term"] == "First Semester"
    assert (
        client.post("/api/v1/workloads", json={**workload, "term": "First Semester"}).status_code
        == 409
    )


def test_stale_faculty_and_workload_edits_do_not_overwrite(client):
    profile_payload = {
        "name": "Concurrent faculty",
        "rank": "Instructor I",
        "employment_status": "Full-time",
        "college": "CAS",
        "department": "General",
    }
    profile = client.post("/api/v1/faculty-profiles", json=profile_payload).json()
    profile_endpoint = f"/api/v1/faculty-profiles/{profile['id']}"
    assert (
        client.put(
            profile_endpoint,
            json={**profile_payload, "department": "Science"},
            headers={"If-Match": str(profile["revision"])},
        ).status_code
        == 200
    )
    assert (
        client.put(
            profile_endpoint,
            json={**profile_payload, "department": "Arts"},
            headers={"If-Match": str(profile["revision"])},
        ).status_code
        == 409
    )
    assert client.get(profile_endpoint).json()["department"] == "Science"
    workload_payload = {
        "faculty_profile_id": profile["id"],
        "academic_year": "2026-2027",
        "term": "First Semester",
        "assignments": [
            {
                "course_code": "T101",
                "course_title": "Test course",
                "year_section": "A",
                "lecture_hours": 3,
            }
        ],
    }
    workload = client.post("/api/v1/workloads", json=workload_payload).json()
    workload_endpoint = f"/api/v1/workloads/{workload['id']}"
    assert (
        client.put(
            workload_endpoint,
            json={**workload_payload, "remarks": "First save"},
            headers={"If-Match": str(workload["revision"])},
        ).status_code
        == 200
    )
    assert (
        client.put(
            workload_endpoint,
            json={**workload_payload, "remarks": "Stale save"},
            headers={"If-Match": str(workload["revision"])},
        ).status_code
        == 409
    )
    assert client.get(workload_endpoint).json()["remarks"] == "First save"


def test_stale_compensation_settings_are_rejected(client):
    settings = client.get("/api/v1/workloads/cost-settings").json()
    endpoint = "/api/v1/workloads/cost-settings"
    assert (
        client.put(
            endpoint,
            json={**settings, "summer_weeks": 7},
            headers={"If-Match": str(settings["revision"])},
        ).status_code
        == 200
    )
    assert (
        client.put(
            endpoint,
            json={**settings, "summer_weeks": 8},
            headers={"If-Match": str(settings["revision"])},
        ).status_code
        == 409
    )
    assert client.get(endpoint).json()["summer_weeks"] == 7
