"""Explicit business-data export; authentication and raw snapshots never leave the app."""

import json
import math
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, load_only

from app.api.qualification_rates import read_draft
from app.api.workload import approved_workload_summary_data
from app.compensation_rules import regular_hours_for_preparations
from app.faculty_status import normalized_term, planning_status, term_status_transition
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
from app.teaching_allocations import teaching_allocations
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


def _build_legacy_google_sheet_tables(db: Session) -> list[SheetTable]:
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


PROFILE_FIELDS = (
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
WORKLOAD_FIELDS = (
    "id",
    "faculty_profile_id",
    "faculty_name",
    "college",
    "department",
    "rank",
    "academic_year",
    "term",
    "remarks",
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
    "created_at",
)
ASSIGNMENT_FIELDS = (
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
)
APPROVED_WORKLOAD_FIELDS = (
    "workload_id",
    "faculty_name",
    "college",
    "department",
    "rank",
    "academic_year",
    "term",
    "weekly_hours",
    "overload_hours",
    "approved_at",
)
OVERLOAD_FIELDS = (
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
)
OVERLOAD_COST_FIELDS = (
    "first_semester_weeks",
    "second_semester_weeks",
    "summer_weeks",
    "updated_at",
)


def _category_overview(
    dataset: str,
    scope: str,
    tables: list[SheetTable],
    *,
    details: list[list[object]] | None = None,
    warnings: list[str] | None = None,
) -> list[SheetTable]:
    overview = [
        ["Snapshot generated at (UTC)", datetime.now(UTC).isoformat()],
        ["Application version", release_version()],
        ["Dataset", dataset],
        ["Scope", scope],
        ["Source", "Latest saved business data on this computer; one-way export"],
        [
            "Privacy",
            "Accounts, sessions, keys, activity logs, provenance and raw snapshot JSON are excluded",
        ],
        *(details or []),
        *[["Warnings / assumptions", warning] for warning in dict.fromkeys(warnings or [])],
        *[[f"Rows: {item.title}", len(item.rows)] for item in tables],
    ]
    return [
        SheetTable(title="Cathedra Overview", headers=["Item", "Value"], rows=overview),
        *tables,
    ]


def _profile_tables(db: Session) -> list[SheetTable]:
    # Select only the profile allowlist; neither financial snapshots nor workloads are read.
    profiles = list(
        db.scalars(
            select(FacultyProfile)
            .options(load_only(*(getattr(FacultyProfile, field) for field in PROFILE_FIELDS)))
            .order_by(FacultyProfile.id)
        )
    )
    return _category_overview(
        "Faculty profiles",
        "All saved faculty profiles, including their profile monthly salary; no workload or projection data",
        [table("Faculty", PROFILE_FIELDS, profiles)],
    )


def _approved_hours(db: Session) -> list[dict[str, object]]:
    """Read the frozen workload history without interpreting stored compensation values."""
    approved = db.scalars(
        select(FacultyWorkload)
        .options(
            load_only(
                FacultyWorkload.id,
                FacultyWorkload.approval_snapshot,
                FacultyWorkload.approved_at,
            )
        )
        .where(
            FacultyWorkload.workflow_status == "Approved",
            FacultyWorkload.approval_snapshot.is_not(None),
        )
        .order_by(FacultyWorkload.approved_at.desc(), FacultyWorkload.id.desc())
    )
    rows = []
    for workload in approved:
        try:
            snapshot = json.loads(workload.approval_snapshot)
            if (
                not isinstance(snapshot, dict)
                or not isinstance(snapshot.get("faculty"), dict)
                or not isinstance(snapshot.get("workload"), dict)
            ):
                raise ValueError("Approval must contain frozen faculty and workload objects")
            if "schema_version" in snapshot and (
                type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1
            ):
                raise ValueError("Unsupported approval version")
            faculty, frozen = snapshot["faculty"], snapshot["workload"]
            for field in ("total_weekly_hours", "overload_weekly_hours"):
                value = frozen[field]
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError("Invalid frozen workload hours")
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as caught:
            raise HTTPException(
                status_code=409,
                detail=f"Workload #{workload.id} approval snapshot is unreadable. Preserve the frozen record and restore a verified backup before relying on it.",
            ) from caught
        rows.append(
            {
                "workload_id": workload.id,
                "faculty_name": str(faculty.get("name") or "Unnamed faculty"),
                "college": faculty.get("college"),
                "department": faculty.get("department"),
                "rank": faculty.get("rank"),
                "academic_year": frozen.get("academic_year"),
                "term": frozen.get("term"),
                "weekly_hours": frozen["total_weekly_hours"],
                "overload_hours": frozen["overload_weekly_hours"],
                "approved_at": snapshot.get("approved_at") or workload.approved_at,
            }
        )
    return rows


def _workload_tables(db: Session) -> list[SheetTable]:
    # Teaching-hours policy is independent of pay rates, qualifications and office settings.
    workload_columns = (
        "id",
        "faculty_profile_id",
        "academic_year",
        "term",
        "remarks",
        "workflow_status",
        "reviewed_at",
        "approved_at",
        "imported_overload_hours",
        "created_at",
    )
    workloads = (
        db.execute(
            select(FacultyWorkload, FacultyProfile)
            .join(FacultyProfile)
            .options(
                *workload_options(),
                load_only(*(getattr(FacultyWorkload, field) for field in workload_columns)),
                load_only(
                    FacultyProfile.id,
                    FacultyProfile.name,
                    FacultyProfile.college,
                    FacultyProfile.department,
                    FacultyProfile.rank,
                ),
            )
            .order_by(FacultyWorkload.id)
        )
        .unique()
        .all()
    )
    workload_rows, assignment_rows = [], []
    for workload, faculty in workloads:
        lecture_hours = sum(item.lecture_hours for item in workload.assignments)
        laboratory_hours = sum(item.laboratory_hours for item in workload.assignments)
        preparations = len({item.course_code.strip().casefold() for item in workload.assignments})
        regular_hours = regular_hours_for_preparations(preparations)
        calculated_overload = max(lecture_hours + laboratory_hours - regular_hours, 0)
        overload = (
            calculated_overload
            if workload.imported_overload_hours is None
            else workload.imported_overload_hours
        )
        workload_rows.append(
            {
                **{field: getattr(workload, field) for field in workload_columns},
                "faculty_name": faculty.name,
                "college": faculty.college,
                "department": faculty.department,
                "rank": faculty.rank,
                "total_lecture_hours": lecture_hours,
                "total_laboratory_hours": laboratory_hours,
                "total_weekly_hours": lecture_hours + laboratory_hours,
                "preparation_count": preparations,
                "regular_weekly_hours": regular_hours,
                "overload_weekly_hours": overload,
                "calculated_overload_hours": calculated_overload,
                "overload_difference": workload.imported_overload_hours is not None
                and abs(overload - calculated_overload) > 0.01,
            }
        )
        for assignment in sorted(workload.assignments, key=lambda item: item.id):
            assignment_rows.append(
                {
                    **{
                        field: getattr(assignment, field)
                        for field in (
                            "id",
                            "course_code",
                            "course_title",
                            "year_section",
                            "lecture_hours",
                            "laboratory_hours",
                        )
                    },
                    "workload_id": workload.id,
                    "faculty_id": faculty.id,
                    "faculty_name": faculty.name,
                    "academic_year": workload.academic_year,
                    "term": workload.term,
                    "weekly_hours": assignment.lecture_hours + assignment.laboratory_hours,
                }
            )
    return _category_overview(
        "Faculty workload",
        "All saved teaching workloads and assignments; approved history uses frozen hours and faculty identity. Compensation and salary are excluded.",
        [
            table("Workloads", WORKLOAD_FIELDS, workload_rows),
            table("Assignments", ASSIGNMENT_FIELDS, assignment_rows),
            table("Approved Workloads", APPROVED_WORKLOAD_FIELDS, _approved_hours(db)),
        ],
    )


def _overload_tables(db: Session) -> list[SheetTable]:
    settings = db.get(WorkloadCostSettings, 1)
    period = db.get(ProjectionSettings, 1)
    as_of = date.today()
    rows, warnings = [], []
    details = [
        ["Academic year", period.academic_year if period else "Not selected"],
        ["Office term", period.term if period else "Not selected"],
        ["Status assessed as of", as_of.isoformat()],
        [
            "Basis",
            "Current regular-faculty overload planning estimates; approved workload history remains frozen",
        ],
        [
            "Excluded",
            "Base salary, internal and external part-time teaching, saved combined estimates and qualification drafts",
        ],
    ]
    if settings is None:
        warnings.append("Compensation rules are not configured. The overload projection is blank.")
    if period is None:
        warnings.append(
            "No office period is selected. Set it in Office Period to populate the overload projection."
        )
    if settings is not None and period is not None:
        canonical_term = normalized_term(period.term)
        aliases = {
            "First Semester": ("First Semester", "1st Semester"),
            "Second Semester": ("Second Semester", "2nd Semester"),
        }
        statement = (
            select(FacultyWorkload, FacultyProfile)
            .join(FacultyProfile)
            .options(*workload_options())
            .where(
                FacultyWorkload.academic_year == period.academic_year,
                FacultyWorkload.term.in_(aliases.get(canonical_term, (canonical_term,))),
                or_(
                    FacultyWorkload.compensation_category.in_(("Regular Faculty", "")),
                    FacultyWorkload.compensation_category.is_(None),
                ),
            )
            .order_by(FacultyWorkload.id)
        )
        incomplete_count = 0
        for workload, faculty in db.execute(statement).unique().all():
            # Match the app's teaching-cost eligibility and provisional classification.
            if (
                faculty.college in ("", "Unassigned")
                or faculty.department in ("", "To verify")
                or faculty.employment_status in ("", "To verify")
            ):
                incomplete_count += 1
                continue
            item = read_workload(workload, faculty, settings)
            allocations, basis, warning = teaching_allocations(workload, faculty, item)
            included = planning_status(faculty, as_of) == "included"
            rows.append(
                {
                    "workload_id": workload.id,
                    "faculty_id": faculty.id,
                    "faculty_name": faculty.name,
                    "academic_year": period.academic_year,
                    "term": workload.term,
                    "home_college": faculty.college,
                    "category": item.compensation_category,
                    "hourly_rate": item.compensation_hourly_rate,
                    "paid_hours": sum(part["paid_hours"] for part in allocations),
                    "weeks": item.projection_weeks,
                    "weekly_pay": sum(part["weekly_pay"] for part in allocations),
                    "term_pay": None
                    if item.estimated_teaching_pay_term is None
                    else sum(part["term_pay"] for part in allocations),
                    "allocation_basis": basis,
                    "allocation_warning": warning,
                    "inclusion": "Included" if included else "Provisional — verify service status",
                }
            )
            if warning:
                warnings.append(warning)
            if not included:
                warnings.append(
                    "Workloads with provisional or inactive faculty status are shown separately from confirmed overload estimates."
                )
            if item.estimated_teaching_pay_term is None:
                warnings.append(
                    "Some workloads lack configured teaching weeks; their period overload estimate is blank."
                )
            if item.overload_weekly_hours > 0 and item.compensation_hourly_rate <= 0:
                warnings.append(
                    "Some payable overload workloads have no hourly rate. Their overload estimate is incomplete."
                )
            if item.overload_difference:
                warnings.append(
                    "Imported overload hours differ from the current teaching-hours rule. The imported values are used for compensation."
                )
            if term_status_transition(faculty, period.academic_year, period.term):
                warnings.append(
                    "A faculty status change may affect this period. Confirm the overload treatment with the office."
                )
        if incomplete_count:
            warnings.append(
                f"{incomplete_count} regular-faculty workloads are excluded because appointment details need verification."
            )
        if not any(row["inclusion"] == "Included" for row in rows):
            warnings.append(
                "No confirmed regular-faculty overload workloads in the selected scope. Missing workloads do not establish zero overload cost."
            )
    budgets = [
        {
            "academic_year": item.academic_year,
            "term": item.term,
            "amount": item.amount_centavos / 100,
        }
        for item in db.scalars(select(SemesterOverloadBudget).order_by(SemesterOverloadBudget.id))
    ]
    return _category_overview(
        "Overload projection",
        "Regular Faculty overload in the selected office period only; internal and external part-time teaching are excluded, matching the dashboard overload figure",
        [
            table("Overload Projection", OVERLOAD_FIELDS, rows),
            table("Overload Budgets", ("academic_year", "term", "amount"), budgets),
            table("Cost Settings", OVERLOAD_COST_FIELDS, [settings] if settings else []),
        ],
        details=details,
        warnings=warnings,
    )


def build_google_sheet_tables(db: Session, *, destination: str | None = None) -> list[SheetTable]:
    """Export one dataset from a caller-owned snapshot without creating settings or records."""
    if destination is None:
        # Keep the original single-sheet API compatible for existing installations.
        return _build_legacy_google_sheet_tables(db)
    builders = {
        "profiles": _profile_tables,
        "workloads": _workload_tables,
        "overload": _overload_tables,
    }
    if not isinstance(destination, str) or destination not in builders:
        raise ValueError("Choose a Google Sheets destination: workloads, overload, or profiles.")
    return builders[destination](db)
