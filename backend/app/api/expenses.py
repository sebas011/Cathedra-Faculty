import json
from datetime import date
from decimal import Decimal
from io import StringIO
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.concurrency import advance_revision, require_new_revision
from app.csv_export import SafeCsvWriter
from app.db import get_db
from app.expense_schemas import (
    MonthlySalaryProjectionRead,
    NoTeachingConfirmationRead,
    OverloadCoverage,
    ProjectionReadinessRead,
    SavedProjectionRead,
    SavedProjectionSummary,
)
from app.faculty_status import planning_status, term_status_transition
from app.models import (
    FacultyNoTeachingConfirmation,
    FacultyProfile,
    FacultyWorkload,
    LocalUser,
    ProjectionSettings,
    SavedProjection,
    SemesterCloseoutEstimate,
    SemesterOverloadBudget,
)
from app.teaching_allocations import COLLEGE_ORDER, teaching_allocations
from app.workload_read import get_workload_cost_settings_record, read_workload, workload_options

router = APIRouter(prefix="/expenses", tags=["Expenses Projection"])


class ActivePeriod(BaseModel):
    academic_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    term: Literal["First Semester", "Second Semester"]

    @model_validator(mode="after")
    def validate_year(self):
        start, end = map(int, self.academic_year.split("-"))
        if end != start + 1:
            raise ValueError("Academic year must contain consecutive years.")
        return self


class OverloadBudgetInput(ActivePeriod):
    amount: Decimal = Field(gt=0, le=Decimal("999999999.99"), decimal_places=2)


class OverloadBudgetRead(ActivePeriod):
    id: int
    revision: int
    amount: float


def read_overload_budget(budget: SemesterOverloadBudget) -> OverloadBudgetRead:
    return OverloadBudgetRead(
        id=budget.id,
        revision=budget.revision,
        academic_year=budget.academic_year,
        term=budget.term,
        amount=budget.amount_centavos / 100,
    )


@router.get("/overload-budgets", response_model=list[OverloadBudgetRead])
def list_overload_budgets(
    db: Annotated[Session, Depends(get_db)], _: Annotated[LocalUser, Depends(require_admin)]
):
    budgets = db.scalars(
        select(SemesterOverloadBudget).order_by(
            SemesterOverloadBudget.academic_year.desc(), SemesterOverloadBudget.term
        )
    ).all()
    return [read_overload_budget(budget) for budget in budgets]


@router.put("/overload-budgets", response_model=OverloadBudgetRead)
def save_overload_budget(
    payload: OverloadBudgetInput,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[LocalUser, Depends(require_admin)],
    if_match: int | None = Header(default=None, alias="If-Match"),
):
    budget = db.scalar(
        select(SemesterOverloadBudget).where(
            SemesterOverloadBudget.academic_year == payload.academic_year,
            SemesterOverloadBudget.term == payload.term,
        )
    )
    if budget is None:
        require_new_revision(if_match)
        budget = SemesterOverloadBudget(
            academic_year=payload.academic_year, term=payload.term, revision=1
        )
        db.add(budget)
    else:
        advance_revision(db, SemesterOverloadBudget, budget.id, if_match)
    budget.amount_centavos = int(payload.amount * 100)
    try:
        db.commit()
    except IntegrityError as caught:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="This budget changed in another window. Reload before saving."
        ) from caught
    db.refresh(budget)
    return read_overload_budget(budget)


@router.delete("/overload-budgets/{budget_id}", status_code=204)
def delete_overload_budget(
    budget_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[LocalUser, Depends(require_admin)],
    if_match: int | None = Header(default=None, alias="If-Match"),
):
    budget = db.get(SemesterOverloadBudget, budget_id)
    if budget is None:
        raise HTTPException(status_code=404, detail="Semester overload budget not found.")
    advance_revision(db, SemesterOverloadBudget, budget_id, if_match)
    db.delete(budget)
    db.commit()


def semester_terms(term: str) -> tuple[str, ...]:
    return {
        "First Semester": ("First Semester", "1st Semester"),
        "Second Semester": ("Second Semester", "2nd Semester"),
    }[term]


@router.put("/no-teaching-confirmations/{faculty_id}", response_model=NoTeachingConfirmationRead)
def confirm_not_teaching(
    faculty_id: int,
    period: ActivePeriod,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[LocalUser, Depends(require_admin)],
):
    faculty = db.get(FacultyProfile, faculty_id)
    if faculty is None:
        raise HTTPException(status_code=404, detail="Faculty profile not found.")
    if faculty.employment_status != "Full-time":
        raise HTTPException(
            status_code=409, detail="Only full-time faculty can be confirmed as not teaching."
        )
    if (
        faculty.service_status in ("Inactive", "Retired", "Resigned")
        and planning_status(faculty, date.today()) != "included"
    ):
        raise HTTPException(
            status_code=409,
            detail="Confirm the faculty member's active status before recording current no-teaching coverage.",
        )
    existing_workload = db.scalar(
        select(FacultyWorkload.id)
        .where(
            FacultyWorkload.faculty_profile_id == faculty_id,
            FacultyWorkload.academic_year == period.academic_year,
            FacultyWorkload.term.in_(semester_terms(period.term)),
        )
        .limit(1)
    )
    if existing_workload is not None:
        raise HTTPException(
            status_code=409,
            detail="This faculty member already has a workload in the selected semester.",
        )
    confirmation = db.scalar(
        select(FacultyNoTeachingConfirmation).where(
            FacultyNoTeachingConfirmation.faculty_id == faculty_id,
            FacultyNoTeachingConfirmation.academic_year == period.academic_year,
            FacultyNoTeachingConfirmation.term == period.term,
        )
    )
    if confirmation is None:
        confirmation = FacultyNoTeachingConfirmation(
            faculty_id=faculty_id,
            academic_year=period.academic_year,
            term=period.term,
            confirmed_by=user.username,
        )
        db.add(confirmation)
        db.commit()
        db.refresh(confirmation)
    return NoTeachingConfirmationRead(
        faculty_id=faculty_id,
        faculty_name=faculty.name,
        academic_year=confirmation.academic_year,
        term=confirmation.term,
        confirmed_by=confirmation.confirmed_by,
        confirmed_at=confirmation.confirmed_at,
    )


