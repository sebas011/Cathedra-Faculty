import type { ApprovedWorkloadSummary, FacultyProfile, LocalUser, SavedProjectionSummary, WorkloadCostSettings } from "../src/types";

export const administrator: LocalUser = { id: 1, username: "test-admin", role: "admin", is_active: true, must_change_password: false };
export const faculty: FacultyProfile = {
  id: 1, revision: 1, name: "Demonstration Faculty", rank: "Instructor I",
  employment_status: "Full-time", salary_grade: "SG 12", salary_step: 1,
  monthly_salary: 33847, campus: "Talisay", college: "CAS", department: "BSAM",
  service_status: "Active", service_status_effective_date: null,
  item_number: null, bachelors_degree: null, masters_degree: null,
  doctoral_degree: null, eligibility: null, remarks: null,
  created_at: "2026-10-01T00:00:00", updated_at: "2026-10-01T00:00:00",
};
export const rules: WorkloadCostSettings = {
  revision: 1, overload_hourly_rate: 0, internal_monthly_equivalent_hours: 160,
  external_base_hourly_rate: 273.77, external_masters_increment: 0,
  external_doctorate_increment: 0, external_doctor_increment: 0,
  external_lawyer_increment: 0, first_semester_weeks: 18,
  second_semester_weeks: 18, summer_weeks: 6, updated_at: "2026-10-01T00:00:00",
};
export const approvedSummary: ApprovedWorkloadSummary = {
  workloads: 0, weekly_hours: 0, overload_hours: 0, weekly_pay: 0, term_pay: 0,
  college_totals: [], allocation_warnings: [], items: [],
};
export const savedEstimates = (count: number): SavedProjectionSummary[] => Array.from({ length: count }, (_, index) => ({
  id: index + 1, academic_year: "2026-2027", term: "First Semester", period: "semester",
  created_by: "test-admin", created_at: "2026-10-01T00:00:00", included_count: 1,
  combined_period_estimate: 1000, closeout: index === 0,
}));
