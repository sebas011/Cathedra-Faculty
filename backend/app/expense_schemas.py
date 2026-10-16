from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class SalaryGradeRuleInput(BaseModel):
    salary_grade: str = Field(min_length=1, max_length=30)
    monthly_salary: float = Field(ge=0, le=10_000_000)
    standard_weekly_hours: float = Field(gt=0, le=80)
    overload_hourly_rate: float = Field(ge=0, le=100_000)


class SalaryGradeRuleRead(SalaryGradeRuleInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    updated_at: datetime


class ProjectionFilters(BaseModel):
    college: str | None
    employment_status: str | None
    academic_year: str | None
    term: str | None


class MonthlySalaryRecord(BaseModel):
    faculty_id: int
    faculty_name: str
    rank: str
    employment_status: str
    college: str
    department: str
    salary_grade: str | None
    salary_step: int
    monthly_salary: float
    regular_weekly_hours: float | None = None
    overload_weekly_hours: float | None = None
    period_overload_pay: float | None = None
    period_part_time_pay: float | None = None
    teaching_status: str = "No workload"


class CollegeMonthlySalaryTotal(BaseModel):
    college: str
    included_count: int
    monthly_salary_total: float
    term_teaching_cost: float
    combined_estimate: float


class SalaryProjectionTotal(BaseModel):
    label: str
    included_count: int
    monthly_salary_total: float


class TeachingCostSnapshot(BaseModel):
    workloads: int
    total_weekly_pay: float
    total_term_pay: float
    unconfigured_term_count: int


class ProvisionalFacultyRecord(BaseModel):
    faculty_id: int
    faculty_name: str
    service_status: str
    status_effective_date: date | None
    monthly_salary: float


class OverloadCoverageIssue(BaseModel):
    faculty_id: int
    faculty_name: str
    workload_id: int | None
    reason: str
    action_path: str


class OverloadCoverage(BaseModel):
    provisional: bool
    regular_workloads: int
    included_workloads: int
    missing_workloads: int
    confirmed_not_teaching: int
    excluded_workloads: int
    missing_rates: int
    missing_weeks: int
    issues: list[OverloadCoverageIssue]
    confirmations: list["NoTeachingConfirmationRead"]


class NoTeachingConfirmationRead(BaseModel):
    faculty_id: int
    faculty_name: str
    academic_year: str
    term: str
    confirmed_by: str
    confirmed_at: datetime


class ProjectionReadinessItem(BaseModel):
    key: str
    title: str
    count: int
    detail: str
    action_path: str


class ProjectionReadinessRead(BaseModel):
    ready: bool
    blocked_count: int
    items: list[ProjectionReadinessItem]


class MonthlySalaryProjectionRead(BaseModel):
    status_as_of: date
    provisional_status_count: int = 0
    provisional_monthly_salary_total: float = 0
    provisional_period_salary_total: float = 0
    excluded_status_count: int = 0
    provisional_records: list[ProvisionalFacultyRecord] = []
    provisional_teaching_cost: TeachingCostSnapshot
    provisional_teaching_details: list[dict] = []
    warnings: list[str] = []
    teaching_details: list[dict] = []
    overload_coverage: OverloadCoverage | None = None
    filters: ProjectionFilters
    period: str
    salary_months: float
    total_period_salary: float
    combined_period_estimate: float
    scope_note: str
    included_count: int
    incomplete_count: int
    total_monthly_salary: float
    total_yearly_salary: float
    combined_annual_estimate: float
    report_assumptions: list[str]
    college_totals: list[CollegeMonthlySalaryTotal]
    employment_status_totals: list[SalaryProjectionTotal]
    salary_grade_totals: list[SalaryProjectionTotal]
    teaching_cost: TeachingCostSnapshot
    records: list[MonthlySalaryRecord]


class SavedProjectionRead(BaseModel):
    id: int
    academic_year: str
    term: str | None
    period: str
    created_by: str
    created_at: datetime
    projection: MonthlySalaryProjectionRead
    closeout: bool = False


class SavedProjectionSummary(BaseModel):
    id: int
    academic_year: str
    term: str | None
    period: str
    created_by: str
    created_at: datetime
    included_count: int
    combined_period_estimate: float
    closeout: bool = False
