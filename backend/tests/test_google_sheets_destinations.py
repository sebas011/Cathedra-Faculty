import json
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    FacultyProfile,
    FacultyWorkload,
    ProjectionSettings,
    QualificationRateDraft,
    SavedProjection,
    SemesterOverloadBudget,
    TeachingAssignment,
    WorkloadCostSettings,
)
from app.services.projection import build_monthly_projection
from app.services.sheets_exports import build_google_sheet_tables


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def faculty(db, name="Current Faculty", **fields):
    profile = FacultyProfile(
        name=name,
        rank="Instructor I",
        employment_status="Full-time",
        college="CIT",
        department="Information Technology",
        monthly_salary=30000,
        **fields,
    )
    db.add(profile)
    db.flush()
    return profile


def workload(db, profile, **fields):
    record = FacultyWorkload(
        faculty_profile_id=profile.id,
        academic_year=fields.pop("academic_year", "2026-2027"),
        term=fields.pop("term", "First Semester"),
        import_provenance='{"private_provenance": "DO-NOT-EXPORT"}',
        **fields,
    )
    record.assignments = [
        TeachingAssignment(
            course_code="TEST101",
            course_title="Saved course",
            year_section="1-A",
            lecture_hours=24,
            laboratory_hours=2,
        )
    ]
    db.add(record)
    db.flush()
    return record


def approval_snapshot(**values):
    return json.dumps(
        {
            "faculty": {
                "name": "Frozen Faculty",
                "college": "CAS",
                "department": "Frozen Department",
                "rank": "Frozen Rank",
                "monthly_salary": "PRIVATE-SALARY-NEVER-EXPORTED",
            },
            "workload": {
                "academic_year": "2026-2027",
                "term": "First Semester",
                "total_weekly_hours": 23,
                "overload_weekly_hours": 2,
                "estimated_teaching_pay_weekly": 999,
                "estimated_teaching_pay_term": 17982,
                "compensation_category": "Regular Faculty",
                **values,
            },
            "approved_by": "PRIVATE-APPROVER-NEVER-EXPORTED",
            "approved_at": "2026-10-01T00:00:00",
        }
    )


def unrelated_corrupt_snapshots(db):
    db.add_all(
        [
            SavedProjection(
                academic_year="2026-2027",
                term="First Semester",
                period="semester",
                created_by="PRIVATE-ACCOUNT",
                projection_json="CORRUPT-FINANCIAL-SNAPSHOT",
            ),
            QualificationRateDraft(
                id=1,
                revision=1,
                combination_rule="highest",
                rates_json="CORRUPT-QUALIFICATION-DRAFT",
                updated_by="PRIVATE-ACCOUNT",
            ),
        ]
    )


def tables_for(db, destination):
    return {table.title: table for table in build_google_sheet_tables(db, destination=destination)}


def records(table):
    return [dict(zip(table.headers, row, strict=True)) for row in table.rows]


@pytest.mark.parametrize(
    ("destination", "titles"),
    [
        ("profiles", ["Overview", "Faculty"]),
        ("workloads", ["Overview", "Workloads", "Assignments", "Approved Workloads"]),
        ("overload", ["Overview", "Overload Projection", "Overload Budgets", "Cost Settings"]),
    ],
)
def test_each_destination_has_only_its_explicit_tables_and_reads_no_unrelated_records(
    db, destination, titles
):
    queries = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        queries.append(statement.lower())

    event.listen(db.bind, "before_cursor_execute", capture)
    tables = tables_for(db, destination)
    event.remove(db.bind, "before_cursor_execute", capture)
    assert list(tables) == [f"Cathedra {title}" for title in titles]
    sql = " ".join(queries)
    for forbidden in (
        "saved_projections",
        "semester_closeout_estimates",
        "qualification_rate_drafts",
        "local_users",
        "local_sessions",
        "activity_events",
        "salary_source",
    ):
        assert forbidden not in sql
    if destination == "profiles":
        assert "faculty_workloads" not in sql
        assert "workload_cost_settings" not in sql
    elif destination == "workloads":
        assert "projection_settings" not in sql
        assert "workload_cost_settings" not in sql
        assert "monthly_salary" not in sql
    assert all(query.lstrip().startswith("select") for query in queries)
    assert db.in_transaction()  # The caller still owns its snapshot and transaction.
    assert not db.new and not db.dirty
    assert db.get(WorkloadCostSettings, 1) is None


