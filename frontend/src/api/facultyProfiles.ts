import { request } from "./client";
import type { FacultyProfile, FacultyProfilePayload, FacultyWorkload, PagedResult, SalaryScale } from "../types";

export const getFacultyProfiles = (search = "", page = 1, serviceStatus = "") => request<PagedResult<FacultyProfile>>(`/faculty-profiles/page?${new URLSearchParams({search, page: String(page), page_size: "50", ...(serviceStatus ? {service_status: serviceStatus} : {})})}`); export const createFacultyProfile = (payload: FacultyProfilePayload) => request<FacultyProfile>("/faculty-profiles", {method:"POST",body:JSON.stringify(payload)}); export const updateFacultyProfile = (id:number,payload:FacultyProfilePayload,revision:number) => request<FacultyProfile>(`/faculty-profiles/${id}`,{method:"PUT",headers:{"If-Match":String(revision)},body:JSON.stringify(payload)}); export const deleteFacultyProfile = (id:number, revision:number) => request<void>(`/faculty-profiles/${id}`,{method:"DELETE",headers:{"If-Match":String(revision)}});
export const getFacultyProfileOptions = () => request<FacultyProfile[]>("/faculty-profiles");
export const getFacultyProfile = (id:number) => request<FacultyProfile>(`/faculty-profiles/${id}`);
export const getFacultyProfileWorkloads = (id:number) => request<FacultyWorkload[]>(`/faculty-profiles/${id}/workloads`);
export const getSalaryScale = () => request<SalaryScale>("/faculty-profiles/salary-scale");
