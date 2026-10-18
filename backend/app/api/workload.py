import json
import math
from datetime import date, datetime
from io import StringIO
from pathlib import PureWindowsPath
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.concurrency import advance_revision
from app.csv_export import SafeCsvWriter
from app.db import get_db
from app.faculty_status import workload_status_conflict, workload_term_status_conflict
from app.models import (
    FacultyProfile,
    FacultyWorkload,
    LocalUser,
    ProjectionSettings,
    TeachingAssignment,
    WorkloadApprovalRevision,
    WorkloadCostSettings,
)
from app.services.snapshots import load_approval_snapshot
from app.teaching_allocations import teaching_allocations
from app.workload_read import (
    get_workload_cost_settings_record,
    read_workload,
    workload_options,
)
from app.workload_schemas import (
    FacultyWorkloadCreate,
    FacultyWorkloadRead,
    FacultyWorkloadUpdate,
    WorkloadCostSettingsRead,
    WorkloadCostSettingsUpdate,
    WorkloadReopenRequest,
)
from app.workload_summary import directory_summary

router = APIRouter(prefix="/workloads", tags=["Faculty Workload"])


def canonical_term(value: str) -> str:
    normalized = " ".join(value.split()).casefold()
    return {
        "first semester": "First Semester",
        "1st semester": "First Semester",
        "second semester": "Second Semester",
        "2nd semester": "Second Semester",
        "summer": "Summer",
    }.get(normalized, value.strip())


def period_terms(value: str) -> tuple[str, ...]:
    return {
        "First Semester": ("first semester", "1st semester"),
        "Second Semester": ("second semester", "2nd semester"),
        "Summer": ("summer",),
    }.get(canonical_term(value), (value.strip().casefold(),))


def period_conflict(
    db: Session, faculty_id: int, academic_year: str, term: str, exclude_id: int | None = None
) -> bool:
    variants = period_terms(term)
    statement = select(FacultyWorkload.id).where(
        FacultyWorkload.faculty_profile_id == faculty_id,
        func.trim(FacultyWorkload.academic_year) == academic_year.strip(),
        func.lower(func.trim(FacultyWorkload.term)).in_(variants),
    )
    if exclude_id is not None:
        statement = statement.where(FacultyWorkload.id != exclude_id)
    return db.scalar(statement.limit(1)) is not None


def get_faculty(db: Session, faculty_profile_id: int) -> FacultyProfile:
    faculty = db.get(FacultyProfile, faculty_profile_id)
    if faculty is None:
        raise HTTPException(status_code=404, detail="Faculty member not found.")
    return faculty


def require_workload_term_status(db: Session, workload: FacultyWorkload) -> None:
    faculty = get_faculty(db, workload.faculty_profile_id)
    conflict = workload_term_status_conflict(faculty, workload.academic_year, workload.term)
    active_period = db.get(ProjectionSettings, 1)
    if (
        active_period is not None
        and active_period.academic_year == workload.academic_year
        and canonical_term(active_period.term) == canonical_term(workload.term)
    ):
        conflict = conflict or workload_status_conflict(
            faculty, workload.academic_year, workload.term, date.today()
        )
    if conflict:
        raise HTTPException(
            status_code=409,
            detail="The faculty status or effective date conflicts with this workload period. Confirm eligibility before review or approval.",
        )


def require_workload_salary(db: Session, workload: FacultyWorkload) -> None:
    category = workload.compensation_category or "Regular Faculty"
    if category not in {"Regular Faculty", "Internal Part-time"}:
        return
    faculty = get_faculty(db, workload.faculty_profile_id)
    salary = faculty.monthly_salary
    if salary is not None and math.isfinite(salary) and salary > 0:
        return
    current = read_workload(workload, faculty, get_workload_cost_settings_record(db))
    paid_hours = (
        current.overload_weekly_hours
        if category == "Regular Faculty"
        else current.total_weekly_hours
    )
    if paid_hours > 0:
        raise HTTPException(
            status_code=409,
            detail="Confirm a positive monthly salary for this faculty member before reviewing or approving paid teaching hours.",
        )


def apply_payload(
    workload: FacultyWorkload, payload: FacultyWorkloadCreate | FacultyWorkloadUpdate
) -> None:
    if workload.imported_overload_hours is not None:
        aliases = {"1st Semester": "First Semester", "2nd Semester": "Second Semester"}
        if (
            workload.faculty_profile_id != payload.faculty_profile_id
            or workload.academic_year != payload.academic_year.strip()
            or aliases.get(workload.term, workload.term)
            != aliases.get(payload.term.strip(), payload.term.strip())
            or workload.compensation_category != payload.compensation_category
        ):
            raise HTTPException(
                status_code=409,
                detail="Imported overload hours belong to this faculty, period, and teaching category. Create a new workload for a different scope.",
            )
    workload.faculty_profile_id = payload.faculty_profile_id
    workload.academic_year = payload.academic_year.strip()
    workload.term = canonical_term(payload.term)
    workload.remarks = payload.remarks.strip() if payload.remarks else None
    workload.compensation_category = payload.compensation_category
    workload.highest_qualification = payload.highest_qualification
    workload.professional_qualification = payload.professional_qualification
    workload.professional_qualification_other = payload.professional_qualification_other
    workload.assignments.clear()
    workload.assignments.extend(
        TeachingAssignment(
            course_code=assignment.course_code.strip(),
            course_title=assignment.course_title.strip(),
            year_section=assignment.year_section.strip(),
            lecture_hours=assignment.lecture_hours,
            laboratory_hours=assignment.laboratory_hours,
        )
        for assignment in payload.assignments
    )


