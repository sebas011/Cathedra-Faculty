import csv
from decimal import Decimal
from io import StringIO

import pytest

import app.main as main
from app.models import FacultyWorkload


def displayed_centavos(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def test_semester_projection_preserves_current_formula_and_reconciles(client) -> None:
    profiles = []
    for name, college in (("Faculty A", "CAS"), ("Faculty B", "CIT")):
        response = client.post(
            "/api/v1/faculty-profiles",
            json={
                "name": name,
                "rank": "Assistant Professor IV",
                "employment_status": "Full-time",
                "salary_step": 2,
                "college": college,
                "department": "General",
            },
        )
        assert response.status_code == 201
        profiles.append(response.json())
    workloads = []
    for profile in profiles:
        response = client.post(
            "/api/v1/workloads",
            json={
                "faculty_profile_id": profile["id"],
                "academic_year": "2026-2027",
                "term": "First Semester",
                "assignments": [
                    {
                        "course_code": "TEST101",
                        "course_title": "Test Course",
                        "year_section": "1A",
                        "lecture_hours": 23,
                        "laboratory_hours": 0,
                    }
                ],
            },
        )
        assert response.status_code == 201
        workloads.append(response.json())
    with main.SessionLocal() as db:
        db.get(FacultyWorkload, workloads[1]["id"]).imported_overload_hours = 0
        db.commit()

    params = {"academic_year": "2026-2027", "term": "First Semester", "period": "semester"}
    response = client.get("/api/v1/expenses/monthly-projection", params=params)
    assert response.status_code == 200
    projection = response.json()
    expected_overload = 54371 * 12 * 0.000781 * 2 * 18
    assert expected_overload == pytest.approx(18344.340432)
    assert projection["salary_months"] == 4.5
    assert projection["total_monthly_salary"] == 108742
    assert projection["total_period_salary"] == 489339
    assert projection["teaching_cost"]["total_term_pay"] == pytest.approx(expected_overload)
    assert projection["combined_period_estimate"] == pytest.approx(489339 + expected_overload)
    assert displayed_centavos(projection["combined_period_estimate"]) == Decimal("507683.34")
    assert sum(item["combined_estimate"] for item in projection["college_totals"]) == pytest.approx(
        projection["combined_period_estimate"]
    )
    records = {item["faculty_name"]: item for item in projection["records"]}
    assert records["Faculty A"]["period_overload_pay"] == pytest.approx(expected_overload)
    assert records["Faculty B"]["period_overload_pay"] == 0
    assert records["Faculty B"]["overload_weekly_hours"] == 0

    export = client.get("/api/v1/expenses/monthly-projection.csv", params=params)
    assert export.status_code == 200
    rows = list(csv.reader(StringIO(export.text)))
    summary = next(row for row in rows if row and row[0] == "Current projection")
    assert float(summary[3]) == pytest.approx(projection["total_period_salary"])
    assert float(summary[4]) == pytest.approx(projection["teaching_cost"]["total_term_pay"])
    assert float(summary[5]) == pytest.approx(projection["combined_period_estimate"])
