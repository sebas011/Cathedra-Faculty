import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import UnsavedChangesDialog from "../components/UnsavedChangesDialog";
import PageSkeleton from "../components/PageSkeleton";
import FacultyProgramField from "../components/FacultyProgramField";
import TableRegion from "../components/TableRegion";
import { useUnsavedChanges } from "../hooks/useUnsavedChanges";
import { useDiscardConfirmation } from "../hooks/useDiscardConfirmation";
import { getCurrentUser, getFacultyProfile, getFacultyProfileWorkloads, getSalaryScale, updateFacultyProfile } from "../api";
import type { FacultyProfile, FacultyProfilePayload, FacultyWorkload, SalaryScale } from "../types";

const departments = ["CAS", "COEd", "CBMA", "COE", "COF", "CIT", "CCS", "CCJ"] as const;
const peso = (amount: number | null) => amount == null ? "Not set" : new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP" }).format(amount);
const hours = (value: number) => value.toFixed(1) + " h";
const profileValues = (profile: FacultyProfile): FacultyProfilePayload => ({ name: profile.name, rank: profile.rank, employment_status: profile.employment_status, salary_grade: profile.salary_grade, salary_step: profile.salary_step, monthly_salary: profile.monthly_salary, campus: profile.campus, college: profile.college, department: profile.department, service_status: profile.service_status, service_status_effective_date: profile.service_status_effective_date, item_number: profile.item_number, bachelors_degree: profile.bachelors_degree, masters_degree: profile.masters_degree, doctoral_degree: profile.doctoral_degree, eligibility: profile.eligibility, remarks: profile.remarks });