@router.delete("/no-teaching-confirmations/{faculty_id}", status_code=204)
def remove_no_teaching_confirmation(
    faculty_id: int,
    academic_year: str,
    term: Literal["First Semester", "Second Semester"],
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[LocalUser, Depends(require_admin)],
):
    try:
        period = ActivePeriod(academic_year=academic_year, term=term)
    except ValidationError as caught:
        raise HTTPException(
            status_code=422, detail="Enter consecutive academic years, such as 2026-2027."
        ) from caught
    confirmation = db.scalar(
        select(FacultyNoTeachingConfirmation).where(
            FacultyNoTeachingConfirmation.faculty_id == faculty_id,
            FacultyNoTeachingConfirmation.academic_year == period.academic_year,
            FacultyNoTeachingConfirmation.term == period.term,
        )
    )
    if confirmation is None:
        raise HTTPException(status_code=404, detail="No-teaching confirmation not found.")
    db.delete(confirmation)
    db.commit()


@router.get("/active-period")
def get_active_period(
    db: Annotated[Session, Depends(get_db)], _: Annotated[LocalUser, Depends(require_admin)]
):
    settings = db.get(ProjectionSettings, 1)
    return (
        {
            "academic_year": settings.academic_year,
            "term": settings.term,
            "revision": settings.revision,
        }
        if settings
        else None
    )


@router.put("/active-period")
def save_active_period(
    payload: ActivePeriod,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[LocalUser, Depends(require_admin)],
    if_match: int | None = Header(default=None, alias="If-Match"),
):
    settings = db.get(ProjectionSettings, 1)
    if settings is None:
        require_new_revision(if_match)
        settings = ProjectionSettings(id=1, revision=1)
        db.add(settings)
    else:
        advance_revision(db, ProjectionSettings, 1, if_match)
    settings.academic_year = payload.academic_year
    settings.term = payload.term
    try:
        db.commit()
    except IntegrityError as caught:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The office period changed in another window. Reload before saving.",
        ) from caught
    db.refresh(settings)
    return {
        "academic_year": settings.academic_year,
        "term": settings.term,
        "revision": settings.revision,
    }


SCOPE_NOTE = (
    "Planning estimate using current saved salaries and teaching compensation for the selected scope. "
    "Excludes allowances, deductions, and actual payroll disbursement."
)


def csv_download(filename: str, rows: list[list[object]]) -> Response:
    output = StringIO(newline="")
    writer = SafeCsvWriter(output)
    writer.writerows(rows)
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def teaching_cost_snapshot(
    db: Session,
    academic_year: str | None = None,
    term: str | None = None,
    college: str | None = None,
    employment_status: str | None = None,
    details: list | None = None,
    covered_faculty: set | None = None,
    status_as_of: date | None = None,
    status_bucket: Literal["included", "provisional"] | None = None,
) -> dict[str, float | int]:
    settings = get_workload_cost_settings_record(db)
    statement = (
        select(FacultyWorkload, FacultyProfile).join(FacultyProfile).options(*workload_options())
    )
    if academic_year:
        statement = statement.where(FacultyWorkload.academic_year == academic_year)
    if term:
        aliases = {
            "First Semester": ("First Semester", "1st Semester"),
            "1st Semester": ("First Semester", "1st Semester"),
            "Second Semester": ("Second Semester", "2nd Semester"),
            "2nd Semester": ("Second Semester", "2nd Semester"),
        }
        statement = statement.where(FacultyWorkload.term.in_(aliases.get(term, (term,))))
    if employment_status:
        statement = statement.where(FacultyProfile.employment_status == employment_status)
    records = db.execute(statement).unique().all()
    total_weekly_pay = 0.0
    total_term_pay = 0.0
    unconfigured_term_count = 0
    workload_count = 0
    for workload, faculty in records:
        if (
            faculty.college in ("", "Unassigned")
            or faculty.department in ("", "To verify")
            or faculty.employment_status in ("", "To verify")
        ):
            continue
        if status_as_of is not None and status_bucket is not None:
            classified_as_included = planning_status(faculty, status_as_of) == "included"
            if classified_as_included != (status_bucket == "included"):
                continue
        if covered_faculty is not None:
            covered_faculty.add(faculty.id)
        item = read_workload(workload, faculty, settings)
        allocations, basis, warning = teaching_allocations(workload, faculty, item)
        allocations = [
            entry for entry in allocations if college is None or entry["college"] == college
        ]
        if not allocations:
            continue
        workload_count += 1
        scoped_term_pay = (
            None
            if item.estimated_teaching_pay_term is None
            else sum(entry["term_pay"] for entry in allocations)
        )
        if details is not None:
            details.append(
                {
                    "home_college": faculty.college,
                    "allocations": allocations,
                    "allocation_basis": basis,
                    "allocation_warning": warning,
                    "workload_id": workload.id,
                    "faculty_id": faculty.id,
                    "faculty_name": faculty.name,
                    "faculty_status": faculty.service_status,
                    "status_effective_date": faculty.service_status_effective_date,
                    "term": workload.term,
                    "category": item.compensation_category,
                    "monthly_salary": faculty.monthly_salary or 0,
                    "hourly_rate": item.compensation_hourly_rate,
                    "paid_hours": sum(entry["paid_hours"] for entry in allocations),
                    "weeks": item.projection_weeks,
                    "term_pay": scoped_term_pay,
                    "imported_overload_hours": item.imported_overload_hours,
                    "calculated_overload_hours": item.calculated_overload_hours,
                    "regular_weekly_hours": item.regular_weekly_hours,
                    "overload_weekly_hours": item.overload_weekly_hours,
                }
            )
        total_weekly_pay += sum(entry["weekly_pay"] for entry in allocations)
        if item.estimated_teaching_pay_term is None:
            unconfigured_term_count += 1
        else:
            total_term_pay += scoped_term_pay
    return {
        "workloads": workload_count,
        "total_weekly_pay": total_weekly_pay,
        "total_term_pay": total_term_pay,
        "unconfigured_term_count": unconfigured_term_count,
    }


