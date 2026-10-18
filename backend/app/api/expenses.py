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
    ProjectionReadinessRead,
    SavedProjectionRead,
    SavedProjectionSummary,
)
from app.faculty_status import planning_status
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
from app.services.projection import build_monthly_projection
from app.services.snapshots import dump_projection, load_projection
from app.teaching_allocations import teaching_allocations as teaching_allocations
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


def csv_download(filename: str, rows: list[list[object]]) -> Response:
    output = StringIO(newline="")
    writer = SafeCsvWriter(output)
    writer.writerows(rows)
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
    return build_monthly_projection(
        db,
        college=college,
        employment_status=employment_status,
        academic_year=academic_year,
        term=term,
        period=period,
        as_of=as_of,
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
    projection = build_monthly_projection(
        db,
        college=payload.college,
        employment_status=payload.employment_status,
        academic_year=payload.academic_year,
        term=payload.term,
        period=payload.period,
        as_of=payload.as_of,
    )
    record = SavedProjection(
        academic_year=payload.academic_year,
        term=projection.filters.term,
        period=payload.period,
        created_by=user.username,
        projection_json=dump_projection(projection),
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
        projection = load_projection(record.projection_json, record_id=record.id)
        summaries.append(
            SavedProjectionSummary(
                id=record.id,
                academic_year=record.academic_year,
                term=record.term,
                period=record.period,
                created_by=record.created_by,
                created_at=record.created_at,
                included_count=projection.included_count,
                combined_period_estimate=projection.combined_period_estimate,
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
        projection=load_projection(record.projection_json, record_id=record.id),
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
    projection = build_monthly_projection(
        db,
        college=college,
        employment_status=employment_status,
        academic_year=academic_year,
        term=term,
        period=period,
        as_of=as_of,
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
