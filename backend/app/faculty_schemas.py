from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.salary_scale import allowed_steps, grade_for_rank, normalize_grade, salary_for

CollegeCode = Literal["CAS", "COEd", "CBMA", "COE", "COF", "CIT", "CCS", "CCJ", "Unassigned", ""]
EmploymentStatus = Literal["Full-time", "Part-time", "To verify", ""]
ServiceStatus = Literal["Active", "Inactive", "Retired", "Resigned", "To verify"]


class FacultyProfileBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    rank: str = Field(min_length=1, max_length=120)
    employment_status: EmploymentStatus
    salary_grade: str | None = Field(default=None, max_length=30)
    salary_step: int = Field(default=1, ge=1, le=8)
    monthly_salary: float | None = Field(default=None, ge=0)
    campus: str | None = Field(default=None, max_length=80)
    college: CollegeCode
    department: str = Field(max_length=160)
    service_status: ServiceStatus = "Active"
    service_status_effective_date: date | None = None
    item_number: str | None = Field(default=None, max_length=100)
    bachelors_degree: str | None = Field(default=None, max_length=300)
    masters_degree: str | None = Field(default=None, max_length=300)
    doctoral_degree: str | None = Field(default=None, max_length=300)
    eligibility: str | None = Field(default=None, max_length=300)
    remarks: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def apply_official_salary_scale(self) -> "FacultyProfileBase":
        official_grade = grade_for_rank(self.rank)
        selected_grade = official_grade or normalize_grade(self.salary_grade)
        if selected_grade is None:
            self.salary_grade = None
            self.monthly_salary = None
            return self
        if self.salary_step not in allowed_steps(selected_grade):
            raise ValueError(f"{selected_grade} does not have salary step {self.salary_step}.")
        self.salary_grade = selected_grade
        self.monthly_salary = salary_for(selected_grade, self.salary_step)
        return self


class FacultyProfileCreate(FacultyProfileBase):
    pass


class FacultyProfileUpdate(FacultyProfileBase):
    pass


class FacultyProfileRead(FacultyProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    revision: int
    data_source: str
    salary_source: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def apply_official_salary_scale(self) -> "FacultyProfileRead":
        return self