def overload_coverage_snapshot(
    db: Session,
    academic_year: str,
    term: str,
    profiles: list[FacultyProfile],
    details: list[dict],
    as_of: date | None = None,
) -> OverloadCoverage:
    aliases = {
        "First Semester": ("First Semester", "1st Semester"),
        "1st Semester": ("First Semester", "1st Semester"),
        "Second Semester": ("Second Semester", "2nd Semester"),
        "2nd Semester": ("Second Semester", "2nd Semester"),
    }
    workloads = db.execute(
        select(FacultyWorkload, FacultyProfile)
        .join(FacultyProfile)
        .where(
            FacultyWorkload.academic_year == academic_year,
            FacultyWorkload.term.in_(aliases.get(term, (term,))),
        )
    ).all()
    workload_faculty_ids = {faculty.id for _, faculty in workloads}
    confirmed = db.scalars(
        select(FacultyNoTeachingConfirmation).where(
            FacultyNoTeachingConfirmation.academic_year == academic_year,
            FacultyNoTeachingConfirmation.term == term,
        )
    ).all()
    faculty_by_id = {faculty.id: faculty for faculty in profiles}
    active_confirmations = [
        item
        for item in confirmed
        if item.faculty_id in faculty_by_id
        and faculty_by_id[item.faculty_id].employment_status == "Full-time"
        and planning_status(faculty_by_id[item.faculty_id], as_of or date.today()) == "included"
        and item.faculty_id not in workload_faculty_ids
    ]
    confirmed_faculty_ids = {item.faculty_id for item in active_confirmations}
    regular_workloads = [
        (workload, faculty)
        for workload, faculty in workloads
        if (workload.compensation_category or "Regular Faculty") == "Regular Faculty"
    ]
    regular_details = [item for item in details if item["category"] == "Regular Faculty"]
    included_ids = {item["workload_id"] for item in regular_details}
    issues = []
    for workload, faculty in regular_workloads:
        status_needs_review = planning_status(faculty, as_of or date.today()) != "included"
        if status_needs_review:
            issues.append(
                {
                    "faculty_id": faculty.id,
                    "faculty_name": faculty.name,
                    "workload_id": workload.id,
                    "reason": "Faculty status needs review for this estimate",
                    "action_path": f"/faculty-profiles/{faculty.id}",
                }
            )
        if workload.id not in included_ids and not status_needs_review:
            issues.append(
                {
                    "faculty_id": faculty.id,
                    "faculty_name": faculty.name,
                    "workload_id": workload.id,
                    "reason": "Workload excluded: verify faculty appointment details",
                    "action_path": f"/faculty-profiles/{faculty.id}",
                }
            )
    for faculty in profiles:
        if (
            faculty.employment_status == "Full-time"
            and planning_status(faculty, as_of or date.today()) == "included"
            and faculty.id not in workload_faculty_ids
            and faculty.id not in confirmed_faculty_ids
        ):
            issues.append(
                {
                    "faculty_id": faculty.id,
                    "faculty_name": faculty.name,
                    "workload_id": None,
                    "reason": "No workload in this semester: confirm teaching coverage",
                    "action_path": f"/faculty-profiles/{faculty.id}",
                }
            )
    for item in regular_details:
        if item["paid_hours"] <= 0:
            continue
        if item["term_pay"] is None:
            issues.append(
                {
                    "faculty_id": item["faculty_id"],
                    "faculty_name": item["faculty_name"],
                    "workload_id": item["workload_id"],
                    "reason": "Teaching weeks not configured",
                    "action_path": f"/workload/{item['workload_id']}",
                }
            )
        if item["hourly_rate"] <= 0:
            issues.append(
                {
                    "faculty_id": item["faculty_id"],
                    "faculty_name": item["faculty_name"],
                    "workload_id": item["workload_id"],
                    "reason": "Overload hourly rate missing",
                    "action_path": f"/faculty-profiles/{item['faculty_id']}",
                }
            )
    issues.sort(key=lambda item: (item["reason"], item["faculty_name"], item["workload_id"] or 0))
    return OverloadCoverage(
        provisional=bool(issues) or not (regular_workloads or active_confirmations),
        regular_workloads=len(regular_workloads),
        included_workloads=len(regular_details),
        missing_workloads=sum(item["workload_id"] is None for item in issues),
        confirmed_not_teaching=len(active_confirmations),
        excluded_workloads=len(regular_workloads) - len(regular_details),
        missing_rates=sum(item["reason"] == "Overload hourly rate missing" for item in issues),
        missing_weeks=sum(item["reason"] == "Teaching weeks not configured" for item in issues),
        issues=issues,
        confirmations=[
            NoTeachingConfirmationRead(
                faculty_id=item.faculty_id,
                faculty_name=faculty_by_id[item.faculty_id].name,
                academic_year=item.academic_year,
                term=item.term,
                confirmed_by=item.confirmed_by,
                confirmed_at=item.confirmed_at,
            )
            for item in active_confirmations
        ],
    )


