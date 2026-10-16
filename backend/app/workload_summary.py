"""Compute directory totals without loading every course or approval snapshot."""

from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import FacultyProfile, FacultyWorkload, TeachingAssignment, WorkloadCostSettings
from app.workload_read import calculate_teaching_cost


def directory_summary(db: Session, filtered, settings: WorkloadCostSettings) -> dict:
    # SQLite lower() is ASCII-only; match the existing Python casefold policy.
    connection = db.connection().connection.driver_connection
    connection.create_function(
        "cathedra_course_key", 1, lambda value: value.strip().casefold(), deterministic=True
    )
    matching = filtered.with_only_columns(FacultyWorkload.id).order_by(None).subquery()
    courses = (
        select(
            TeachingAssignment.workload_id,
            func.count().label("assignments"),
            func.count(
                func.distinct(func.cathedra_course_key(TeachingAssignment.course_code))
            ).label("preparations"),
            func.sum(TeachingAssignment.lecture_hours + TeachingAssignment.laboratory_hours).label(
                "hours"
            ),
        )
        .join(matching, matching.c.id == TeachingAssignment.workload_id)
        .group_by(TeachingAssignment.workload_id)
        .subquery()
    )
    query = (
        select(
            FacultyWorkload.compensation_category,
            FacultyWorkload.highest_qualification,
            FacultyWorkload.professional_qualification,
            FacultyWorkload.imported_overload_hours,
            FacultyProfile.monthly_salary,
            courses.c.assignments,
            courses.c.preparations,
            courses.c.hours,
        )
        .join(FacultyProfile)
        .join(matching, matching.c.id == FacultyWorkload.id)
        .outerjoin(courses, courses.c.workload_id == FacultyWorkload.id)
        .execution_options(yield_per=256)
    )
    summary = {"assignments": 0, "preparations": 0, "weekly_pay": 0.0}
    for row in db.execute(query).mappings():
        workload = SimpleNamespace(**row)
        hours = row["hours"] or 0
        preparations = row["preparations"] or 0
        overload = row["imported_overload_hours"]
        if overload is None:
            overload = max(hours - (21 if preparations <= 2 else 18), 0)
        _, _, weekly_pay = calculate_teaching_cost(workload, workload, hours, overload, settings)
        summary["assignments"] += row["assignments"] or 0
        summary["preparations"] += preparations
        summary["weekly_pay"] += weekly_pay
    return summary
