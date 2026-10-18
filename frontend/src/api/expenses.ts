import { downloadFile, request } from "./client";
import type { MonthlySalaryProjection, ProjectionReadiness, SavedProjection, SavedProjectionSummary } from "../types";

export const getMonthlySalaryProjection = (college = "", employmentStatus = "", academicYear = "", term = "", period: "semester" | "summer" | "yearly" = "yearly", asOf = "") => request<MonthlySalaryProjection>(`/expenses/monthly-projection?${new URLSearchParams({college, employment_status: employmentStatus, academic_year: academicYear, term, period, ...(asOf ? {as_of: asOf} : {})})}`);
export const getProjectionReadiness = () => request<ProjectionReadiness>("/expenses/projection-readiness");
export const saveProjection = (scope:{academic_year:string;term:string|null;period:"semester"|"summer"|"yearly";college:string|null;employment_status:string|null;as_of:string}) => request<SavedProjection>("/expenses/saved-projections", {method:"POST", body:JSON.stringify(scope)});
export const getSavedProjections = (offset = 0, limit = 50) => request<SavedProjectionSummary[]>(`/expenses/saved-projections?${new URLSearchParams({offset:String(offset),limit:String(limit)})}`);
export const getSavedProjection = (id:number) => request<SavedProjection>(`/expenses/saved-projections/${id}`);
export type CloseoutTerm = "First Semester" | "Second Semester" | "Summer";
export const getCloseoutEstimate = (academicYear:string, term:CloseoutTerm) => request<SavedProjection|null>(`/expenses/closeout-estimates?${new URLSearchParams({academic_year:academicYear,term})}`);
export const saveCloseoutEstimate = (value:{academic_year:string;term:CloseoutTerm;as_of:string}) => request<SavedProjection>("/expenses/closeout-estimates", {method:"POST",body:JSON.stringify(value)});
export function downloadMonthlySalaryProjection(college = "", employmentStatus = "", academicYear = "", term = "", period: "semester" | "summer" | "yearly" = "yearly", asOf = "") {
  const query = new URLSearchParams({ college, employment_status: employmentStatus, academic_year: academicYear, term, period, ...(asOf ? { as_of: asOf } : {}) });
  return downloadFile(`/expenses/monthly-projection.csv?${query}`, "cathedra-expenses-projection.csv");
}

export type ActiveProjectionPeriod = { academic_year:string; term:"First Semester"|"Second Semester"; revision?:number };
export type SemesterOverloadBudget = ActiveProjectionPeriod & { id:number; amount:number };
export const getActiveProjectionPeriod = () => request<ActiveProjectionPeriod | null>("/expenses/active-period");
export const saveActiveProjectionPeriod = (value: ActiveProjectionPeriod) => request<ActiveProjectionPeriod>("/expenses/active-period", {method:"PUT", headers:{"If-Match":String(value.revision ?? 0)}, body:JSON.stringify(value)});
export const getSemesterOverloadBudgets = () => request<SemesterOverloadBudget[]>("/expenses/overload-budgets");
export const saveSemesterOverloadBudget = (value: ActiveProjectionPeriod & {amount:string}) => request<SemesterOverloadBudget>("/expenses/overload-budgets", {method:"PUT", headers:{"If-Match":String(value.revision ?? 0)}, body:JSON.stringify(value)});
export const deleteSemesterOverloadBudget = (id:number, revision:number) => request<void>(`/expenses/overload-budgets/${id}`, {method:"DELETE",headers:{"If-Match":String(revision)}});
export const confirmNoTeaching = (facultyId:number, period:ActiveProjectionPeriod) => request<void>(`/expenses/no-teaching-confirmations/${facultyId}`, {method:"PUT",body:JSON.stringify(period)});
export const removeNoTeachingConfirmation = (facultyId:number, period:ActiveProjectionPeriod) => request<void>(`/expenses/no-teaching-confirmations/${facultyId}?${new URLSearchParams({academic_year:period.academic_year,term:period.term})}`, {method:"DELETE"});