@router.get("/projection-readiness", response_model=ProjectionReadinessRead)
def projection_readiness(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[LocalUser, Depends(require_admin)],
) -> ProjectionReadinessRead:
    profiles = list(db.scalars(select(FacultyProfile)).all())
    profiles_missing_salary = sum(
        1
        for profile in profiles
        if not profile.salary_grade
        or profile.salary_step < 1
        or not profile.monthly_salary
        or profile.monthly_salary <= 0
    )
    profiles_missing_org = sum(
        1
        for profile in profiles
        if profile.college == "Unassigned"
        or profile.department == "To verify"
        or profile.employment_status == "To verify"
        or not profile.college.strip()
        or not profile.department.strip()
        or not profile.employment_status.strip()
    )
    profiles_status_to_verify = sum(
        planning_status(profile, date.today()) == "provisional" for profile in profiles
    )
    settings = get_workload_cost_settings_record(db)
    workloads = (
        db.execute(
            select(FacultyWorkload, FacultyProfile)
            .join(FacultyProfile)
            .options(*workload_options())
        )
        .unique()
        .all()
    )
    unconfigured_terms = 0
    unpaid_overloads = 0
    for workload, faculty in workloads:
        item = read_workload(workload, faculty, settings)
        if item.projection_weeks == 0:
            unconfigured_terms += 1
        if (
            item.compensation_category == "Regular Faculty"
            and item.overload_weekly_hours > 0
            and (faculty.monthly_salary or 0) <= 0
        ):
            unpaid_overloads += 1
    items = [
        {
            "key": "salary-profiles",
            "title": "Faculty profiles missing salary details",
            "count": profiles_missing_salary,
            "detail": "Add a salary grade and step so the monthly and yearly salary totals can include these profiles.",
            "action_path": "/faculty-profiles",
        },
        {
            "key": "organization-details",
            "title": "Faculty profiles with unverified appointment details",
            "count": profiles_missing_org,
            "detail": "Verify employment status, college, and department so projection totals are reliable.",
            "action_path": "/faculty-profiles",
        },
        {
            "key": "faculty-status",
            "title": "Faculty status needs confirmation",
            "count": profiles_status_to_verify,
            "detail": "Confirm uncertain faculty status and record its effective date before relying on salary totals.",
            "action_path": "/faculty-profiles",
        },
        {
            "key": "term-weeks",
            "title": "Workloads without configured term weeks",
            "count": unconfigured_terms,
            "detail": "Set the applicable teaching weeks in Compensation Rules to include these records in term costs.",
            "action_path": "/compensation-rules",
        },
        {
            "key": "overload-rate",
            "title": "Regular overloads missing a monthly salary",
            "count": unpaid_overloads,
            "detail": "Complete the faculty monthly salary. Overload hourly rate is monthly salary × 12 × 0.000781.",
            "action_path": "/faculty-profiles",
        },
    ]
    return ProjectionReadinessRead(
        ready=not any(item["count"] for item in items),
        blocked_count=sum(item["count"] for item in items),
        items=items,
    )


