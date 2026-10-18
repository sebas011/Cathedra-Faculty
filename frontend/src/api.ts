import { downloadFile, request } from "./api/client";
export { clearSession, getCurrentUser, getSessionToken, releaseVersion, saveSession } from "./api/client";
export * from "./api/workloads";
export * from "./api/facultyProfiles";
export * from "./api/expenses";
import type { QualificationDraft, QualificationDraftInput } from "./types";
import type { ActivityEvent, BackupResult, LocalUser, MaintenanceStatus, ServiceHealth, SessionResult, VerificationQueue } from "./types";
export const getServiceHealth = () => request<ServiceHealth>("/health");
export const exitDesktop = () => request<{status:"closing"}>("/desktop/exit", {method:"POST"});
export const getQualificationDraft = () => request<QualificationDraft>("/qualification-rates/draft");
export const saveQualificationDraft = (payload: QualificationDraftInput) => request<QualificationDraft>("/qualification-rates/draft", { method: "PUT", body: JSON.stringify(payload) });
export const getAccountStatus = () => request<{setup_required:boolean}>("/auth/status"); export const setupAdmin = (username:string, password:string, setupKey:string) => request<SessionResult>("/auth/setup", {method:"POST",headers:{"X-Cathedra-Setup-Key":setupKey},body:JSON.stringify({username,password})}); export const signIn = (username:string, password:string) => request<SessionResult>("/auth/login", {method:"POST",body:JSON.stringify({username,password})}); export const signOut = () => request<void>("/auth/logout", {method:"POST"}); export const getUsers = () => request<LocalUser[]>("/auth/users"); export const createUser = (username:string,password:string,role:"admin"|"staff") => request<LocalUser>("/auth/users", {method:"POST",body:JSON.stringify({username,password,role})}); export const changePassword = (current_password:string,new_password:string) => request<void>("/auth/change-password",{method:"POST",body:JSON.stringify({current_password,new_password})}); export const resetUserPassword = (id:number,new_password:string) => request<void>(`/auth/users/${id}/reset-password`,{method:"POST",body:JSON.stringify({new_password})});
export const setUserActive = (id:number,active:boolean) => request<LocalUser>(`/auth/users/${id}/status`,{method:"PUT",body:JSON.stringify({active})});
export const revokeUserSessions = (id:number) => request<void>(`/auth/users/${id}/revoke-sessions`,{method:"POST"});
export const getMaintenanceStatus = () => request<MaintenanceStatus>("/maintenance/status"); export const createDatabaseBackup = () => request<BackupResult>("/maintenance/backups", { method: "POST" }); export const restoreDatabase = (filename:string) => request<{restored_from:string;safety_backup:string}>("/maintenance/restore", {method:"POST",body:JSON.stringify({filename})});
export const deleteDatabaseBackup = (filename:string) => request<void>(`/maintenance/backups/${encodeURIComponent(filename)}`, {method:"DELETE"});
export const setBackupProtection = (filename:string, protect:boolean) => request<void>(`/maintenance/backups/${encodeURIComponent(filename)}/protection`, {method:protect?"POST":"DELETE"});
export const downloadDatabaseBackup = (filename: string) =>
  downloadFile(`/maintenance/backups/${encodeURIComponent(filename)}/download`, filename);

export const getVerificationQueue = (area = "All", search = "", page = 1) => request<VerificationQueue>(`/verification?${new URLSearchParams({ area, search, page: String(page), page_size: "50" })}`);
export const getActivity = () => request<ActivityEvent[]>("/activity");
export const checkDatabaseIntegrity = () => request<{status:string;checked_at:string}>("/maintenance/integrity-check", {method:"POST"});
export const getActivityPage = (filters: {search:string;date_from:string;date_to:string}, page=1) => {
  const query = new URLSearchParams({page:String(page),page_size:"50"});
  Object.entries(filters).forEach(([key,value]) => { if(value) query.set(key,value); });
  return request<{items:ActivityEvent[];total:number;page:number;page_size:number}>(`/activity/page?${query}`);
};
export function downloadActivity(filters: { search: string; date_from: string; date_to: string }) {
  const query = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value); });
  return downloadFile(`/activity/export.csv?${query}`, "cathedra-activity.csv");
}
export const downloadExport = (kind: "faculty-profiles" | "workloads", filename: string) =>
  downloadFile(`/maintenance/exports/${kind}.csv`, filename);
