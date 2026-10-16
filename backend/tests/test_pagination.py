import pytest

import app.main as main
from app.models import FacultyProfile


def faculty_payload(name: str) -> dict[str, str]:
    return {
        "name": name,
        "rank": "Instructor I",
        "employment_status": "Full-time",
        "salary_grade": "SG 12",
        "salary_step": 1,
        "monthly_salary": 32000,
        "college": "CIT",
        "department": "Information Technology",
    }


def test_faculty_and_workload_pages_respect_filters(client) -> None:
    first = client.post("/api/v1/faculty-profiles", json=faculty_payload("Ada Cruz"))
    second = client.post("/api/v1/faculty-profiles", json=faculty_payload("Bela Cruz"))
    assert first.status_code == 201 and second.status_code == 201
    faculty_page = client.get("/api/v1/faculty-profiles/page?search=Ada&page_size=10")
    assert faculty_page.status_code == 200
    assert faculty_page.json()["total"] == 1
    assert faculty_page.json()["items"][0]["monthly_salary"] == 33947

    workload = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": first.json()["id"],
            "academic_year": "2026-2027",
            "term": "First Semester",
            "remarks": "",
            "assignments": [
                {
                    "course_code": "IT101",
                    "course_title": "Computing",
                    "year_section": "1A",
                    "lecture_hours": 3,
                    "laboratory_hours": 0,
                }
            ],
        },
    )
    assert workload.status_code == 201
    workload_page = client.get("/api/v1/workloads/page?academic_year=2026-2027&page_size=10")
    assert workload_page.status_code == 200
    assert workload_page.json()["total"] == 1
    assert workload_page.json()["items"][0]["faculty_name"] == "Ada Cruz"
    college_page = client.get("/api/v1/workloads/page?college=CIT&page_size=10")
    assert college_page.json()["total"] == 1
    summary = client.get("/api/v1/workloads/summary")
    assert summary.status_code == 200
    assert summary.json()["workloads"] == 1
    assert summary.json()["weekly_hours"] == 3


def test_directory_summaries_cover_every_page_and_follow_search(client):
    for index in range(11):
        profile = client.post(
            "/api/v1/faculty-profiles",
            json={
                **faculty_payload(f"Faculty {index:02d}"),
                "college": "CAS" if index == 10 else "CIT",
                "employment_status": "Part-time" if index == 10 else "Full-time",
            },
        )
        assert profile.status_code == 201
        if index == 10:
            with main.SessionLocal() as db:
                db.get(
                    FacultyProfile, profile.json()["id"]
                ).data_source = "Imported from ScholarDesk"
                db.commit()
    for page in (1, 2, 3):
        response = client.get(
            "/api/v1/faculty-profiles/page", params={"page": page, "page_size": 10}
        )
        assert response.status_code == 200
        assert response.json()["total"] == 11
        assert response.json()["summary"] == {
            "full_time": 10,
            "colleges": 2,
            "imported": 1,
            "pending_placement": 0,
        }
    filtered = client.get("/api/v1/faculty-profiles/page?search=Faculty%2010").json()
    assert filtered["total"] == 1
    assert filtered["summary"] == {
        "full_time": 0,
        "colleges": 1,
        "imported": 1,
        "pending_placement": 0,
    }
    empty = client.get("/api/v1/faculty-profiles/page?search=missing").json()
    assert empty["total"] == 0
    assert empty["summary"] == {
        "full_time": 0,
        "colleges": 0,
        "imported": 0,
        "pending_placement": 0,
    }


def test_workload_summaries_cover_every_page_and_follow_filters(client):
    expected_pay = 0
    last_pay = 0
    for index in range(11):
        profile = client.post(
            "/api/v1/faculty-profiles",
            json={
                **faculty_payload(f"Faculty {index:02d}"),
                "college": "CAS" if index == 10 else "CIT",
            },
        ).json()
        workload = client.post(
            "/api/v1/workloads",
            json={
                "faculty_profile_id": profile["id"],
                "academic_year": "2026-2027",
                "term": "Second Semester" if index == 10 else "First Semester",
                "assignments": [
                    {
                        "course_code": "IT101",
                        "course_title": "Computing",
                        "year_section": "1A",
                        "lecture_hours": 20,
                        "laboratory_hours": 0,
                    },
                    {
                        "course_code": " it101 ",
                        "course_title": "Computing",
                        "year_section": "1B",
                        "lecture_hours": 3,
                        "laboratory_hours": 0,
                    },
                ],
            },
        )
        assert workload.status_code == 201
        last_pay = workload.json()["estimated_teaching_pay_weekly"]
        expected_pay += last_pay
    for page in (1, 2, 3):
        response = client.get("/api/v1/workloads/page", params={"page": page, "page_size": 10})
        assert response.status_code == 200
        result = response.json()
        assert result["total"] == 11
        assert result["summary"]["assignments"] == 22
        assert result["summary"]["preparations"] == 11
        assert result["summary"]["weekly_pay"] == pytest.approx(expected_pay)
    for filters in ({"search": "Faculty 10"}, {"college": "CAS"}, {"term": "Second Semester"}):
        result = client.get("/api/v1/workloads/page", params=filters).json()
        assert result["total"] == 1
        assert result["summary"] == {"assignments": 2, "preparations": 1, "weekly_pay": last_pay}
    empty = client.get("/api/v1/workloads/page?academic_year=2025-2026").json()
    assert empty["total"] == 0
    assert empty["summary"] == {"assignments": 0, "preparations": 0, "weekly_pay": 0}