@router.get("/monthly-projection", response_model=MonthlySalaryProjectionRead)
def monthly_salary_projection(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[LocalUser, Depends(require_admin)],
    college: str | None = Query(default=None, max_length=120),
    employment_status: str | None = Query(default=None, max_length=20),
    academic_year: str | None = Query(default=None, max_length=20),
    term: str | None = Query(default=None, max_length=40),
    period: Literal["semester", "summer", "yearly"] = "yearly",
    as_of: date | None = None,
) -> MonthlySalaryProjectionRead:
    status_as_of = as_of or date.today()
    selected_college = college.strip() if college else None
    selected_status = employment_status.strip() if employment_status else None
    selected_academic_year = academic_year.strip() if academic_year else None
    selected_term = term.strip() if term else None
    if period == "semester" and (
        not selected_academic_year
        or selected_term
        not in ("First Semester", "1st Semester", "Second Semester", "2nd Semester")
    ):
        raise HTTPException(
            status_code=422, detail="Choose an academic year and first or second semester."
        )
    if period == "summer" and (not selected_academic_year or selected_term != "Summer"):
        raise HTTPException(
            status_code=422,
            detail="Choose an academic year and Summer for a teaching-only estimate.",
        )
    if selected_term == "1st Semester":
        selected_term = "First Semester"
    elif selected_term == "2nd Semester":
        selected_term = "Second Semester"
    if period == "yearly":
        selected_term = None
    salary_months = 4.5 if period == "semester" else 0 if period == "summer" else 12
    statement = select(FacultyProfile)
    if selected_college:
        statement = statement.where(FacultyProfile.college == selected_college)
    if selected_status:
        statement = statement.where(FacultyProfile.employment_status == selected_status)

    profiles = list(
        db.scalars(statement.order_by(FacultyProfile.college, FacultyProfile.name)).all()
    )
    records = []
    provisional_records = []
    incomplete_count = 0
    provisional_status_count = 0
    provisional_monthly_salary_total = 0.0
    excluded_status_count = 0
    employment_status_totals: dict[str, dict[str, float | int | str]] = {}
    salary_grade_totals: dict[str, dict[str, float | int | str]] = {}
    college_totals = {
        code: {
            "college": code,
            "included_count": 0,
            "monthly_salary_total": 0.0,
            "term_teaching_cost": 0.0,
            "combined_estimate": 0.0,
        }
        for code in (COLLEGE_ORDER if not selected_college else (selected_college,))
    }

    for profile in profiles:
        monthly_salary = profile.monthly_salary or 0
        if (
            monthly_salary <= 0
            or profile.college == "Unassigned"
            or profile.department == "To verify"
            or profile.employment_status == "To verify"
            or not profile.college.strip()
            or not profile.department.strip()
            or not profile.employment_status.strip()
        ):
            incomplete_count += 1
            continue
        status_classification = planning_status(profile, status_as_of)
        if status_classification == "provisional":
            provisional_status_count += 1
            provisional_monthly_salary_total += monthly_salary
            provisional_records.append(
                {
                    "faculty_id": profile.id,
                    "faculty_name": profile.name,
                    "service_status": profile.service_status,
                    "status_effective_date": profile.service_status_effective_date,
                    "monthly_salary": monthly_salary,
                }
            )
            continue
        if status_classification == "excluded":
            excluded_status_count += 1
            continue

        record = {
            "faculty_id": profile.id,
            "faculty_name": profile.name,
            "rank": profile.rank,
            "employment_status": profile.employment_status,
            "college": profile.college,
            "department": profile.department,
            "salary_grade": profile.salary_grade,
            "salary_step": profile.salary_step,
            "monthly_salary": monthly_salary,
        }
        records.append(record)
        for target, label in (
            (employment_status_totals, profile.employment_status),
            (salary_grade_totals, profile.salary_grade or "Not specified"),
        ):
            subtotal = target.setdefault(
                label,
                {"label": label, "included_count": 0, "monthly_salary_total": 0.0},
            )
            subtotal["included_count"] = int(subtotal["included_count"]) + 1
            subtotal["monthly_salary_total"] = (
                float(subtotal["monthly_salary_total"]) + monthly_salary
            )
        subtotal = college_totals.setdefault(
            profile.college,
            {
                "college": profile.college,
                "included_count": 0,
                "monthly_salary_total": 0.0,
                "term_teaching_cost": 0.0,
                "combined_estimate": 0.0,
            },
        )
        subtotal["included_count"] += 1
        subtotal["monthly_salary_total"] += monthly_salary

    for profile in profiles:
        college_totals.setdefault(
            profile.college,
            {
                "college": profile.college,
                "included_count": 0,
                "monthly_salary_total": 0.0,
                "term_teaching_cost": 0.0,
                "combined_estimate": 0.0,
            },
        )
    ordered_totals = [college_totals[code] for code in COLLEGE_ORDER if code in college_totals]
    ordered_totals.extend(
        subtotal for code, subtotal in college_totals.items() if code not in COLLEGE_ORDER
    )
    for subtotal in ordered_totals:
        teaching_cost_for_college = teaching_cost_snapshot(
            db,
            selected_academic_year,
            selected_term,
            str(subtotal["college"]),
            selected_status,
            status_as_of=status_as_of,
            status_bucket="included",
        )
        subtotal["term_teaching_cost"] = float(teaching_cost_for_college["total_term_pay"])
        subtotal["combined_estimate"] = float(
            subtotal["monthly_salary_total"]
        ) * salary_months + float(subtotal["term_teaching_cost"])
    total_monthly_salary = sum(record["monthly_salary"] for record in records)
    details = []
    covered_faculty = set()
    teaching_cost = teaching_cost_snapshot(
        db,
        selected_academic_year,
        selected_term,
        selected_college,
        selected_status,
        details,
        covered_faculty,
        status_as_of=status_as_of,
        status_bucket="included",
    )
    provisional_teaching_details = []
    provisional_teaching_cost = teaching_cost_snapshot(
        db,
        selected_academic_year,
        selected_term,
        selected_college,
        selected_status,
        provisional_teaching_details,
        status_as_of=status_as_of,
        status_bucket="provisional",
    )
    semester_coverage = (
        overload_coverage_snapshot(
            db, selected_academic_year, selected_term, profiles, details, status_as_of
        )
        if period == "semester" and selected_academic_year and selected_term
        else None
    )
    overload_coverage = semester_coverage if not selected_college and not selected_status else None
    faculty_details = {}
    confirmed_not_teaching_ids = (
        {item.faculty_id for item in semester_coverage.confirmations}
        if semester_coverage
        else set()
    )
    for item in details:
        faculty_details.setdefault(item["faculty_id"], []).append(item)
    for record in records:
        workloads = faculty_details.get(record["faculty_id"], [])
        regular_workloads = [item for item in workloads if item["category"] == "Regular Faculty"]
        record["regular_weekly_hours"] = (
            sum(item["regular_weekly_hours"] for item in regular_workloads)
            if regular_workloads and period != "yearly"
            else None
        )
        record["overload_weekly_hours"] = (
            sum(item["overload_weekly_hours"] for item in regular_workloads)
            if regular_workloads and period != "yearly"
            else None
        )
        incomplete = any(
            item["term_pay"] is None or (item["paid_hours"] > 0 and item["hourly_rate"] <= 0)
            for item in workloads
        )
        missing = (
            record["faculty_id"] not in covered_faculty
            and record["faculty_id"] not in confirmed_not_teaching_ids
        )
        record["teaching_status"] = (
            "Incomplete"
            if incomplete
            else "Calculated"
            if workloads
            else "Confirmed not teaching this semester"
            if record["faculty_id"] in confirmed_not_teaching_ids
            else "No workload in selected period"
            if missing
            else "Allocated to another college"
        )
        record["period_overload_pay"] = (
            None
            if incomplete or missing
            else sum(
                item["term_pay"] for item in workloads if item["category"] == "Regular Faculty"
            )
        )
        record["period_part_time_pay"] = (
            None
            if incomplete or missing
            else sum(
                item["term_pay"] for item in workloads if item["category"] != "Regular Faculty"
            )
        )
    warnings = [item["allocation_warning"] for item in details if item["allocation_warning"]]
    if provisional_status_count:
        warnings.append(
            f"{provisional_status_count} faculty salary records need status confirmation; their potential salary cost is shown separately and excluded from confirmed salary totals."
        )
    if excluded_status_count:
        warnings.append(
            f"{excluded_status_count} faculty salary records are excluded based on their status effective date and the selected as-of date."
        )
    status_review_workloads = {item["workload_id"] for item in provisional_teaching_details}
    if status_review_workloads:
        warnings.append(
            f"{len(status_review_workloads)} saved workloads belong to faculty with provisional or inactive status. Their potential teaching cost is shown separately, not in confirmed totals; approved workload history is unchanged."
        )
    transition_terms = (
        (selected_term,) if selected_term else ("First Semester", "Second Semester", "Summer")
    )
    transition_count = (
        sum(
            any(
                term_status_transition(profile, selected_academic_year, candidate_term)
                for candidate_term in transition_terms
            )
            for profile in profiles
        )
        if selected_academic_year
        else 0
    )
    if transition_count:
        warnings.append(
            f"{transition_count} faculty status changes may affect the selected period. Salary is not automatically prorated; confirm the treatment with the office."
        )
    if incomplete_count:
        warnings.append(
            f"{incomplete_count} faculty profiles are excluded from salary totals because salary or profile information is incomplete."
        )
    missing_workloads = len(
        {profile.id for profile in profiles if planning_status(profile, status_as_of) == "included"}
        - covered_faculty
        - confirmed_not_teaching_ids
    )
    if missing_workloads and period != "summer":
        warnings.append(
            f"{missing_workloads} faculty profiles have no workload in this scope. Confirm whether they should teach; missing records do not mean zero teaching cost."
        )
    all_records_confirmed_not_teaching = bool(records) and all(
        record["faculty_id"] in confirmed_not_teaching_ids for record in records
    )
    if not details and not all_records_confirmed_not_teaching:
        warnings.append(
            "No confirmed teaching workloads in the selected scope. Teaching cost is not yet established."
        )
    if teaching_cost["unconfigured_term_count"]:
        warnings.append(
            f"{teaching_cost['unconfigured_term_count']} workloads lack teaching weeks and are excluded from teaching totals."
        )
    if provisional_teaching_cost["unconfigured_term_count"]:
        warnings.append(
            f"{provisional_teaching_cost['unconfigured_term_count']} provisional workloads lack teaching weeks, so their potential cost is incomplete."
        )
    source_differences = sum(
        item["imported_overload_hours"] is not None
        and abs(item["imported_overload_hours"] - item["calculated_overload_hours"]) > 0.01
        for item in details
    )
    if source_differences:
        warnings.append(
            f"{source_differences} workloads use imported overload hours that differ from the current teaching-hours rule. The file values are used for compensation."
        )
    missing_rates = sum(item["paid_hours"] > 0 and item["hourly_rate"] <= 0 for item in details)
    if missing_rates:
        warnings.append(
            f"{missing_rates} payable workloads have no hourly rate. Their teaching cost is incomplete."
        )
    if overload_coverage and overload_coverage.excluded_workloads:
        warnings.append(
            f"{overload_coverage.excluded_workloads} regular-faculty workloads are outside confirmed teaching totals because faculty status or appointment details need verification."
        )
    if period == "yearly":
        warnings.append(
            "Annual teaching totals include only saved workloads. Check first semester, second semester, and summer coverage; missing terms are not assumed to have zero cost."
        )
    if period == "summer":
        warnings.append(
            "Summer is teaching compensation only. No summer salary-month basis has been approved, so salary is not included in this estimate."
        )
    return MonthlySalaryProjectionRead(
        status_as_of=status_as_of,
        provisional_status_count=provisional_status_count,
        provisional_monthly_salary_total=provisional_monthly_salary_total,
        provisional_period_salary_total=provisional_monthly_salary_total * salary_months,
        excluded_status_count=excluded_status_count,
        provisional_records=provisional_records,
        provisional_teaching_cost=provisional_teaching_cost,
        provisional_teaching_details=provisional_teaching_details,
        warnings=warnings,
        teaching_details=details,
        overload_coverage=overload_coverage,
        filters={
            "college": selected_college,
            "employment_status": selected_status,
            "academic_year": selected_academic_year,
            "term": selected_term,
        },
        period=period,
        salary_months=salary_months,
        total_period_salary=total_monthly_salary * salary_months,
        combined_period_estimate=total_monthly_salary * salary_months
        + float(teaching_cost["total_term_pay"]),
        scope_note=SCOPE_NOTE,
        included_count=len(records),
        incomplete_count=incomplete_count,
        total_monthly_salary=total_monthly_salary,
        total_yearly_salary=total_monthly_salary * 12,
        combined_annual_estimate=total_monthly_salary * 12 + float(teaching_cost["total_term_pay"]),
        report_assumptions=[
            "Salary stays under the faculty home college. Teaching cost follows confirmed teaching-college allocations; otherwise it stays under the home college. College filters use these respective bases.",
            "Summer salary is not included because no salary-month basis has been approved."
            if period == "summer"
            else f"Selected salary estimate uses current monthly salaries × {salary_months} months; not historical payroll.",
            "Semester salary uses 4.5 months; yearly salary uses 12 months, not two semester estimates.",
            "Teaching compensation follows the selected academic year and semester (all terms for yearly), using configured weeks: normally 18 per semester and 6 for summer.",
            "Allowances, deductions, payroll disbursements, and unconfigured workload terms are excluded.",
            "Faculty status is assessed as of the selected date. Historical salaries and appointment dates are not reconstructed; approved workload snapshots remain unchanged.",
            "Teaching costs attached to uncertain or inactive faculty are shown separately from confirmed planning totals.",
        ],
        college_totals=ordered_totals,
        employment_status_totals=list(employment_status_totals.values()),
        salary_grade_totals=sorted(
            salary_grade_totals.values(), key=lambda item: str(item["label"])
        ),
        teaching_cost=teaching_cost,
        records=records,
    )