def test_profile_export_survives_corrupt_financial_workload_and_draft_snapshots(db):
    profile = faculty(db)
    workload(db, profile, workflow_status="Approved", approval_snapshot="CORRUPT-APPROVAL")
    unrelated_corrupt_snapshots(db)
    db.commit()
    tables = tables_for(db, "profiles")
    row = records(tables["Cathedra Faculty"])[0]
    assert row["Monthly Salary"] == 30000
    assert row["Name"] == profile.name
    assert "CORRUPT" not in str(tables)
    assert "PRIVATE-ACCOUNT" not in str(tables)


def test_workload_export_uses_current_hours_without_settings_and_frozen_approval_hours(db):
    profile = faculty(db)
    current = workload(
        db,
        profile,
        workflow_status="Approved",
        approved_at=datetime(2026, 10, 1),
        approval_snapshot=approval_snapshot(),
        imported_overload_hours=8.25,
    )
    unrelated_corrupt_snapshots(db)
    db.commit()
    tables = tables_for(db, "workloads")
    row = records(tables["Cathedra Workloads"])[0]
    assert row["Faculty Name"] == "Current Faculty"
    assert row["Total Lecture Hours"] == 24
    assert row["Total Laboratory Hours"] == 2
    assert row["Total Weekly Hours"] == 26
    assert row["Regular Weekly Hours"] == 21
    assert row["Calculated Overload Hours"] == 5
    assert row["Overload Weekly Hours"] == 8.25
    assert row["Overload Difference"] is True
    approved = records(tables["Cathedra Approved Workloads"])[0]
    assert approved["Faculty Name"] == "Frozen Faculty"
    assert approved["Weekly Hours"] == 23
    assert approved["Overload Hours"] == 2
    assert approved["College"] == "CAS"
    assert approved["Approved At"] == "2026-10-01T00:00:00"
    assert records(tables["Cathedra Assignments"])[0]["Course Code"] == "TEST101"
    assert db.get(WorkloadCostSettings, 1) is None
    assert db.get(FacultyWorkload, current.id).approval_snapshot == approval_snapshot()
    exported = str(tables)
    for forbidden in (
        "Salary",
        "Weekly Pay",
        "Term Pay",
        "Hourly Rate",
        "Qualification",
        "PRIVATE-SALARY",
        "PRIVATE-APPROVER",
        "DO-NOT-EXPORT",
        "CORRUPT",
    ):
        assert forbidden not in exported
    assert all("Compensation" not in header for item in tables.values() for header in item.headers)


def test_workload_hours_ignore_unrelated_frozen_compensation_values(db):
    profile = faculty(db)
    workload(
        db,
        profile,
        workflow_status="Approved",
        approval_snapshot=approval_snapshot(
            estimated_teaching_pay_weekly={"private": "UNREADABLE-FINANCIAL-FIELD"},
            estimated_teaching_pay_term="UNREADABLE-FINANCIAL-FIELD",
        ),
    )
    db.commit()
    rows = records(tables_for(db, "workloads")["Cathedra Approved Workloads"])
    assert rows[0]["Weekly Hours"] == 23
    assert "UNREADABLE" not in str(rows)


def test_workload_hours_match_existing_preparation_rule_for_three_distinct_courses(db):
    profile = faculty(db)
    current = workload(db, profile)
    current.assignments.extend(
        TeachingAssignment(
            course_code=code,
            course_title="Additional course",
            year_section="1A",
            lecture_hours=1,
            laboratory_hours=0,
        )
        for code in ("TEST102", "TEST103")
    )
    db.commit()
    row = records(tables_for(db, "workloads")["Cathedra Workloads"])[0]
    assert row["Preparation Count"] == 3
    assert row["Regular Weekly Hours"] == 18
    assert row["Calculated Overload Hours"] == 10


