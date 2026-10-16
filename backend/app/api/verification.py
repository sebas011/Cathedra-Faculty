import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.faculty_status import planning_status
from app.models import (
    FacultyNoTeachingConfirmation,
    FacultyProfile,
    FacultyWorkload,
    ProjectionSettings,
)

router = APIRouter(prefix="/verification", tags=["Verification"])


def missing(value: str | None) -> bool:
    return not value or value.strip().casefold() in {"", "to verify", "unassigned"}


@router.get("")
def verification_queue(
    area: Literal["All", "Faculty Profile", "Faculty Workload"] = "All",
    search: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    items: list[dict[str, object]] = []
    counts = {name: 0 for name in ("Faculty Profile", "Faculty Workload")}
    matching_total = 0
    search_value = search.strip().casefold()
    status_as_of = date.today()

    def collect(item: dict[str, object]) -> None:
        nonlocal matching_total
        item_area = item["area"]
        counts[item_area] += 1
        if area != "All" and item_area != area:
            return
        if (
            search_value
            and search_value not in f"{item['name']} {' '.join(item['issues'])}".casefold()
        ):
            return
        matching_total += 1
        if (page - 1) * page_size < matching_total <= page * page_size:
            items.append(item)

    period = db.get(ProjectionSettings, 1)
    faculty_with_workload: set[int] = set()
    faculty_confirmed_not_teaching: set[int] = set()
    if period and period.academic_year.strip() and period.term.strip():
        aliases = {
            "First Semester": ("First Semester", "1st Semester"),
            "1st Semester": ("First Semester", "1st Semester"),
            "Second Semester": ("Second Semester", "2nd Semester"),
            "2nd Semester": ("Second Semester", "2nd Semester"),
        }
        terms = aliases.get(period.term, (period.term,))
        faculty_with_workload = set(
            db.scalars(
                select(FacultyWorkload.faculty_profile_id).where(
                    FacultyWorkload.academic_year == period.academic_year,
                    FacultyWorkload.term.in_(terms),
                )
            )
        )
        faculty_confirmed_not_teaching = set(
            db.scalars(
                select(FacultyNoTeachingConfirmation.faculty_id).where(
                    FacultyNoTeachingConfirmation.academic_year == period.academic_year,
                    FacultyNoTeachingConfirmation.term.in_(terms),
                )
            )
        )

    for profile in db.scalars(select(FacultyProfile).order_by(FacultyProfile.name)).yield_per(100):
        if planning_status(profile, status_as_of) == "excluded":
            continue
        issues: list[str] = []
        if profile.service_status == "To verify":
            issues.append("Active or inactive status needs confirmation")
        if (
            profile.service_status in ("Inactive", "Retired", "Resigned")
            and profile.service_status_effective_date is None
        ):
            issues.append("Faculty status effective date needs confirmation")
        if missing(profile.employment_status):
            issues.append("Employment status needs confirmation")
        if missing(profile.college):
            issues.append("Department needs confirmation")
        if missing(profile.department):
            issues.append("Program needs confirmation")
        if profile.employment_status == "Full-time" and (
            not profile.monthly_salary or profile.monthly_salary <= 0
        ):
            issues.append("Monthly salary is not recorded")
        if (
            period
            and profile.service_status == "Active"
            and profile.id not in faculty_with_workload
            and profile.id not in faculty_confirmed_not_teaching
        ):
            issues.append(f"No workload recorded for {period.academic_year} {period.term}")
        if issues:
            collect(
                {
                    "key": f"faculty-{profile.id}",
                    "area": "Faculty Profile",
                    "name": profile.name,
                    "status": "Needs details",
                    "issues": issues,
                    "action_path": f"/faculty-profiles/{profile.id}",
                }
            )

    workloads = db.execute(
        select(FacultyWorkload, FacultyProfile)
        .join(FacultyProfile, FacultyWorkload.faculty_profile_id == FacultyProfile.id)
        .order_by(FacultyProfile.name, FacultyWorkload.id)
    ).yield_per(100)
    for workload, profile in workloads:
        if planning_status(profile, status_as_of) == "excluded":
            continue
        issues = []
        if workload.workflow_status == "Reopened":
            issues.append("Correction needs review and reapproval")
        try:
            provenance = (
                json.loads(workload.import_provenance) if workload.import_provenance else {}
            )
        except (TypeError, ValueError):
            provenance = {}
            issues.append("Import source information could not be read")
        if (
            isinstance(provenance, dict)
            and provenance.get("batch_id")
            and not provenance.get("projection_rows")
        ):
            issues.append("No reliable overload-projection source row linked")
        if issues:
            collect(
                {
                    "key": f"workload-{workload.id}",
                    "area": "Faculty Workload",
                    "name": profile.name,
                    "status": "Reopened"
                    if workload.workflow_status == "Reopened"
                    else "Needs source review",
                    "issues": issues,
                    "action_path": f"/workload/{workload.id}",
                }
            )

    return {
        "total": sum(counts.values()),
        "matching_total": matching_total,
        "counts": counts,
        "items": items,
        "page": page,
        "page_size": page_size,
    }
