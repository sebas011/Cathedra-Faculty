"""Build planning estimates without depending on API route defaults."""

from datetime import date
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compensation_rules import SEMESTER_SALARY_MONTHS, YEARLY_SALARY_MONTHS
from app.expense_schemas import (
    MonthlySalaryProjectionRead,
    NoTeachingConfirmationRead,
    OverloadCoverage,
)
from app.faculty_status import planning_status, term_status_transition
from app.models import FacultyNoTeachingConfirmation, FacultyProfile, FacultyWorkload
from app.teaching_allocations import COLLEGE_ORDER, teaching_allocations
from app.workload_read import get_workload_cost_settings_record, read_workload, workload_options

SCOPE_NOTE = (
    "Planning estimate using current saved salaries and teaching compensation for the selected scope. "
    "Excludes allowances, deductions, and actual payroll disbursement."
)


def empty_teaching_cost() -> dict[str, float | int]:
    return {
        "workloads": 0,
        "total_weekly_pay": 0.0,
        "total_term_pay": 0.0,
        "unconfigured_term_count": 0,
    }


class TeachingCostRollup:
    """Aggregate each workload once, including its confirmed college allocations."""

    def __init__(self) -> None:
        self.totals: dict[tuple[str, str | None], dict[str, float | int]] = {}
        self.details: dict[tuple[str, str | None], list[dict]] = {}
        self.covered_faculty: dict[str, set[int]] = {"included": set(), "provisional": set()}

    def snapshot(self, bucket: str, college: str | None = None) -> dict[str, float | int]:
        return self.totals.get((bucket, college), empty_teaching_cost())

    def scoped_details(self, bucket: str, college: str | None = None) -> list[dict]:
        return self.details.get((bucket, college), [])


def teaching_cost_rollup(
    db: Session,
    *,
    academic_year: str | None,
    term: str | None,
    employment_status: str | None,
    status_as_of: date,
) -> TeachingCostRollup:
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
    rollup = TeachingCostRollup()
    for workload, faculty in db.execute(statement).unique().all():
        if (
            faculty.college in ("", "Unassigned")
            or faculty.department in ("", "To verify")
            or faculty.employment_status in ("", "To verify")
        ):
            continue
        bucket = (
            "included" if planning_status(faculty, status_as_of) == "included" else "provisional"
        )
        # Coverage means a saved workload exists, even when all its pay is allocated
        # to another college. Preserve this distinction from a missing workload.
        rollup.covered_faculty[bucket].add(faculty.id)
        item = read_workload(workload, faculty, settings)
        allocations, basis, warning = teaching_allocations(workload, faculty, item)
        scopes = [None, *dict.fromkeys(entry["college"] for entry in allocations)]
        for college in scopes:
            scoped_allocations = [
                entry for entry in allocations if college is None or entry["college"] == college
            ]
            if not scoped_allocations:
                continue
            term_pay = (
                None
                if item.estimated_teaching_pay_term is None
                else sum(entry["term_pay"] for entry in scoped_allocations)
            )
            details = {
                "home_college": faculty.college,
                "allocations": scoped_allocations,
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
                "paid_hours": sum(entry["paid_hours"] for entry in scoped_allocations),
                "weeks": item.projection_weeks,
                "term_pay": term_pay,
                "imported_overload_hours": item.imported_overload_hours,
                "calculated_overload_hours": item.calculated_overload_hours,
                "regular_weekly_hours": item.regular_weekly_hours,
                "overload_weekly_hours": item.overload_weekly_hours,
            }
            key = (bucket, college)
            rollup.details.setdefault(key, []).append(details)
            total = rollup.totals.setdefault(key, empty_teaching_cost())
            total["workloads"] += 1
            total["total_weekly_pay"] += sum(entry["weekly_pay"] for entry in scoped_allocations)
            if term_pay is None:
                total["unconfigured_term_count"] += 1
            else:
                total["total_term_pay"] += term_pay
    return rollup


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


def build_monthly_projection(
    db: Session,
    *,
    college: str | None = None,
    employment_status: str | None = None,
    academic_year: str | None = None,
    term: str | None = None,
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
    salary_months = (
        SEMESTER_SALARY_MONTHS
        if period == "semester"
        else 0
        if period == "summer"
        else YEARLY_SALARY_MONTHS
    )
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
    teaching_rollup = teaching_cost_rollup(
        db,
        academic_year=selected_academic_year,
        term=selected_term,
        employment_status=selected_status,
        status_as_of=status_as_of,
    )
    for subtotal in ordered_totals:
        teaching_cost_for_college = teaching_rollup.snapshot("included", str(subtotal["college"]))
        subtotal["term_teaching_cost"] = float(teaching_cost_for_college["total_term_pay"])
        subtotal["combined_estimate"] = float(
            subtotal["monthly_salary_total"]
        ) * salary_months + float(subtotal["term_teaching_cost"])
    total_monthly_salary = sum(record["monthly_salary"] for record in records)
    details = teaching_rollup.scoped_details("included", selected_college)
    covered_faculty = teaching_rollup.covered_faculty["included"]
    teaching_cost = teaching_rollup.snapshot("included", selected_college)
    provisional_teaching_details = teaching_rollup.scoped_details("provisional", selected_college)
    provisional_teaching_cost = teaching_rollup.snapshot("provisional", selected_college)
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