@pytest.mark.parametrize("term", ["First Semester", "1st Semester", "Summer"])
def test_overload_matches_existing_regular_faculty_business_math_and_excludes_part_time(db, term):
    regular = faculty(db, "Regular Faculty")
    internal = faculty(db, "Internal Part-time Faculty")
    external = faculty(db, "External Part-time Faculty")
    record = workload(db, regular, term=term, imported_overload_hours=9.25)
    workload(db, internal, term=term, compensation_category="Internal Part-time")
    workload(db, external, term=term, compensation_category="External Part-time")
    settings = WorkloadCostSettings(id=1, first_semester_weeks=16, summer_weeks=5)
    db.add_all(
        [
            settings,
            ProjectionSettings(id=1, academic_year="2026-2027", term=term),
            SemesterOverloadBudget(
                academic_year="2026-2027", term="First Semester", amount_centavos=123456
            ),
        ]
    )
    unrelated_corrupt_snapshots(db)
    db.commit()
    projection = build_monthly_projection(
        db,
        academic_year="2026-2027",
        term=term,
        period="summer" if term == "Summer" else "semester",
    )
    expected = next(row for row in projection.teaching_details if row["workload_id"] == record.id)
    tables = tables_for(db, "overload")
    rows = records(tables["Cathedra Overload Projection"])
    assert len(rows) == 1
    assert rows[0]["Category"] == "Regular Faculty"
    assert rows[0]["Paid Hours"] == 9.25
    assert rows[0]["Hourly Rate"] == expected["hourly_rate"]
    assert rows[0]["Weekly Pay"] == pytest.approx(
        sum(part["weekly_pay"] for part in expected["allocations"])
    )
    assert rows[0]["Term Pay"] == expected["term_pay"]
    assert rows[0]["Inclusion"] == "Included"
    assert records(tables["Cathedra Overload Budgets"])[0]["Amount"] == 1234.56
    headers = " ".join(tables["Cathedra Cost Settings"].headers)
    assert "Internal" not in headers and "External" not in headers
    assert "Monthly Salary" not in str(tables)
    assert "PRIVATE-ACCOUNT" not in str(tables)
    assert "DO-NOT-EXPORT" not in str(tables)
    assert len(tables_for(db, "workloads")["Cathedra Workloads"].rows) == 3


def test_overload_ignores_corrupt_part_time_approval_and_unselected_period(db):
    regular = faculty(db, "Regular")
    external = faculty(db, "External")
    workload(db, regular)
    workload(db, external, compensation_category="External Part-time", approval_snapshot="BAD")
    workload(db, regular, academic_year="2025-2026", approval_snapshot="BAD")
    db.add_all(
        [
            WorkloadCostSettings(id=1),
            ProjectionSettings(id=1, academic_year="2026-2027", term="First Semester"),
        ]
    )
    db.commit()
    assert len(tables_for(db, "overload")["Cathedra Overload Projection"].rows) == 1


def test_overload_keeps_provisional_status_separate_and_reports_missing_rates_and_weeks(db):
    profile = faculty(db, service_status="To verify")
    profile.monthly_salary = 0
    workload(db, profile)
    db.add_all(
        [
            WorkloadCostSettings(id=1, first_semester_weeks=0),
            ProjectionSettings(id=1, academic_year="2026-2027", term="First Semester"),
        ]
    )
    db.commit()
    tables = tables_for(db, "overload")
    row = records(tables["Cathedra Overload Projection"])[0]
    assert row["Inclusion"].startswith("Provisional")
    assert row["Term Pay"] is None
    assert "no hourly rate" in str(tables["Cathedra Overview"].rows)
    assert "configured teaching weeks" in str(tables["Cathedra Overview"].rows)


@pytest.mark.parametrize("missing", ["settings", "period", "both"])
def test_missing_overload_settings_or_period_gives_blank_projection_without_creating_defaults(
    db, missing
):
    if missing == "settings":
        db.add(ProjectionSettings(id=1, academic_year="2026-2027", term="First Semester"))
    elif missing == "period":
        db.add(WorkloadCostSettings(id=1))
    db.commit()
    tables = tables_for(db, "overload")
    assert not tables["Cathedra Overload Projection"].rows
    assert "Warnings / assumptions" in str(tables["Cathedra Overview"].rows)
    assert (db.get(WorkloadCostSettings, 1) is None) == (missing != "period")
    assert (db.get(ProjectionSettings, 1) is None) == (missing != "settings")
    assert not db.new and not db.dirty


@pytest.mark.parametrize("value", [None, True, "PRIVATE-CORRUPT-HOURS", float("nan")])
def test_unreadable_frozen_hours_fail_safely_without_guessing_or_exporting_raw_snapshot(db, value):
    profile = faculty(db)
    workload(
        db,
        profile,
        workflow_status="Approved",
        approval_snapshot=approval_snapshot(total_weekly_hours=value),
    )
    db.commit()
    with pytest.raises(HTTPException) as caught:
        tables_for(db, "workloads")
    assert caught.value.status_code == 409
    assert "PRIVATE" not in caught.value.detail


@pytest.mark.parametrize("destination", ["unknown", "faculty", "", "ALL", 123, []])
def test_invalid_destination_is_rejected_before_reading_business_data(db, destination):
    with pytest.raises(ValueError, match="Choose a Google Sheets destination"):
        build_google_sheet_tables(db, destination=destination)


def test_legacy_export_remains_twelve_tables(db):
    tables = build_google_sheet_tables(db)
    assert len(tables) == 12
    assert any(table.title == "Cathedra Salary Projection" for table in tables)
    assert db.scalars(select(WorkloadCostSettings)).first() is None