export default function FacultyProfileDetailPage() {
  const canEditPay = getCurrentUser()?.role === "admin";
  const { confirmDiscard, discardDialog } = useDiscardConfirmation();
  const { id } = useParams();
  const [profile, setProfile] = useState<FacultyProfile | null>(null);
  const [form, setForm] = useState<FacultyProfilePayload | null>(null);
  const [salaryScale, setSalaryScale] = useState<SalaryScale | null>(null);
  const [workloads, setWorkloads] = useState<FacultyWorkload[]>([]);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loadRevision, setLoadRevision] = useState(0);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [historyError, setHistoryError] = useState("");
  const [historyLoading, setHistoryLoading] = useState(true);
  const { blocker, dirty, resetBaseline } = useUnsavedChanges(editing ? form : null);
  useEffect(() => {
    let active = true;
    resetBaseline(null); setEditing(false); setForm(null); setNotice("");
    setProfile(null); setError("");
    void Promise.all([getFacultyProfile(Number(id)), getSalaryScale()])
      .then(([loadedProfile, scale]) => {
        if (!active) return;
        setProfile(loadedProfile); setSalaryScale(scale);
      })
      .catch(caught => { if (active) setError(caught instanceof Error ? caught.message : "Unable to load faculty profile."); });
    return () => { active = false; };
  }, [id, loadRevision]);
  useEffect(() => {
    let active = true;
    setWorkloads([]); setHistoryError(""); setHistoryLoading(true);
    if (!profile) return;
    void getFacultyProfileWorkloads(profile.id)
      .then(value => { if (active) setWorkloads(value); })
      .catch(caught => { if (active) setHistoryError(caught instanceof Error ? caught.message : "Unable to load workload history."); })
      .finally(() => { if (active) setHistoryLoading(false); });
    return () => { active = false; };
  }, [profile?.id, profile?.revision, historyRevision]);
  const startEditing = () => {
    if (!profile) return;
    const values = profileValues(profile);
    resetBaseline(values); setForm(values); setEditing(true); setError(""); setNotice("");
  };
  const cancelEditing = async () => {
    if (dirty && !(await confirmDiscard("Discard your unsaved faculty changes? Saved faculty information will stay unchanged."))) return;
    resetBaseline(null); setForm(null); setEditing(false); setError("");
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!profile || !form || saving) return;
    setSaving(true); setError("");
    try {
      const saved = await updateFacultyProfile(profile.id, form, profile.revision);
      setProfile(saved); resetBaseline(null); setForm(null); setEditing(false); setNotice("Faculty profile updated.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to save faculty profile."); }
    finally { setSaving(false); }
  };
  const grade = salaryScale?.grades.find(item => item.salary_grade === form?.salary_grade);
  const rankGrade = salaryScale?.rank_mappings.find(item => item.rank.toLocaleLowerCase() === form?.rank.trim().toLocaleLowerCase())?.salary_grade;
  const selectedSalary = profile?.salary_source ? profile.monthly_salary : grade?.steps.find(item => item.step === form?.salary_step)?.monthly_salary ?? null;
  const updateRank = (rank: string) => setForm(current => current ? { ...current, rank, salary_grade: salaryScale?.rank_mappings.find(item => item.rank.toLocaleLowerCase() === rank.trim().toLocaleLowerCase())?.salary_grade || current.salary_grade } : current);
  if (!profile) return error ? <div className="notice error" role="alert">{error}<div className="action-group"><button className="btn secondary" type="button" onClick={() => setLoadRevision(value => value + 1)}>Retry</button><Link to="/faculty-profiles">Back to directory</Link></div></div> : <PageSkeleton label="Loading faculty profile" />;
  return <div className="stack-md faculty-profile-detail">
    <UnsavedChangesDialog blocker={blocker} />
    {discardDialog}
    <section className="hero-card faculty-profile-hero"><div><span className="eyebrow light">FACULTY PROFILE</span><h1>{editing ? "Edit faculty profile" : profile.name}</h1><p>{editing ? (canEditPay ? "Update general and salary information below." : "Update general information. Appointment and salary changes require an administrator.") : `${profile.rank}${profile.employment_status ? ` · ${profile.employment_status}` : ""}`}</p></div><div className="action-group no-print">{!editing && <button className="btn primary" onClick={startEditing}>Edit Profile</button>}<Link className="btn secondary" to="/faculty-profiles">Back to Directory</Link></div></section>
    <nav className="profile-section-links no-print" aria-label="Faculty record sections"><a href="#profile-general">General information</a><a href="#profile-appointment">Qualifications</a><a href="#profile-salary">Salary record</a><a href="#profile-teaching">Teaching pay</a><a href="#profile-history">Workload history</a></nav>
    {error && <div className="notice error" role="alert">{error}</div>}
    {notice && <div className="notice" role="status">{notice}</div>}
    {historyError && <div className="notice error" role="alert">{historyError} <button className="btn secondary" type="button" onClick={() => setHistoryRevision(value => value + 1)}>Retry workload history</button></div>}
    <form onSubmit={save} className="stack-md"><fieldset disabled={saving} className="profile-edit-fields">
      <section className="data-card faculty-profile-section" id="profile-general">
        <div className="section-heading"><div><span className="eyebrow">FACULTY DETAILS</span><h2>General information</h2></div></div>
        {editing && form ? <div className="form-grid three">
          <label className="span-2">Name<input required maxLength={200} value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} /></label>
          <label>Rank / position<input required disabled={!canEditPay} maxLength={120} list="profile-academic-ranks" value={form.rank} onChange={event => updateRank(event.target.value)} /><datalist id="profile-academic-ranks">{salaryScale?.rank_mappings.map(item => <option key={item.rank} value={item.rank} />)}</datalist></label>
          <label>Employment status<select disabled={!canEditPay} value={form.employment_status} onChange={event => setForm({ ...form, employment_status: event.target.value as FacultyProfilePayload["employment_status"] })}><option value="">Not recorded</option><option>Full-time</option><option>Part-time</option><option>To verify</option></select></label>
          <label>Faculty status<select disabled={!canEditPay} value={form.service_status} onChange={event => setForm({ ...form, service_status: event.target.value as FacultyProfilePayload["service_status"], service_status_effective_date: null })}><option>Active</option><option>Inactive</option><option>Retired</option><option>Resigned</option><option>To verify</option></select></label>
          {["Inactive", "Retired", "Resigned"].includes(form.service_status) && <label>Status effective date<input type="date" disabled={!canEditPay} required={canEditPay} value={form.service_status_effective_date || ""} onChange={event => setForm({ ...form, service_status_effective_date: event.target.value || null })} /></label>}
          <label>Campus<input maxLength={80} list="profile-campuses" value={form.campus || ""} onChange={event => setForm({ ...form, campus: event.target.value || null })} /><datalist id="profile-campuses">{["Talisay", "Alijis", "Fortune Towne", "Binalbagan"].map(campus => <option key={campus} value={campus} />)}</datalist></label>
          <label>Department<select value={form.college} onChange={event => setForm({ ...form, college: event.target.value as FacultyProfilePayload["college"] })}><option value="">Not recorded</option><option>Unassigned</option>{departments.map(department => <option key={department}>{department}</option>)}</select></label>
          <FacultyProgramField department={form.college} value={form.department} onChange={program => setForm({ ...form, department: program })} />
        </div> : <div className="faculty-profile-grid"><span>Faculty status<strong>{profile.service_status}</strong></span><span>Status effective date<strong>{profile.service_status_effective_date || "Not recorded"}</strong></span><span>Campus<strong>{profile.campus || "—"}</strong></span><span>Department<strong>{profile.college || "—"}</strong></span><span>Program<strong>{profile.department || "—"}</strong></span></div>}
      </section>
      <section className="data-card faculty-profile-section" id="profile-appointment">
        <div className="section-heading"><div><span className="eyebrow">PERSONNEL RECORD</span><h2>Qualifications and appointment</h2></div></div>
        {editing && form ? <div className="form-grid three">
          <label>Item number<input maxLength={100} value={form.item_number || ""} onChange={event => setForm({ ...form, item_number: event.target.value || null })} /></label>
          <label>Bachelor’s degree<input maxLength={300} value={form.bachelors_degree || ""} onChange={event => setForm({ ...form, bachelors_degree: event.target.value || null })} /></label>
          <label>Master’s degree<input maxLength={300} value={form.masters_degree || ""} onChange={event => setForm({ ...form, masters_degree: event.target.value || null })} /></label>
          <label>Doctoral degree<input maxLength={300} value={form.doctoral_degree || ""} onChange={event => setForm({ ...form, doctoral_degree: event.target.value || null })} /></label>
          <label>Eligibility<input maxLength={300} value={form.eligibility || ""} onChange={event => setForm({ ...form, eligibility: event.target.value || null })} /></label>
          <label className="span-3">Remarks<textarea maxLength={2000} value={form.remarks || ""} onChange={event => setForm({ ...form, remarks: event.target.value || null })} /></label>
        </div> : <div className="faculty-profile-grid"><span>Item number<strong>{profile.item_number || "—"}</strong></span><span>Bachelor’s degree<strong>{profile.bachelors_degree || "—"}</strong></span><span>Master’s degree<strong>{profile.masters_degree || "—"}</strong></span><span>Doctoral degree<strong>{profile.doctoral_degree || "—"}</strong></span><span>Eligibility<strong>{profile.eligibility || "—"}</strong></span><span>Remarks<strong>{profile.remarks || "—"}</strong></span></div>}
      </section>
      <section className="data-card faculty-profile-section" id="profile-salary">
        <div className="section-heading"><div><span className="eyebrow">SALARY INFORMATION</span><h2>Current salary record</h2></div></div>
        {editing && form && canEditPay ? <div className="form-grid three">
          <label>Salary grade<select value={form.salary_grade || ""} disabled={Boolean(rankGrade)} onChange={event => setForm({ ...form, salary_grade: event.target.value, salary_step: 1 })}><option value="">Select salary grade</option>{salaryScale?.grades.map(item => <option key={item.salary_grade}>{item.salary_grade}</option>)}</select>{rankGrade && <small>Set by academic rank.</small>}</label>
          <label>Salary step<select value={form.salary_step} disabled={!grade} onChange={event => setForm({ ...form, salary_step: Number(event.target.value) })}>{grade ? grade.steps.map(item => <option key={item.step} value={item.step}>Step {item.step}</option>) : <option value={1}>Choose a salary grade first</option>}</select></label>
          <label>Monthly salary<input readOnly value={peso(selectedSalary)} /><small>{profile.salary_source ? "The confirmed salary is preserved when editing this profile." : "Calculated from salary grade and step."}</small></label>
        </div> : <div className="faculty-profile-grid"><span>Salary grade<strong>{profile.salary_grade || "Not set"}</strong></span><span>Salary step<strong>{profile.salary_grade ? "Step " + profile.salary_step : "Not set"}</strong></span><span>Monthly salary<strong>{peso(profile.monthly_salary)}</strong></span></div>}
      </section>
      {editing && <div className="form-actions no-print"><button type="button" className="btn secondary" onClick={cancelEditing}>Cancel</button><button className="btn primary" disabled={saving}>{saving ? "Saving…" : "Save Changes"}</button></div>}
    </fieldset></form>
    <section className="data-card faculty-profile-section" id="profile-teaching">
      <div className="section-heading"><div><span className="eyebrow">APPOINTMENT AND COMPENSATION</span><h2>Teaching pay by term</h2><p>Estimated teaching pay is separate from the monthly salary above. Rates and qualifications follow each saved workload.</p></div></div>
      {historyLoading ? <PageSkeleton label="Loading workload history" variant="table" /> : historyError ? <div className="empty-state">Workload history is unavailable. Use Retry workload history above.</div> : workloads.length === 0 ? <div className="empty-state">No workload or teaching compensation has been recorded yet.</div> : <div className="faculty-compensation-list">{workloads.map(workload => {
        const payLabel = workload.compensation_category === "Regular Faculty" ? "overload" : "teaching";
        const termLabel = workload.term.toLowerCase().includes("summer") ? "summer" : "semester";
        const credential = workload.professional_qualification === "Other" ? workload.professional_qualification_other : workload.professional_qualification === "Doctor" ? "Medical doctor" : workload.professional_qualification;
        return <article key={workload.id} className="faculty-compensation-record">
          <div className="faculty-compensation-heading"><strong>{workload.academic_year} · {workload.term}</strong><Link to={`/workload/${workload.id}`}>View workload</Link></div>
          <div className="faculty-profile-grid">
            <span>Highest academic degree<strong>{workload.highest_qualification === "Masters" ? "Master’s degree" : workload.highest_qualification || "Not recorded"}</strong></span>
            <span>Professional credential<strong>{credential || "None"}</strong></span>
            <span>Compensation category<strong>{workload.compensation_category}</strong></span>
            <span>Hourly rate<strong>{peso(workload.compensation_hourly_rate)}</strong></span>
            <span>Estimated {payLabel} pay / week<strong>{peso(workload.estimated_teaching_pay_weekly)}</strong></span>
            <span>Estimated {payLabel} pay / {termLabel}<strong>{peso(workload.estimated_teaching_pay_term)}</strong><small>{workload.projection_weeks} teaching weeks · excludes base salary</small></span>
            <span>Workflow status<strong>{workload.workflow_status}</strong></span>
          </div>
        </article>;
      })}</div>}
    </section>
    <section className="data-card faculty-profile-section" id="profile-history"><div className="section-heading"><div><span className="eyebrow">WORKLOAD HISTORY</span><h2>Teaching assignments by term</h2><p>{historyLoading ? "Loading workload records…" : historyError ? "Workload records could not be loaded." : workloads.length ? "Saved workload records for this faculty member." : "No workload records have been saved yet."}</p></div><Link className="btn secondary" to="/workload/new">Add Workload</Link></div>{workloads.length > 0 && <TableRegion label="Faculty workload history"><table><thead><tr><th scope="col">Academic year</th><th scope="col">Term</th><th scope="col">Courses</th><th scope="col">Weekly load</th><th scope="col">Overload</th><th scope="col" className="right">Teaching estimate</th></tr></thead><tbody>{workloads.map(workload => <tr key={workload.id}><td><Link to={"/workload/" + workload.id + "/details"}>{workload.academic_year}</Link></td><td>{workload.term}</td><td>{workload.assignments.length}</td><td><strong>{hours(workload.total_weekly_hours)}</strong></td><td>{hours(workload.overload_weekly_hours)}</td><td className="right">{peso(workload.estimated_teaching_pay_weekly)}</td></tr>)}</tbody></table></TableRegion>}</section>
  </div>;
}