class SaveProjectionInput(BaseModel):
    academic_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    term: Literal["First Semester", "Second Semester", "Summer"] | None = None
    period: Literal["semester", "summer", "yearly"]
    college: str | None = Field(default=None, max_length=120)
    employment_status: str | None = Field(default=None, max_length=20)
    as_of: date | None = None

    @model_validator(mode="after")
    def validate_scope(self):
        start, end = map(int, self.academic_year.split("-"))
        if end != start + 1:
            raise ValueError("Academic year must contain consecutive years.")
        if self.period == "semester" and self.term not in ("First Semester", "Second Semester"):
            raise ValueError("Choose a semester for a semester snapshot.")
        if self.period == "summer" and self.term != "Summer":
            raise ValueError("Choose Summer for a summer snapshot.")
        if self.period == "yearly" and self.term is not None:
            raise ValueError("Yearly snapshots cannot select a term.")
        return self


@router.post("/saved-projections", response_model=SavedProjectionRead, status_code=201)
def save_projection(
    payload: SaveProjectionInput,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[LocalUser, Depends(require_admin)],
) -> SavedProjectionRead:
    projection = monthly_salary_projection(
        db,
        user,
        payload.college,
        payload.employment_status,
        payload.academic_year,
        payload.term,
        payload.period,
        payload.as_of or date.today(),
    )
    record = SavedProjection(
        academic_year=payload.academic_year,
        term=projection.filters.term,
        period=payload.period,
        created_by=user.username,
        projection_json=projection.model_dump_json(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return SavedProjectionRead(
        id=record.id,
        academic_year=record.academic_year,
        term=record.term,
        period=record.period,
        created_by=record.created_by,
        created_at=record.created_at,
        projection=projection,
    )


@router.get("/saved-projections", response_model=list[SavedProjectionSummary])
def list_saved_projections(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[LocalUser, Depends(require_admin)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[SavedProjectionSummary]:
    records = db.execute(
        select(SavedProjection, SemesterCloseoutEstimate.id)
        .outerjoin(
            SemesterCloseoutEstimate,
            SemesterCloseoutEstimate.projection_id == SavedProjection.id,
        )
        .order_by(SavedProjection.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    summaries = []
    for record, closeout_id in records:
        projection = json.loads(record.projection_json)
        summaries.append(
            SavedProjectionSummary(
                id=record.id,
                academic_year=record.academic_year,
                term=record.term,
                period=record.period,
                created_by=record.created_by,
                created_at=record.created_at,
                included_count=projection["included_count"],
                combined_period_estimate=projection["combined_period_estimate"],
                closeout=closeout_id is not None,
            )
        )
    return summaries


@router.get("/saved-projections/{projection_id}", response_model=SavedProjectionRead)
def read_saved_projection(
    projection_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[LocalUser, Depends(require_admin)],
) -> SavedProjectionRead:
    record = db.get(SavedProjection, projection_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Saved estimate not found.")
    return SavedProjectionRead(
        id=record.id,
        academic_year=record.academic_year,
        term=record.term,
        period=record.period,
        created_by=record.created_by,
        created_at=record.created_at,
        projection=MonthlySalaryProjectionRead.model_validate_json(record.projection_json),
        closeout=db.scalar(
            select(SemesterCloseoutEstimate.id).where(
                SemesterCloseoutEstimate.projection_id == record.id,
            )
        )
        is not None,
    )


@router.get("/monthly-projection.csv")
def export_monthly_salary_projection(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[LocalUser, Depends(require_admin)],
    college: str | None = Query(default=None, max_length=120),
    employment_status: str | None = Query(default=None, max_length=20),
    academic_year: str | None = Query(default=None, max_length=20),
    term: str | None = Query(default=None, max_length=40),
    period: Literal["semester", "summer", "yearly"] = "yearly",
    as_of: date | None = None,
) -> Response:
    projection = monthly_salary_projection(
        db, user, college, employment_status, academic_year, term, period, as_of
    )
    rows: list[list[object]] = [
        ["Cathedra Expenses Projection"],
        ["Reporting period", projection.period],
        ["Salary months", projection.salary_months],
        ["Faculty status as of", projection.status_as_of],
        ["Provisional faculty salary records", projection.provisional_status_count],
        ["Provisional monthly salary cost", projection.provisional_monthly_salary_total],
        ["Provisional period salary cost", projection.provisional_period_salary_total],
        ["Provisional teaching workloads", projection.provisional_teaching_cost.workloads],
        ["Provisional period teaching cost", projection.provisional_teaching_cost.total_term_pay],
        ["College filter", projection.filters.college or "All colleges"],
        [
            "Employment status filter",
            projection.filters.employment_status or "All employment statuses",
        ],
        ["Academic year filter", projection.filters.academic_year or "All academic years"],
        ["Term filter", projection.filters.term or "All terms"],
        [],
        [
            "Summary",
            "Included faculty",
            "Monthly salary cost",
            "Period salary cost",
            "Period teaching cost",
            "Combined annual estimate"
            if period == "yearly"
            else "Summer teaching estimate"
            if period == "summer"
            else "Combined semester estimate",
        ],
        [
            "Current projection",
            projection.included_count,
            projection.total_monthly_salary,
            projection.total_period_salary,
            projection.teaching_cost.total_term_pay,
            projection.combined_period_estimate,
        ],
        [],
        [
            "College",
            "Included faculty",
            "Monthly salary cost",
            "Term teaching cost",
            "Combined estimate",
        ],
    ]
    rows.extend(
        [
            [
                item.college,
                item.included_count,
                item.monthly_salary_total,
                item.term_teaching_cost,
                item.combined_estimate,
            ]
            for item in projection.college_totals
        ]
    )
    rows.extend([[], ["Employment status", "Included faculty", "Monthly salary cost"]])
    rows.extend(
        [
            [item.label, item.included_count, item.monthly_salary_total]
            for item in projection.employment_status_totals
        ]
    )
    rows.extend(
        [
            [],
            [
                "Faculty member",
                "Rank",
                "Status",
                "College",
                "Department",
                "Salary grade",
                "Step",
                "Monthly salary",
                "Period overload compensation",
                "Period part-time compensation",
                "Teaching status",
            ],
        ]
    )
    rows.extend(
        [
            [
                item.faculty_name,
                item.rank,
                item.employment_status,
                item.college,
                item.department,
                item.salary_grade or "",
                item.salary_step,
                item.monthly_salary,
                item.period_overload_pay,
                item.period_part_time_pay,
                item.teaching_status,
            ]
            for item in projection.records
        ]
    )
    rows.extend([[], ["Faculty status review", "Status", "Effective date", "Monthly salary"]])
    rows.extend(
        [
            [
                item.faculty_name,
                item.service_status,
                item.status_effective_date or "",
                item.monthly_salary,
            ]
            for item in projection.provisional_records
        ]
    )
    rows.extend([[], ["Scope warnings"]])
    rows.extend([[item] for item in projection.warnings])
    rows.extend(
        [
            [],
            [
                "Teaching calculation",
                "Term",
                "Category",
                "Home college",
                "Teaching college",
                "Allocation basis",
                "Hourly rate",
                "Paid hours/week",
                "Weeks",
                "Period pay",
            ],
        ]
    )
    rows.extend(
        [
            [
                item["faculty_name"],
                item["term"],
                item["category"],
                item["home_college"],
                allocation["college"],
                item["allocation_basis"],
                item["hourly_rate"],
                allocation["paid_hours"],
                item["weeks"],
                allocation["term_pay"],
            ]
            for item in projection.teaching_details
            for allocation in item["allocations"]
        ]
    )
    rows.extend(
        [
            [],
            [
                "Provisional teaching calculation",
                "Term",
                "Category",
                "Home college",
                "Teaching college",
                "Allocation basis",
                "Hourly rate",
                "Paid hours/week",
                "Weeks",
                "Period pay",
            ],
        ]
    )
    rows.extend(
        [
            [
                item["faculty_name"],
                item["term"],
                item["category"],
                item["home_college"],
                allocation["college"],
                item["allocation_basis"],
                item["hourly_rate"],
                allocation["paid_hours"],
                item["weeks"],
                allocation["term_pay"],
            ]
            for item in projection.provisional_teaching_details
            for allocation in item["allocations"]
        ]
    )
    rows.extend([[], ["Assumptions"]])
    rows.extend([[item] for item in projection.report_assumptions])
    return csv_download("cathedra-expenses-projection.csv", rows)
