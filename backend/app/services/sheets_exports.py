"""Explicit business-data export; authentication and raw snapshots never leave the app."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.qualification_rates import read_draft
from app.api.workload import approved_workload_summary_data
from app.models import (
    FacultyNoTeachingConfirmation,
    FacultyProfile,
    FacultyWorkload,
    ProjectionSettings,
    SavedProjection,
    SemesterCloseoutEstimate,
    SemesterOverloadBudget,
    WorkloadCostSettings,
)
from app.services.google_sheets import SheetTable
from app.services.projection import build_monthly_projection
from app.services.snapshots import load_projection
from app.version import release_version
from app.workload_read import read_workload, workload_options


def cell(value: object) -> object:
    if isinstance(value, datetime):
        # SQLite stores the application's timestamps as naive UTC.
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def table(title: str, fields: tuple[str, ...], items: list) -> SheetTable:
    return SheetTable(
        title=f"Cathedra {title}",
        headers=[field.replace("_", " ").title() for field in fields],
        rows=[
            [
                cell(item.get(field) if isinstance(item, dict) else getattr(item, field, None))
                for field in fields
            ]
            for item in items
        ],
    )


def build_google_sheet_tables(db: Session) -> list[SheetTable]:
    """Read a caller-owned SQLite snapshot without creating default settings or editing records."""
    generated_at = datetime.now(UTC).isoformat()
    profiles = list(db.scalars(select(FacultyProfile).order_by(FacultyProfile.id)))
    faculty_by_id = {faculty.id: faculty for faculty in profiles}
    workloads = list(
        db.scalars(
            select(FacultyWorkload).options(*workload_options()).order_by(FacultyWorkload.id)
        )
    )
    settings = db.get(WorkloadCostSettings, 1)
    period = db.get(ProjectionSettings, 1)
    warnings = []
    faculty_fields = (
        "id",
        "name",
        "rank",
        "employment_status",
        "salary_grade",
        "salary_step",
        "monthly_salary",
        "campus",
        "college",
        "department",
        "service_status",
        "service_status_effective_date",
        "item_number",
        "bachelors_degree",
        "masters_degree",
        "doctoral_degree",
        "eligibility",
        "remarks",
        "data_source",
        "created_at",
        "updated_at",
    )
    workload_fields = (
        "id",
        "faculty_profile_id",
        "faculty_name",
        "college",
        "department",
        "rank",
        "academic_year",
        "term",
        "remarks",
        "compensation_category",
        "highest_qualification",
        "professional_qualification",
        "professional_qualification_other",
        "workflow_status",
        "reviewed_at",
        "approved_at",
        "total_lecture_hours",
        "total_laboratory_hours",
        "total_weekly_hours",
        "preparation_count",
        "regular_weekly_hours",
        "overload_weekly_hours",
        "imported_overload_hours",
        "calculated_overload_hours",
        "overload_difference",
        "compensation_hourly_rate",
        "estimated_teaching_pay_weekly",
        "projection_weeks",
        "estimated_teaching_pay_term",
        "data_source",
        "created_at",
    )
    workload_rows = []
    assignment_rows = []
    if settings is None:
        warnings.append(
            "Compensation rules are not configured. Calculated workload costs and projection tabs are blank."
        )
    for workload in workloads:
        faculty = faculty_by_id[workload.faculty_profile_id]
        if settings is not None:
            # Explicit field selection below omits internal import provenance and approval JSON.
            workload_rows.append(read_workload(workload, faculty, settings).model_dump())
        else:
            workload_rows.append(
                {
                    **{field: getattr(workload, field, None) for field in workload_fields},
                    "faculty_name": faculty.name,
                    "college": faculty.college,
                    "department": faculty.department,
                    "rank": faculty.rank,
                }
            )
        for assignment in sorted(workload.assignments, key=lambda item: item.id):
            assignment_rows.append(
                {
                    "id": assignment.id,
                    "workload_id": workload.id,
                    "faculty_id": faculty.id,
                    "faculty_name": faculty.name,
                    "academic_year": workload.academic_year,
                    "term": workload.term,
                    "course_code": assignment.course_code,
                    "course_title": assignment.course_title,
                    "year_section": assignment.year_section,
                    "lecture_hours": assignment.lecture_hours,
                    "laboratory_hours": assignment.laboratory_hours,
                    "weekly_hours": assignment.lecture_hours + assignment.laboratory_hours,
                }
            )
    approved = approved_workload_summary_data(db)
    draft = read_draft(db)
    cost_fields = (
        "internal_monthly_equivalent_hours",
        "external_base_hourly_rate",
        "external_masters_increment",
        "external_doctorate_increment",
        "external_doctor_increment",
        "external_lawyer_increment",
        "first_semester_weeks",
        "second_semester_weeks",
        "summer_weeks",
        "updated_at",
    )
    salary_rows = []
    teaching_rows = []
    overview = [
        ["Snapshot generated at (UTC)", generated_at],
        ["Application version", release_version()],
        ["Academic year", period.academic_year if period else "Not selected"],
        ["Office term", period.term if period else "Not selected"],
        ["Source", "Latest saved business data on this computer; one-way export"],
        [
            "Privacy",
            "Accounts, sessions, keys, activity logs and internal snapshot JSON are excluded",
        ],
        [
            "Financial scope",
            "Planning estimates, not payroll disbursements. Approved values remain frozen.",
        ],
        ["Qualification draft", "Draft — not applied to live compensation"],
    ]
    if period is None:
        warnings.append(
            "No office period is selected. Set it in Office Period to populate projection tabs."
        )
    elif settings is not None:
        projection = build_monthly_projection(
            db,
            academic_year=period.academic_year,
            term=period.term,
            period="summer" if period.term == "Summer" else "semester",
        )
        salary_rows = [
            {
                **row.model_dump(),
                "academic_year": period.academic_year,
                "term": period.term,
                "salary_months": projection.salary_months,
                "period_salary": row.monthly_salary * projection.salary_months,
                "inclusion": "Included",
            }
            for row in projection.records
        ]
        salary_rows.extend(
            {
                **row.model_dump(),
                "academic_year": period.academic_year,
                "term": period.term,
                "salary_months": projection.salary_months,
                "period_salary": row.monthly_salary * projection.salary_months,
                "inclusion": "Provisional — verify service status",
            }
            for row in projection.provisional_records
        )
        teaching_rows = [
            {
                **row,
                "academic_year": period.academic_year,
                "inclusion": inclusion,
                "weekly_pay": sum(part["weekly_pay"] for part in row["allocations"]),
            }
            for inclusion, rows in (
                ("Included", projection.teaching_details),
                ("Provisional — verify service status", projection.provisional_teaching_details),
            )
            for row in rows
        ]
        overview.extend(
            [
                ["Monthly salary total (included)", projection.total_monthly_salary],
                ["Period salary total (included)", projection.total_period_salary],
                ["Combined period estimate (included)", projection.combined_period_estimate],
                ["Provisional faculty count", projection.provisional_status_count],
            ]
        )
        warnings.extend(projection.warnings)
        warnings.extend(projection.report_assumptions)
    closeout_ids = set(db.scalars(select(SemesterCloseoutEstimate.projection_id)))
    estimates = []
    for saved in db.scalars(select(SavedProjection).order_by(SavedProjection.id)):
        frozen = load_projection(saved.projection_json, record_id=saved.id)
        estimates.append(
            {
                "id": saved.id,
                "academic_year": saved.academic_year,
                "term": saved.term,
                "period": saved.period,
                "created_at": saved.created_at,
                "included_count": frozen.included_count,
                "combined_period_estimate": frozen.combined_period_estimate,
                "closeout": saved.id in closeout_ids,
            }
        )
    no_teaching = [
        {
            "faculty_id": confirmation.faculty_id,
            "faculty_name": faculty_by_id[confirmation.faculty_id].name,
            "academic_year": confirmation.academic_year,
            "term": confirmation.term,
            "confirmed_at": confirmation.confirmed_at,
        }
        for confirmation in db.scalars(
            select(FacultyNoTeachingConfirmation).order_by(FacultyNoTeachingConfirmation.id)
        )
    ]
    budgets = [
        {
            "academic_year": item.academic_year,
            "term": item.term,
            "amount": item.amount_centavos / 100,
        }
        for item in db.scalars(select(SemesterOverloadBudget).order_by(SemesterOverloadBudget.id))
    ]
    tables = [
        table("Faculty", faculty_fields, profiles),
        table("Workloads", workload_fields, workload_rows),
        table(
            "Assignments",
            (
                "id",
                "workload_id",
                "faculty_id",
                "faculty_name",
                "academic_year",
                "term",
                "course_code",
                "course_title",
                "year_section",
                "lecture_hours",
                "laboratory_hours",
                "weekly_hours",
            ),
            assignment_rows,
        ),
        table(
            "Approved Workloads",
            (
                "workload_id",
                "faculty_name",
                "college",
                "department",
                "rank",
                "academic_year",
                "term",
                "weekly_hours",
                "overload_hours",
                "weekly_pay",
                "term_pay",
                "allocation_basis",
                "allocation_warning",
                "approved_at",
            ),
            approved["items"],
        ),
        table("Cost Settings", cost_fields, [settings] if settings else []),
        table(
            "Qualification Draft",
            (
                "category",
                "qualification",
                "hourly_addition",
                "effective_from",
                "effective_to",
                "reference",
                "combination_rule",
                "status",
            ),
            [
                {
                    **rate.model_dump(),
                    "combination_rule": draft.combination_rule,
                    "status": "Draft — not applied",
                }
                for rate in draft.rates
            ],
        ),
        table(
            "Salary Projection",
            (
                "faculty_id",
                "faculty_name",
                "rank",
                "employment_status",
                "college",
                "department",
                "salary_grade",
                "salary_step",
                "monthly_salary",
                "academic_year",
                "term",
                "salary_months",
                "period_salary",
                "teaching_status",
                "inclusion",
            ),
            salary_rows,
        ),
        table(
            "Teaching Projection",
            (
                "workload_id",
                "faculty_id",
                "faculty_name",
                "academic_year",
                "term",
                "home_college",
                "category",
                "hourly_rate",
                "paid_hours",
                "weeks",
                "weekly_pay",
                "term_pay",
                "allocation_basis",
                "allocation_warning",
                "inclusion",
            ),
            teaching_rows,
        ),
        table(
            "Saved Estimates",
            (
                "id",
                "academic_year",
                "term",
                "period",
                "created_at",
                "included_count",
                "combined_period_estimate",
                "closeout",
            ),
            estimates,
        ),
        table("Overload Budgets", ("academic_year", "term", "amount"), budgets),
        table(
            "No Teaching",
            ("faculty_id", "faculty_name", "academic_year", "term", "confirmed_at"),
            no_teaching,
        ),
    ]
    overview.extend([["Warnings / assumptions", warning] for warning in dict.fromkeys(warnings)])
    overview.extend([[f"Rows: {item.title}", len(item.rows)] for item in tables])
    return [
        SheetTable(title="Cathedra Overview", headers=["Item", "Value"], rows=overview),
        *tables,
    ]
