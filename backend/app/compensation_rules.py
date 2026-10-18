"""Current office compensation policy, shared without changing its arithmetic.

These constants require an approved policy change before adjustment. Saved
approvals and estimates retain the values captured when they were created.
"""

SEMESTER_SALARY_MONTHS = 4.5
YEARLY_SALARY_MONTHS = 12
OVERLOAD_MONTHLY_FACTOR = 0.000781


def regular_hours_for_preparations(preparation_count: int) -> int:
    return 21 if preparation_count <= 2 else 18


def salary_based_overload_rate(monthly_salary: float) -> float:
    return monthly_salary * 12 * OVERLOAD_MONTHLY_FACTOR
