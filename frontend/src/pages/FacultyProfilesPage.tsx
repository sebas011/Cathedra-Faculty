import { useDirectoryValue, useDirectoryScroll } from "../hooks/useDirectoryMemory";
import FormError from "../components/FormError";
import { SkeletonTableRows } from "../components/PageSkeleton";
import FacultyProgramField from "../components/FacultyProgramField";
import UnsavedChangesDialog from "../components/UnsavedChangesDialog";
import { useDiscardConfirmation } from "../hooks/useDiscardConfirmation";
import { useUnsavedChanges } from "../hooks/useUnsavedChanges";
import { FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { createFacultyProfile, deleteFacultyProfile, getCurrentUser, getFacultyProfiles, getSalaryScale } from "../api";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import type { FacultyProfile, FacultyProfilePayload, SalaryScale } from "../types";

const departments = ["CAS", "COEd", "CBMA", "COE", "COF", "CIT", "CCS", "CCJ"] as const;

const blankProfile = (): FacultyProfilePayload => ({ name: "", rank: "", employment_status: "Full-time", salary_grade: "", salary_step: 1, monthly_salary: null, campus: null, college: "CAS", department: "", service_status: "Active", service_status_effective_date: null, item_number: null, bachelors_degree: null, masters_degree: null, doctoral_degree: null, eligibility: null, remarks: null });
export default function FacultyProfilesPage() {
  const isAdmin = getCurrentUser()?.role === "admin";
  const { confirmDiscard: requestDiscard, discardDialog } = useDiscardConfirmation();
  const [profiles, setProfiles] = useState<FacultyProfile[]>([]);
  const [salaryScale, setSalaryScale] = useState<SalaryScale | null>(null);
  const [search, setSearch] = useDirectoryValue<string>("faculty:search", "");
  const [serviceStatus, setServiceStatus] = useDirectoryValue<string>("faculty:service-status", "");
  const [form, setForm] = useState<FacultyProfilePayload>(blankProfile);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const savePending = useRef(false);
  const [page, setPage] = useDirectoryValue<number>("faculty:page", 1); const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<Record<string, number> | null>(null);
  const debouncedSearch = useDebouncedValue(search);

  const { blocker, dirty, resetBaseline } = useUnsavedChanges(isEditorOpen ? form : null);
  const confirmDiscard = async () => !dirty || await requestDiscard("Discard your unsaved faculty changes? Saved faculty records will stay unchanged.");

  const requestId = useRef(0);
  const [loading, setLoading] = useState(true);
  useDirectoryScroll("faculty", !loading && !error);

  const load = async () => {
    const currentRequest = ++requestId.current;
    setLoading(true);
    try {
      setError("");
      const result = await getFacultyProfiles(debouncedSearch, page, serviceStatus); if (currentRequest !== requestId.current) return;
      setProfiles(result.items); setTotal(result.total);
      const lastPage = Math.max(1, Math.ceil(result.total / 50)); if (page > lastPage || page < 1) setPage(lastPage);
      setSummary(result.summary ?? null);
    } catch (caught) {
      if (currentRequest !== requestId.current) return;
      setError(caught instanceof Error ? caught.message : "Unable to load faculty profiles.");
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  };

  useEffect(() => { void load(); return () => { requestId.current += 1; }; }, [debouncedSearch, page, serviceStatus]);
  useEffect(() => { void getSalaryScale().then(setSalaryScale).catch((caught) => setError(caught instanceof Error ? caught.message : "Unable to load the salary scale.")); }, []);

  const closeEditor = () => {
    resetBaseline(null);
    setIsEditorOpen(false);
    setForm(blankProfile());
  };

  const saveProfile = async (event: FormEvent) => {
    event.preventDefault();
    if (savePending.current) return;
    const missing = [["Name", form.name], ["Rank", form.rank], ["Program", form.department]].filter(([, value]) => !value.trim());
    if (missing.length) { setError(missing.map(([label]) => `${label}: enter a value.`).join("; ")); return; }
    savePending.current = true;
    setSaving(true);
    try {
      setError("");
      await createFacultyProfile(form);
      closeEditor();
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save profile.");
    } finally {
      savePending.current = false;
      setSaving(false);
    }
  };

  const removeProfile = async (profile: FacultyProfile) => {
    if (!confirm(`Delete ${profile.name}?`)) return;
    try {
      setError("");
      await deleteFacultyProfile(profile.id, profile.revision);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to delete profile.");
    }
  };

  const grade = salaryScale?.grades.find((item) => item.salary_grade === form.salary_grade);
  const rankGrade = salaryScale?.rank_mappings.find((item) => item.rank.toLocaleLowerCase() === form.rank.trim().toLocaleLowerCase())?.salary_grade;
  const selectedSalary = grade?.steps.find((item) => item.step === form.salary_step)?.monthly_salary ?? null;
  const updateRank = (rank: string) => setForm((current) => ({ ...current, rank, salary_grade: salaryScale?.rank_mappings.find((item) => item.rank.toLocaleLowerCase() === rank.trim().toLocaleLowerCase())?.salary_grade || current.salary_grade }));

  return (
    <div className="stack-md faculty-directory-page"><UnsavedChangesDialog blocker={blocker} />{discardDialog}
      <section className="hero-card compact">
        <div>
          <span className="eyebrow">FACULTY DIRECTORY</span>
          <h1>Faculty Profiles</h1>
          <p>Keep faculty ranks, departments, and programs in one directory.</p>
        </div>
        {isAdmin && <button className="btn primary" type="button" disabled={saving} onClick={async () => { if (!(await confirmDiscard())) return; resetBaseline(blankProfile()); setForm(blankProfile()); setIsEditorOpen(true); }}>Add Faculty</button>}
      </section>

      {isEditorOpen ? <FormError message={error} /> : error && <div className="notice error" role="alert">{error}</div>}

      {isEditorOpen && (
        <form onSubmit={saveProfile} className="form-card faculty-editor">
          <div className="form-card-head"><span>NEW</span><div><h2>New faculty profile</h2><p>Enter the faculty member’s current appointment details.</p></div></div>
          <div className="form-grid three">
            <label className="span-2">Name *<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
            <label>Rank / position *<input required list="academic-ranks" value={form.rank} onChange={(event) => updateRank(event.target.value)} /><datalist id="academic-ranks">{salaryScale?.rank_mappings.map((item) => <option key={item.rank} value={item.rank} />)}</datalist></label>
            <label>Employment status<select value={form.employment_status} onChange={(event) => setForm({ ...form, employment_status: event.target.value as FacultyProfilePayload["employment_status"] })}><option>Full-time</option><option>Part-time</option></select></label>
            <label>Faculty status<select value={form.service_status} onChange={(event) => setForm({ ...form, service_status: event.target.value as FacultyProfilePayload["service_status"], service_status_effective_date: null })}><option>Active</option><option>Inactive</option><option>Retired</option><option>Resigned</option><option>To verify</option></select></label>
            {["Inactive", "Retired", "Resigned"].includes(form.service_status) && <label>Status effective date<input type="date" required value={form.service_status_effective_date || ""} onChange={event => setForm({ ...form, service_status_effective_date: event.target.value || null })} /></label>}
            <label>Salary grade<select value={form.salary_grade || ""} disabled={Boolean(rankGrade)} onChange={(event) => setForm({ ...form, salary_grade: event.target.value, salary_step: 1 })}><option value="">Select salary grade</option>{salaryScale?.grades.map((item) => <option key={item.salary_grade} value={item.salary_grade}>{item.salary_grade}</option>)}</select>{rankGrade && <small>Set from the selected academic rank.</small>}</label>
            <label>Salary step<select value={form.salary_step} disabled={!grade} onChange={(event) => setForm({ ...form, salary_step: Number(event.target.value) })}>{grade ? grade.steps.map((item) => <option key={item.step} value={item.step}>Step {item.step}</option>) : <option>Choose a salary grade first</option>}</select></label>
            <label>Official monthly salary<input readOnly value={selectedSalary != null ? `₱${selectedSalary.toLocaleString("en-PH", { minimumFractionDigits: 2 })}` : "Select a salary grade and step"} /></label>
            <label>Campus<input maxLength={80} list="faculty-campuses" value={form.campus || ""} onChange={(event) => setForm({ ...form, campus: event.target.value || null })} /><datalist id="faculty-campuses">{["Talisay", "Alijis", "Fortune Towne", "Binalbagan"].map((campus) => <option key={campus} value={campus} />)}</datalist></label>
            <label>Department<select value={form.college} onChange={(event) => setForm({ ...form, college: event.target.value as FacultyProfilePayload["college"] })}>{departments.map((department) => <option key={department}>{department}</option>)}</select></label>
            <FacultyProgramField className="span-3" department={form.college} value={form.department} onChange={program => setForm({ ...form, department: program })} required />
            <label>Item number<input maxLength={100} value={form.item_number || ""} onChange={event => setForm({ ...form, item_number: event.target.value || null })} /></label>
            <label>Bachelor’s degree<input maxLength={300} value={form.bachelors_degree || ""} onChange={event => setForm({ ...form, bachelors_degree: event.target.value || null })} /></label>
            <label>Master’s degree<input maxLength={300} value={form.masters_degree || ""} onChange={event => setForm({ ...form, masters_degree: event.target.value || null })} /></label>
            <label>Doctoral degree<input maxLength={300} value={form.doctoral_degree || ""} onChange={event => setForm({ ...form, doctoral_degree: event.target.value || null })} /></label>
            <label>Eligibility<input maxLength={300} value={form.eligibility || ""} onChange={event => setForm({ ...form, eligibility: event.target.value || null })} /></label>
            <label className="span-3">Remarks<textarea maxLength={2000} value={form.remarks || ""} onChange={event => setForm({ ...form, remarks: event.target.value || null })} /></label>
          </div>
          <div className="form-actions"><button type="button" className="btn secondary" disabled={saving} onClick={async () => { if (await confirmDiscard()) closeEditor(); }}>Cancel</button><button className="btn primary" disabled={saving}>{saving ? "Saving…" : "Save Faculty"}</button></div>
        </form>
      )}

      <section className="data-card directory-table-card">
        <div className="toolbar directory-toolbar"><div className="search-wrap"><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Search name, rank, department, or program" aria-label="Search faculty profiles" /></div><label>Faculty status<select value={serviceStatus} onChange={event => { setServiceStatus(event.target.value); setPage(1); }}><option value="">All</option><option>Active</option><option>Inactive</option><option>Retired</option><option>Resigned</option><option>To verify</option></select></label>{search && <button className="btn secondary" type="button" onClick={() => { setSearch(""); setPage(1); }}>Clear search</button>}</div>
        <div className="table-meta">{total} profiles · Page {page} of {Math.max(1, Math.ceil(total / 50))}</div>
        <div className="table-scroll" role="region" aria-label="Faculty profile directory" tabIndex={0}><table><thead><tr><th scope="col">Faculty member</th><th scope="col">Appointment</th><th scope="col">Department & program</th><th scope="col" className="right">Actions</th></tr></thead><tbody>
          {loading ? <SkeletonTableRows columns={4} /> : profiles.length === 0 ? <tr><td colSpan={4} className="empty-table"><strong>No faculty profiles found.</strong><span>{search ? "Try a broader search term." : "Add a faculty member to begin the directory."}</span></td></tr> : profiles.map((profile) => <tr key={profile.id}>
            <td><div className="person-cell"><Link className="faculty-profile-link" to={`/faculty-profiles/${profile.id}`}><strong>{profile.name}</strong></Link><span>{profile.service_status} · {profile.employment_status}</span></div></td>
            <td><div className="person-cell"><strong>{profile.rank}</strong><span>{profile.salary_grade ? `${profile.salary_grade} · Step ${profile.salary_step}` : "No salary grade"}{profile.monthly_salary != null ? ` · ₱${profile.monthly_salary.toLocaleString("en-PH", { minimumFractionDigits: 2 })}` : ""}</span></div></td>
            <td><div className="person-cell"><strong>{profile.college || "—"}</strong><span>{profile.department || "—"}{profile.campus ? ` · ${profile.campus}` : ""}</span></div></td>
            <td className="right"><div className="action-group"><Link className="btn secondary" to={`/faculty-profiles/${profile.id}`}>View</Link>{isAdmin && <button className="btn secondary danger" type="button" onClick={() => void removeProfile(profile)}>Delete</button>}</div></td>
          </tr>)}
        </tbody></table></div><div className="form-actions no-print"><button className="btn secondary" disabled={page===1} onClick={()=>setPage(page-1)}>Previous</button><button className="btn secondary" disabled={page>=Math.max(1,Math.ceil(total/50))} onClick={()=>setPage(page+1)}>Next</button></div>
      </section>
      <details className="data-card directory-summary-details"><summary>Faculty overview</summary><div className="directory-summary three" aria-label="Faculty profile summary">
        <div><span>Faculty profiles</span><strong>{total}</strong></div>
        <div><span>Full-time</span><strong>{summary?.full_time ?? "—"}</strong></div>
        <div><span>Departments represented</span><strong>{summary?.colleges ?? "—"}</strong></div>
      </div></details>
    </div>
  );
}