def editable_workload(workload: FacultyWorkload) -> None:
    if workload.workflow_status not in {"Draft", "Reopened"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This workload is under review or approved. Reopen it before changing assignments or hours.",
        )


def require_complete_workload(workload: FacultyWorkload) -> None:
    try:
        FacultyWorkloadCreate.model_validate(workload)
    except ValidationError as caught:
        raise HTTPException(
            status_code=409,
            detail="Correct the academic year, term, and course details before review or approval.",
        ) from caught


def workload_record(db: Session, workload_id: int) -> FacultyWorkload:
    workload = db.scalar(
        select(FacultyWorkload)
        .options(*workload_options())
        .where(FacultyWorkload.id == workload_id)
    )
    if workload is None:
        raise HTTPException(status_code=404, detail="Workload record not found.")
    return workload


@router.get("/cost-settings", response_model=WorkloadCostSettingsRead)
def get_workload_cost_settings(
    db: Annotated[Session, Depends(get_db)],
) -> WorkloadCostSettings:
    return get_workload_cost_settings_record(db)


@router.put("/cost-settings", response_model=WorkloadCostSettingsRead)
def update_workload_cost_settings(
    payload: WorkloadCostSettingsUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[LocalUser, Depends(require_admin)],
    if_match: int | None = Header(default=None, alias="If-Match"),
) -> WorkloadCostSettings:
    settings = get_workload_cost_settings_record(db)
    advance_revision(db, WorkloadCostSettings, settings.id, if_match)
    settings.overload_hourly_rate = payload.overload_hourly_rate
    settings.internal_monthly_equivalent_hours = payload.internal_monthly_equivalent_hours
    settings.external_base_hourly_rate = payload.external_base_hourly_rate
    settings.external_masters_increment = payload.external_masters_increment
    settings.external_doctorate_increment = payload.external_doctorate_increment
    settings.external_doctor_increment = payload.external_doctor_increment
    settings.external_lawyer_increment = payload.external_lawyer_increment
    settings.first_semester_weeks = payload.first_semester_weeks
    settings.second_semester_weeks = payload.second_semester_weeks
    settings.summer_weeks = payload.summer_weeks
    db.commit()
    db.refresh(settings)
    return settings


@router.get("/cost-projection")
def workload_cost_projection(
    academic_year: str = Query(default="", max_length=20),
    term: str = Query(default="", max_length=40),
    college: str = Query(default="", max_length=20),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    statement = (
        select(FacultyWorkload, FacultyProfile).join(FacultyProfile).options(*workload_options())
    )
    if academic_year.strip():
        statement = statement.where(FacultyWorkload.academic_year == academic_year.strip())
    if term.strip():
        statement = statement.where(
            func.lower(func.trim(FacultyWorkload.term)).in_(period_terms(term))
        )
    settings = get_workload_cost_settings_record(db)
    records = db.execute(statement).unique().all()
    category_totals: dict[str, dict[str, float | int | str]] = {}
    college_totals: dict[str, dict[str, float | int | str]] = {}
    total_weekly = 0.0
    total_term = 0.0
    unconfigured_term_count = 0
    included_workloads = 0
    allocation_warnings: list[str] = []
    for workload, faculty in records:
        item = read_workload(workload, faculty, settings)
        allocations, _, warning = teaching_allocations(workload, faculty, item)
        allocations = [
            allocation
            for allocation in allocations
            if not college.strip() or allocation["college"] == college.strip()
        ]
        if not allocations:
            continue
        if warning:
            allocation_warnings.append(warning)
        included_workloads += 1
        scoped_weekly = sum(allocation["weekly_pay"] for allocation in allocations)
        scoped_term = (
            sum(allocation["term_pay"] for allocation in allocations)
            if item.estimated_teaching_pay_term is not None
            else 0.0
        )
        total_weekly += scoped_weekly
        if item.estimated_teaching_pay_term is None:
            unconfigured_term_count += 1
        else:
            total_term += scoped_term
        category = category_totals.setdefault(
            item.compensation_category,
            {
                "label": item.compensation_category,
                "workloads": 0,
                "weekly_pay": 0.0,
                "term_pay": 0.0,
            },
        )
        category["workloads"] += 1
        category["weekly_pay"] += scoped_weekly
        category["term_pay"] += scoped_term
        for allocation in allocations:
            key = allocation["college"]
            subtotal = college_totals.setdefault(
                key, {"label": key, "workloads": 0, "weekly_pay": 0.0, "term_pay": 0.0}
            )
            subtotal["workloads"] += 1
            subtotal["weekly_pay"] += allocation["weekly_pay"]
            subtotal["term_pay"] += allocation["term_pay"] or 0
    return {
        "workloads": included_workloads,
        "total_weekly_pay": total_weekly,
        "total_term_pay": total_term,
        "unconfigured_term_count": unconfigured_term_count,
        "category_totals": list(category_totals.values()),
        "college_totals": list(college_totals.values()),
        "allocation_warnings": allocation_warnings,
    }


def workload_review_data(
    db: Session, academic_year: str = "", term: str = "", college: str = ""
) -> dict[str, object]:
    statement = (
        select(FacultyWorkload, FacultyProfile).join(FacultyProfile).options(*workload_options())
    )
    if academic_year.strip():
        statement = statement.where(FacultyWorkload.academic_year == academic_year.strip())
    if term.strip():
        statement = statement.where(
            func.lower(func.trim(FacultyWorkload.term)).in_(period_terms(term))
        )
    if college.strip():
        statement = statement.where(FacultyProfile.college == college.strip())
    settings = get_workload_cost_settings_record(db)
    records = db.execute(statement).unique().all()
    high_load_count = 0
    overload_count = 0
    duplicate_assignment_count = 0
    incomplete_assignment_count = 0
    flagged_records: list[dict[str, object]] = []
    for workload, faculty in records:
        item = read_workload(workload, faculty, settings)
        flags: list[str] = []
        if item.overload_difference:
            flags.append(
                f"Imported overload {item.overload_weekly_hours:g}h differs from calculated {item.calculated_overload_hours:g}h"
            )
        if item.total_weekly_hours > 30:
            high_load_count += 1
            flags.append("Above 30 weekly teaching hours")
        if item.overload_weekly_hours > 0:
            overload_count += 1
        assignment_keys: set[tuple[str, str]] = set()
        has_duplicate = False
        has_incomplete = False
        for assignment in item.assignments:
            key = (
                assignment.course_code.strip().casefold(),
                assignment.year_section.strip().casefold(),
            )
            if key in assignment_keys:
                has_duplicate = True
            assignment_keys.add(key)
            if (
                not assignment.course_code.strip()
                or not assignment.course_title.strip()
                or not assignment.year_section.strip()
                or assignment.lecture_hours + assignment.laboratory_hours <= 0
            ):
                has_incomplete = True
        if has_duplicate:
            duplicate_assignment_count += 1
            flags.append("Duplicate-looking course section")
        if has_incomplete:
            incomplete_assignment_count += 1
            flags.append("Incomplete course details")
        if flags:
            flagged_records.append(
                {
                    "workload_id": item.id,
                    "faculty_name": item.faculty_name,
                    "college": item.college,
                    "academic_year": item.academic_year,
                    "term": item.term,
                    "preparation_count": item.preparation_count,
                    "regular_weekly_hours": item.regular_weekly_hours,
                    "total_weekly_hours": item.total_weekly_hours,
                    "overload_weekly_hours": item.overload_weekly_hours,
                    "flags": flags,
                }
            )
    return {
        "workloads": len(records),
        "high_load_count": high_load_count,
        "overload_count": overload_count,
        "duplicate_assignment_count": duplicate_assignment_count,
        "incomplete_assignment_count": incomplete_assignment_count,
        "items": flagged_records,
    }


def frozen_teaching_allocations(
    snapshot: dict, home_college: str, weekly_pay: float, term_pay: float | None, paid_hours: float
) -> tuple[list[dict], str, str | None]:
    saved = snapshot.get("teaching_allocation")
    if isinstance(saved, dict) and isinstance(saved.get("allocations"), list):
        allocations = saved["allocations"]
        try:
            if not allocations or any(
                not isinstance(part, dict)
                or not isinstance(part.get("college"), str)
                or not part["college"].strip()
                or any(
                    isinstance(part.get(field), bool)
                    or not isinstance(part.get(field), (int, float))
                    or not math.isfinite(part[field])
                    for field in ("paid_hours", "weekly_pay")
                )
                or part["paid_hours"] < 0
                or (
                    part.get("term_pay") is not None
                    and (
                        isinstance(part["term_pay"], bool)
                        or not isinstance(part["term_pay"], (int, float))
                        or not math.isfinite(part["term_pay"])
                    )
                )
                for part in allocations
            ):
                raise ValueError("Invalid frozen allocation")
            if (
                not math.isclose(
                    sum(part["paid_hours"] for part in allocations), paid_hours, abs_tol=0.000001
                )
                or not math.isclose(
                    sum(part["weekly_pay"] for part in allocations), weekly_pay, abs_tol=0.000001
                )
                or (
                    term_pay is None
                    and any(part.get("term_pay") is not None for part in allocations)
                )
                or (
                    term_pay is not None
                    and (
                        any(part.get("term_pay") is None for part in allocations)
                        or not math.isclose(
                            sum(part["term_pay"] for part in allocations),
                            term_pay,
                            abs_tol=0.000001,
                        )
                    )
                )
            ):
                raise ValueError("Frozen allocation does not reconcile")
            return (
                allocations,
                str(saved.get("basis") or "Recorded teaching allocation"),
                saved.get("warning"),
            )
        except (TypeError, ValueError):
            pass
    return (
        [
            {
                "college": home_college,
                "paid_hours": paid_hours,
                "weekly_pay": weekly_pay,
                "term_pay": term_pay,
            }
        ],
        "Legacy approval — teaching allocation not captured",
        "Teaching college was not captured at approval; cost is shown under the home college pending historical review.",
    )


def approved_workload_summary_data(
    db: Session, academic_year: str = "", term: str = "", college: str = ""
) -> dict[str, object]:
    """Return immutable values captured when workloads were approved."""
    statement = (
        select(FacultyWorkload)
        .where(
            FacultyWorkload.workflow_status == "Approved",
            FacultyWorkload.approval_snapshot.is_not(None),
        )
        .order_by(FacultyWorkload.approved_at.desc(), FacultyWorkload.id.desc())
    )
    rows: list[dict[str, object]] = []
    totals: dict[str, float] = {
        "weekly_hours": 0.0,
        "overload_hours": 0.0,
        "weekly_pay": 0.0,
        "term_pay": 0.0,
    }
    college_totals: dict[str, dict[str, float | int | str]] = {}
    allocation_warnings: list[str] = []
    for workload in db.scalars(statement):
        snapshot = load_approval_snapshot(
            workload.approval_snapshot, label=f"Workload #{workload.id} approval snapshot"
        )
        faculty = snapshot["faculty"]
        frozen = snapshot["workload"]
        year, snapshot_term = str(frozen.get("academic_year") or ""), str(frozen.get("term") or "")
        snapshot_college = str(faculty.get("college") or "Unassigned")
        if academic_year.strip() and year != academic_year.strip():
            continue
        if term.strip() and canonical_term(snapshot_term) != canonical_term(term):
            continue
        weekly_hours = float(frozen.get("total_weekly_hours") or 0)
        overload_hours = float(frozen.get("overload_weekly_hours") or 0)
        weekly_pay = float(frozen.get("estimated_teaching_pay_weekly") or 0)
        term_pay = (
            float(frozen["estimated_teaching_pay_term"])
            if frozen.get("estimated_teaching_pay_term") is not None
            else None
        )
        paid_hours = (
            overload_hours
            if frozen.get("compensation_category") == "Regular Faculty"
            else weekly_hours
        )
        allocations, basis, warning = frozen_teaching_allocations(
            snapshot, snapshot_college, weekly_pay, term_pay, paid_hours
        )
        allocations = [
            part
            for part in allocations
            if not college.strip() or part["college"] == college.strip()
        ]
        if not allocations:
            continue
        if warning:
            allocation_warnings.append(f"{faculty.get('name') or 'Unnamed faculty'}: {warning}")
        scoped_weekly = sum(part["weekly_pay"] for part in allocations)
        scoped_term = (
            sum(part["term_pay"] for part in allocations)
            if all(part.get("term_pay") is not None for part in allocations)
            else None
        )
        rows.append(
            {
                "workload_id": workload.id,
                "faculty_name": str(faculty.get("name") or "Unnamed faculty"),
                "college": snapshot_college,
                "department": faculty.get("department"),
                "rank": faculty.get("rank"),
                "academic_year": year,
                "term": snapshot_term,
                "weekly_hours": weekly_hours,
                "overload_hours": overload_hours,
                "weekly_pay": scoped_weekly,
                "term_pay": scoped_term,
                "allocation_basis": basis,
                "allocation_warning": warning,
                "approved_by": snapshot.get("approved_by") or workload.approved_by,
                "approved_at": snapshot.get("approved_at")
                or (workload.approved_at.isoformat() if workload.approved_at else None),
            }
        )
        totals["weekly_hours"] += weekly_hours
        totals["overload_hours"] += overload_hours
        totals["weekly_pay"] += scoped_weekly
        totals["term_pay"] += scoped_term or 0
        for part in allocations:
            key = part["college"]
            subtotal = college_totals.setdefault(
                key,
                {
                    "college": key,
                    "workloads": 0,
                    "paid_hours": 0.0,
                    "weekly_pay": 0.0,
                    "term_pay": 0.0,
                },
            )
            subtotal["workloads"] += 1
            subtotal["paid_hours"] += part["paid_hours"]
            subtotal["weekly_pay"] += part["weekly_pay"]
            subtotal["term_pay"] = (
                None
                if subtotal["term_pay"] is None or part["term_pay"] is None
                else subtotal["term_pay"] + part["term_pay"]
            )
    incomplete_term_count = sum(row["term_pay"] is None for row in rows)
    known_term_pay = totals["term_pay"]
    if incomplete_term_count:
        totals["term_pay"] = None
    return {
        "workloads": len(rows),
        **totals,
        "known_term_pay": known_term_pay,
        "incomplete_term_count": incomplete_term_count,
        "college_totals": list(college_totals.values()),
        "allocation_warnings": allocation_warnings,
        "items": rows,
    }


def historical_allocation_review_data(db: Session) -> dict[str, object]:
    def frozen_number(value: object) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    rows: list[dict[str, object]] = []
    revisions = db.execute(
        select(WorkloadApprovalRevision, FacultyWorkload)
        .join(FacultyWorkload, WorkloadApprovalRevision.workload_id == FacultyWorkload.id)
        .order_by(WorkloadApprovalRevision.approved_at.desc(), WorkloadApprovalRevision.id.desc())
    )
    for revision, workload in revisions:
        try:
            snapshot = json.loads(revision.snapshot)
        except (TypeError, ValueError):
            snapshot = None
        faculty = snapshot.get("faculty") if isinstance(snapshot, dict) else None
        frozen = snapshot.get("workload") if isinstance(snapshot, dict) else None
        if not isinstance(faculty, dict) or not isinstance(frozen, dict):
            rows.append(
                {
                    "approval_revision_id": revision.id,
                    "workload_id": workload.id,
                    "current_status": workload.workflow_status,
                    "issue": "Unreadable frozen approval",
                    "approved_at": revision.approved_at,
                    "approved_by": revision.approved_by,
                }
            )
            continue
        saved = snapshot.get("teaching_allocation")
        if isinstance(saved, dict):
            basis = "Legacy approval"
            try:
                paid_hours = float(
                    frozen.get(
                        "overload_weekly_hours"
                        if frozen.get("compensation_category") == "Regular Faculty"
                        else "total_weekly_hours"
                    )
                    or 0
                )
                _, basis, warning = frozen_teaching_allocations(
                    snapshot,
                    str(faculty.get("college") or "Unassigned"),
                    float(frozen.get("estimated_teaching_pay_weekly") or 0),
                    float(frozen.get("estimated_teaching_pay_term") or 0),
                    paid_hours,
                )
            except (TypeError, ValueError):
                warning = "Frozen amount is unreadable."
            if warning is None:
                continue
            issue = (
                "Invalid frozen allocation"
                if basis.startswith("Legacy approval")
                else "Unverified at approval"
            )
        else:
            issue = "Allocation not captured"
        try:
            provenance = json.loads(frozen.get("import_provenance") or "{}")
        except (TypeError, ValueError):
            provenance = {}
        sources = provenance.get("sources", []) if isinstance(provenance, dict) else []
        assignments = frozen.get("assignments")
        rows.append(
            {
                "approval_revision_id": revision.id,
                "workload_id": workload.id,
                "current_status": workload.workflow_status,
                "issue": issue,
                "faculty_name": str(faculty.get("name") or "Unnamed faculty"),
                "home_college": str(faculty.get("college") or "Unassigned"),
                "academic_year": str(frozen.get("academic_year") or ""),
                "term": str(frozen.get("term") or ""),
                "paid_hours": frozen_number(
                    frozen.get("overload_weekly_hours")
                    if frozen.get("compensation_category") == "Regular Faculty"
                    else frozen.get("total_weekly_hours")
                ),
                "term_pay": frozen_number(frozen.get("estimated_teaching_pay_term")),
                "course_codes": sorted(
                    {
                        str(item.get("course_code"))
                        for item in assignments
                        if isinstance(item, dict) and item.get("course_code")
                    }
                )
                if isinstance(assignments, list)
                else [],
                "source_files": sorted(
                    {PureWindowsPath(source).name for source in sources if isinstance(source, str)}
                )
                if isinstance(sources, list)
                else [],
                "approved_at": revision.approved_at,
                "approved_by": revision.approved_by,
            }
        )
    return {"count": len(rows), "items": rows}


@router.get("/review")
def workload_review(
    academic_year: str = Query(default="", max_length=20),
    term: str = Query(default="", max_length=40),
    college: str = Query(default="", max_length=20),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return workload_review_data(db, academic_year, term, college)


@router.get("/approved-summary")
def approved_workload_summary(
    academic_year: str = Query(default="", max_length=20),
    term: str = Query(default="", max_length=40),
    college: str = Query(default="", max_length=20),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return approved_workload_summary_data(db, academic_year, term, college)


@router.get("/historical-allocation-review")
def historical_allocation_review(
    db: Session = Depends(get_db), _: LocalUser = Depends(require_admin)
) -> dict[str, object]:
    return historical_allocation_review_data(db)


@router.get("/review.csv")
def export_workload_review(
    academic_year: str = Query(default="", max_length=20),
    term: str = Query(default="", max_length=40),
    college: str = Query(default="", max_length=20),
    db: Session = Depends(get_db),
) -> Response:
    review = workload_review_data(db, academic_year, term, college)
    output = StringIO(newline="")
    writer = SafeCsvWriter(output)
    writer.writerow(["Cathedra Faculty Workload Review"])
    writer.writerow(["Academic year", academic_year or "All academic years"])
    writer.writerow(["Term", term or "All terms"])
    writer.writerow(["College", college or "All colleges"])
    writer.writerow([])
    writer.writerow(["Workloads reviewed", review["workloads"]])
    writer.writerow(["Above 30 weekly hours", review["high_load_count"]])
    writer.writerow(["With overload hours", review["overload_count"]])
    writer.writerow(["Duplicate-looking course sections", review["duplicate_assignment_count"]])
    writer.writerow(["Incomplete course details", review["incomplete_assignment_count"]])
    writer.writerow([])
    writer.writerow(
        [
            "Faculty member",
            "College",
            "Academic year",
            "Term",
            "Preps",
            "Regular load",
            "Weekly hours",
            "Overload hours",
            "Review flags",
        ]
    )
    for item in review["items"]:
        writer.writerow(
            [
                item["faculty_name"],
                item["college"],
                item["academic_year"],
                item["term"],
                item["preparation_count"],
                item["regular_weekly_hours"],
                item["total_weekly_hours"],
                item["overload_weekly_hours"],
                "; ".join(item["flags"]),
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="cathedra-workload-review.csv"'},
    )


@router.get("", response_model=list[FacultyWorkloadRead])
def list_workloads(
    search: str = Query(default="", max_length=200),
    academic_year: str = Query(default="", max_length=20),
    term: str = Query(default="", max_length=40),
    college: str = Query(default="", max_length=20),
    db: Session = Depends(get_db),
) -> list[FacultyWorkloadRead]:
    statement = (
        select(FacultyWorkload, FacultyProfile).join(FacultyProfile).options(*workload_options())
    )
    if search.strip():
        search_term = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                FacultyProfile.name.ilike(search_term),
                FacultyProfile.department.ilike(search_term),
                FacultyProfile.rank.ilike(search_term),
                FacultyWorkload.academic_year.ilike(search_term),
                FacultyWorkload.term.ilike(search_term),
            )
        )
    if academic_year.strip():
        statement = statement.where(FacultyWorkload.academic_year == academic_year.strip())
    if term.strip():
        statement = statement.where(
            func.lower(func.trim(FacultyWorkload.term)).in_(period_terms(term))
        )
    if college.strip():
        statement = statement.where(FacultyProfile.college == college.strip())
    records = (
        db.execute(statement.order_by(FacultyProfile.name, FacultyWorkload.academic_year.desc()))
        .unique()
        .all()
    )
    settings = get_workload_cost_settings_record(db)
    return [read_workload(workload, faculty, settings) for workload, faculty in records]


@router.get("/page")
def paged_workloads(
    search: str = Query(default="", max_length=200),
    academic_year: str = Query(default="", max_length=20),
    term: str = Query(default="", max_length=40),
    college: str = Query(default="", max_length=20),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=10, le=100),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    statement = (
        select(FacultyWorkload, FacultyProfile).join(FacultyProfile).options(*workload_options())
    )
    if search.strip():
        search_term = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                FacultyProfile.name.ilike(search_term),
                FacultyProfile.department.ilike(search_term),
                FacultyProfile.rank.ilike(search_term),
                FacultyWorkload.academic_year.ilike(search_term),
                FacultyWorkload.term.ilike(search_term),
            )
        )
    if academic_year.strip():
        statement = statement.where(FacultyWorkload.academic_year == academic_year.strip())
    if term.strip():
        statement = statement.where(
            func.lower(func.trim(FacultyWorkload.term)).in_(period_terms(term))
        )
    if college.strip():
        statement = statement.where(FacultyProfile.college == college.strip())
    total = (
        db.scalar(
            select(func.count()).select_from(
                statement.with_only_columns(FacultyWorkload.id).order_by(None).subquery()
            )
        )
        or 0
    )
    records = (
        db.execute(
            statement.order_by(FacultyProfile.name, FacultyWorkload.academic_year.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .unique()
        .all()
    )
    settings = get_workload_cost_settings_record(db)
    summary = directory_summary(db, statement, settings)
    return {
        "items": [read_workload(workload, faculty, settings) for workload, faculty in records],
        "total": total,
        "summary": summary,
        "page": page,
        "page_size": page_size,
    }


@router.get("/summary")
def workload_summary(db: Session = Depends(get_db)) -> dict[str, float | int]:
    totals = db.execute(
        select(
            func.count(func.distinct(FacultyWorkload.id)),
            func.count(TeachingAssignment.id),
            func.coalesce(func.sum(TeachingAssignment.lecture_hours), 0),
            func.coalesce(func.sum(TeachingAssignment.laboratory_hours), 0),
        )
        .select_from(FacultyWorkload)
        .outerjoin(TeachingAssignment)
    ).one()
    return {
        "workloads": totals[0] or 0,
        "assignments": totals[1] or 0,
        "lecture_hours": float(totals[2] or 0),
        "laboratory_hours": float(totals[3] or 0),
        "weekly_hours": float((totals[2] or 0) + (totals[3] or 0)),
    }


@router.get("/{workload_id}", response_model=FacultyWorkloadRead)
def get_workload(workload_id: int, db: Session = Depends(get_db)) -> FacultyWorkloadRead:
    record = (
        db.execute(
            select(FacultyWorkload, FacultyProfile)
            .join(FacultyProfile)
            .options(*workload_options())
            .where(FacultyWorkload.id == workload_id)
        )
        .unique()
        .one_or_none()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Workload record not found.")
    return read_workload(*record, get_workload_cost_settings_record(db))


@router.post("", response_model=FacultyWorkloadRead, status_code=status.HTTP_201_CREATED)
def create_workload(
    payload: FacultyWorkloadCreate, db: Session = Depends(get_db)
) -> FacultyWorkloadRead:
    faculty = get_faculty(db, payload.faculty_profile_id)
    if workload_status_conflict(faculty, payload.academic_year, payload.term, date.today()):
        raise HTTPException(
            status_code=409,
            detail="The faculty status or effective date conflicts with this workload period.",
        )
    if (
        faculty.college in ("", "Unassigned")
        or faculty.department in ("", "To verify")
        or faculty.employment_status in ("", "To verify")
    ):
        raise HTTPException(
            status_code=409,
            detail="Verify this faculty profile's college, department, and employment status before adding a workload.",
        )
    if period_conflict(db, payload.faculty_profile_id, payload.academic_year, payload.term):
        raise HTTPException(
            status_code=409, detail="A workload already exists for this faculty member and period."
        )
    workload = FacultyWorkload()
    apply_payload(workload, payload)
    db.add(workload)
    try:
        db.commit()
    except IntegrityError as caught:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A workload already exists for this faculty member and period."
        ) from caught
    db.refresh(workload)
    return get_workload(workload.id, db)


@router.put("/{workload_id}", response_model=FacultyWorkloadRead)
def update_workload(
    workload_id: int,
    payload: FacultyWorkloadUpdate,
    db: Session = Depends(get_db),
    if_match: int | None = Header(default=None, alias="If-Match"),
) -> FacultyWorkloadRead:
    workload = workload_record(db, workload_id)
    editable_workload(workload)
    faculty = get_faculty(db, payload.faculty_profile_id)
    scope_changed = (
        faculty.id != workload.faculty_profile_id
        or payload.academic_year.strip() != workload.academic_year.strip()
        or canonical_term(payload.term) != canonical_term(workload.term)
    )
    if scope_changed and workload_status_conflict(
        faculty, payload.academic_year, payload.term, date.today()
    ):
        raise HTTPException(
            status_code=409,
            detail="The faculty status or effective date conflicts with this workload period.",
        )
    if (
        faculty.college in ("", "Unassigned")
        or faculty.department in ("", "To verify")
        or faculty.employment_status in ("", "To verify")
    ):
        raise HTTPException(
            status_code=409,
            detail="Verify this faculty profile's college, department, and employment status before editing a workload.",
        )
    if period_conflict(
        db, payload.faculty_profile_id, payload.academic_year, payload.term, workload_id
    ):
        raise HTTPException(
            status_code=409, detail="A workload already exists for this faculty member and period."
        )
    advance_revision(db, FacultyWorkload, workload_id, if_match)
    apply_payload(workload, payload)
    try:
        db.commit()
    except IntegrityError as caught:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A workload already exists for this faculty member and period."
        ) from caught
    return get_workload(workload_id, db)


@router.post("/{workload_id}/review", response_model=FacultyWorkloadRead)
def review_workload(
    workload_id: int,
    db: Session = Depends(get_db),
    user: LocalUser = Depends(require_admin),
    if_match: int | None = Header(default=None, alias="If-Match"),
) -> FacultyWorkloadRead:
    workload = workload_record(db, workload_id)
    editable_workload(workload)
    require_complete_workload(workload)
    require_workload_term_status(db, workload)
    require_workload_salary(db, workload)
    advance_revision(db, FacultyWorkload, workload_id, if_match)
    workload.workflow_status = "Reviewed"
    workload.reviewed_at = datetime.now()
    workload.reviewed_by = user.username
    db.commit()
    return get_workload(workload_id, db)


@router.post("/{workload_id}/approve", response_model=FacultyWorkloadRead)
def approve_workload(
    workload_id: int,
    db: Session = Depends(get_db),
    user: LocalUser = Depends(require_admin),
    if_match: int | None = Header(default=None, alias="If-Match"),
) -> FacultyWorkloadRead:
    workload = workload_record(db, workload_id)
    if workload.workflow_status != "Reviewed":
        raise HTTPException(status_code=409, detail="Review the workload before approving it.")
    require_complete_workload(workload)
    require_workload_term_status(db, workload)
    require_workload_salary(db, workload)
    advance_revision(db, FacultyWorkload, workload_id, if_match)
    faculty = get_faculty(db, workload.faculty_profile_id)
    current = read_workload(workload, faculty, get_workload_cost_settings_record(db))
    allocations, allocation_basis, allocation_warning = teaching_allocations(
        workload, faculty, current
    )
    previous_approval_id = db.scalar(
        select(WorkloadApprovalRevision.id)
        .where(WorkloadApprovalRevision.workload_id == workload_id)
        .order_by(WorkloadApprovalRevision.id.desc())
        .limit(1)
    )
    workload.workflow_status = "Approved"
    workload.approved_at = datetime.now()
    workload.approved_by = user.username
    workload.approval_snapshot = json.dumps(
        {
            "faculty": {
                "name": faculty.name,
                "rank": faculty.rank,
                "college": faculty.college,
                "department": faculty.department,
                "salary_grade": faculty.salary_grade,
                "salary_step": faculty.salary_step,
                "monthly_salary": faculty.monthly_salary,
            },
            "workload": current.model_dump(
                mode="json",
                exclude={
                    "approval_snapshot",
                    "workflow_status",
                    "reviewed_at",
                    "reviewed_by",
                    "approved_at",
                    "approved_by",
                    "reopened_at",
                    "reopened_by",
                    "reopen_reason",
                },
            ),
            "teaching_allocation": {
                "basis": allocation_basis,
                "warning": allocation_warning,
                "allocations": allocations,
            },
            "approved_by": user.username,
            "approved_at": workload.approved_at.isoformat(),
            "correction_of_revision_id": previous_approval_id,
            "correction_reason": workload.reopen_reason if previous_approval_id else None,
        }
    )
    db.add(
        WorkloadApprovalRevision(
            workload_id=workload.id,
            snapshot=workload.approval_snapshot,
            approved_by=user.username,
            approved_at=workload.approved_at,
        )
    )
    db.commit()
    return get_workload(workload_id, db)


@router.post("/{workload_id}/reopen", response_model=FacultyWorkloadRead)
def reopen_workload(
    workload_id: int,
    payload: WorkloadReopenRequest,
    db: Session = Depends(get_db),
    user: LocalUser = Depends(require_admin),
    if_match: int | None = Header(default=None, alias="If-Match"),
) -> FacultyWorkloadRead:
    workload = workload_record(db, workload_id)
    if workload.workflow_status not in {"Reviewed", "Approved"}:
        raise HTTPException(
            status_code=409, detail="Only reviewed or approved workloads can be reopened."
        )
    advance_revision(db, FacultyWorkload, workload_id, if_match)
    workload.workflow_status = "Reopened"
    workload.reopened_at = datetime.now()
    workload.reopened_by = user.username
    workload.reopen_reason = payload.reason.strip()
    db.commit()
    return get_workload(workload_id, db)


@router.get("/{workload_id}/approvals")
def workload_approval_history(
    workload_id: int, db: Session = Depends(get_db)
) -> list[dict[str, object]]:
    workload_record(db, workload_id)
    revisions = db.scalars(
        select(WorkloadApprovalRevision)
        .where(WorkloadApprovalRevision.workload_id == workload_id)
        .order_by(WorkloadApprovalRevision.id)
    ).all()
    return [
        {
            "id": revision.id,
            "approved_by": revision.approved_by,
            "approved_at": revision.approved_at,
            "snapshot": load_approval_snapshot(
                revision.snapshot, label=f"Approval revision #{revision.id}"
            ),
        }
        for revision in revisions
    ]


@router.delete("/{workload_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workload(
    workload_id: int,
    db: Session = Depends(get_db),
    _: LocalUser = Depends(require_admin),
    if_match: int | None = Header(default=None, alias="If-Match"),
) -> Response:
    workload = db.get(FacultyWorkload, workload_id)
    if workload is None:
        raise HTTPException(status_code=404, detail="Workload record not found.")
    advance_revision(db, FacultyWorkload, workload_id, if_match)
    db.refresh(workload)
    if (
        workload.workflow_status == "Approved"
        or workload.approval_snapshot
        or db.scalar(
            select(WorkloadApprovalRevision.id)
            .where(WorkloadApprovalRevision.workload_id == workload_id)
            .limit(1)
        )
        is not None
    ):
        raise HTTPException(
            status_code=409, detail="A workload with approval history cannot be deleted."
        )
    db.delete(workload)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
