import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { createWorkload, getFacultyProfileOptions, getWorkload, updateWorkload } from "../api";
import FormError from "../components/FormError";
import ImportedOverloadNotice from "../components/ImportedOverloadNotice";
import PageSkeleton from "../components/PageSkeleton";
import UnsavedChangesDialog from "../components/UnsavedChangesDialog";
import { useDiscardConfirmation } from "../hooks/useDiscardConfirmation";
import { useUnsavedChanges } from "../hooks/useUnsavedChanges";
import type { FacultyProfile, FacultyWorkload, FacultyWorkloadPayload, TeachingAssignmentPayload } from "../types";

const blankAssignment = (): TeachingAssignmentPayload => ({ course_code: "", course_title: "", year_section: "", lecture_hours: 0, laboratory_hours: 0 });
const blankWorkload = (): FacultyWorkloadPayload => ({ faculty_profile_id: 0, academic_year: "2026-2027", term: "First Semester", remarks: "", compensation_category: "Regular Faculty", highest_qualification: null, professional_qualification: "None", professional_qualification_other: null, assignments: [] });
const knownTermStarts: Record<string, string> = { "2026-2027:First Semester": "2026-08-12", "2026-2027:Second Semester": "2027-01-13", "2026-2027:Summer": "2027-06-14" };

function statusConflictsWithPeriod(profile: FacultyProfile, academicYear: string, term: string): boolean {
  if (!["Inactive", "Retired", "Resigned"].includes(profile.service_status)) return false;
  if (!profile.service_status_effective_date) return true;
  const effectiveDate = profile.service_status_effective_date;
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  if (effectiveDate <= today) return true;
  const start = knownTermStarts[`${academicYear.trim()}:${term}`];
  if (start) return effectiveDate <= start;
  const years = academicYear.trim().match(/^(\d{4})-(\d{4})$/);
  if (!years) return false;
  const termYear = term === "First Semester" ? Number(years[1]) : Number(years[2]);
  return Number(effectiveDate.slice(0, 4)) < termYear;
}

export default function WorkloadFormPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { confirmDiscard, discardDialog } = useDiscardConfirmation();
  const [profiles, setProfiles] = useState<FacultyProfile[]>([]);
  const [form, setForm] = useState(blankWorkload);
  const [draft, setDraft] = useState(blankAssignment);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [showEditor, setShowEditor] = useState(false);
  const [error, setError] = useState("");
  const [sourceRecord, setSourceRecord] = useState<FacultyWorkload | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [loadRevision, setLoadRevision] = useState(0);
  const [saving, setSaving] = useState(false);
  const { blocker, resetBaseline, allowLeave } = useUnsavedChanges({ form, draft });

  useEffect(() => {
    let active = true;
    setInitialLoading(true);
    setLoadError(""); setError(""); setSourceRecord(null);
    setShowEditor(false); setEditingIndex(null); setDraft(blankAssignment());
    const initial = blankWorkload();
    resetBaseline({ form: initial, draft: blankAssignment() }); setForm(initial);
    void (async () => {
      try {
        const options = await getFacultyProfileOptions();
        if (!active) return;
        setProfiles(options);
        if (!id) return;
        const item = await getWorkload(Number(id));
        if (!active) return;
        setSourceRecord(item);
        const loaded: FacultyWorkloadPayload = {
          faculty_profile_id: item.faculty_profile_id, academic_year: item.academic_year, term: item.term,
          remarks: item.remarks || "", compensation_category: item.compensation_category,
          highest_qualification: item.highest_qualification,
          professional_qualification: item.professional_qualification || "None",
          professional_qualification_other: item.professional_qualification_other || null,
          assignments: item.assignments.map(({ id: assignmentId, ...assignment }) => assignment),
        };
        resetBaseline({ form: loaded, draft: blankAssignment() });
        setForm(loaded);
      } catch (caught) {
        if (active) setLoadError(caught instanceof Error ? caught.message : "Unable to load workload.");
      } finally {
        if (active) setInitialLoading(false);
      }
    })();
    return () => { active = false; };
  }, [id, loadRevision]);

  const closeEditor = () => { setShowEditor(false); setEditingIndex(null); setDraft(blankAssignment()); };

  const saveAssignment = () => {
    const problems = [];
    if (!draft.course_code.trim()) problems.push("Course code: enter a course code.");
    if (!draft.course_title.trim()) problems.push("Course title: enter a course title.");
    if (!draft.year_section.trim()) problems.push("Year and section: enter the class section.");
    if (![draft.lecture_hours, draft.laboratory_hours].every((hours) => Number.isFinite(hours) && hours >= 0 && hours <= 80)) problems.push("Weekly hours: lecture and laboratory hours must each be between 0 and 80.");
    if (draft.lecture_hours + draft.laboratory_hours <= 0) problems.push("Weekly hours: enter lecture or laboratory hours greater than zero.");
    if (problems.length) { setError(problems.join("; ")); return; }
    setForm((current) => ({
      ...current,
      assignments: editingIndex === null ? [...current.assignments, draft] : current.assignments.map((assignment, index) => index === editingIndex ? draft : assignment),
    }));
    closeEditor();
    setError("");
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (saving || initialLoading || loadError || (id && !sourceRecord)) return;
    if (showEditor) { setError("Save or cancel the open assignment before saving the workload."); return; }
    if (!form.faculty_profile_id || !form.assignments.length) { setError("Select a faculty member and add an assignment."); return; }
    setSaving(true);
    try {
      if (id) await updateWorkload(Number(id), form, sourceRecord?.revision ?? -1);
      else await createWorkload(form);
      allowLeave();
      navigate(id ? `/workload/${id}` : "/workload");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save workload.");
    } finally {
      setSaving(false);
    }
  };

  if (loadError) return <div className="notice error" role="alert">{loadError}<div className="action-group"><button className="btn secondary" type="button" onClick={() => setLoadRevision(value => value + 1)}>Retry</button><Link to="/workload">Back to workloads</Link></div></div>;
  if (initialLoading) return <PageSkeleton label="Loading workload form" variant="form" />;
  return <div className="form-page stack-md">
    <UnsavedChangesDialog blocker={blocker} />{discardDialog}
    <section className="hero-card compact"><div><span className="eyebrow">FACULTY WORKLOAD</span><h1>{id ? "Edit Workload" : "Add Workload"}</h1></div><Link className="btn secondary" to={id ? `/workload/${id}` : "/workload"}>Back</Link></section>
    <FormError message={error} />
    {sourceRecord && <ImportedOverloadNotice record={sourceRecord} />}
    <form onSubmit={save} className="stack-md">
      <section className="form-card"><div className="form-card-head"><span>01</span><div><h2>Faculty and teaching period</h2></div></div><div className="form-grid three">
        <label>Faculty Member<select value={form.faculty_profile_id} onChange={(event) => setForm({ ...form, faculty_profile_id: Number(event.target.value) })}><option value={0}>Select faculty member</option>{profiles.map((profile) => {
          const inactive = statusConflictsWithPeriod(profile, form.academic_year, form.term);
          return <option key={profile.id} value={profile.id} disabled={inactive && profile.id !== form.faculty_profile_id}>{profile.name} — {profile.department}{inactive ? ` (${profile.service_status}: conflicts with selected period)` : ""}</option>;
        })}</select></label>
        <label>Academic Year<input required maxLength={20} value={form.academic_year} onChange={(event) => setForm({ ...form, academic_year: event.target.value })} /></label>
        <label>Term<select value={form.term} onChange={(event) => setForm({ ...form, term: event.target.value })}><option>First Semester</option><option>Second Semester</option><option>Summer</option></select></label>
        <label>Teaching category<select value={form.compensation_category} onChange={(event) => setForm({ ...form, compensation_category: event.target.value as FacultyWorkloadPayload["compensation_category"] })}><option>Regular Faculty</option><option>Internal Part-time</option><option>External Part-time</option></select></label>
        <label>Highest academic degree<select value={form.highest_qualification || ""} onChange={(event) => setForm({ ...form, highest_qualification: (event.target.value || null) as FacultyWorkloadPayload["highest_qualification"] })}><option value="">Not recorded</option><option value="Bachelor">Bachelor’s degree</option><option value="Masters">Master’s degree</option><option value="Doctorate">Doctorate</option></select></label>
        <label>Professional credential<select value={form.professional_qualification} onChange={(event) => setForm({ ...form, professional_qualification: event.target.value as FacultyWorkloadPayload["professional_qualification"], professional_qualification_other: null })}><option>None</option><option value="Doctor">Medical doctor</option><option>Lawyer</option><option>CPA</option><option>Other</option></select><small>Degrees and credentials are separate. Existing rate additions apply only to external part-time teaching; CPA and Other have no rate addition yet.</small></label>
        {form.professional_qualification === "Other" && <label>Other professional credential<input required maxLength={200} value={form.professional_qualification_other || ""} onChange={(event) => setForm({ ...form, professional_qualification_other: event.target.value })} /></label>}
      </div></section>
      <section className="form-card">
        <div className="form-card-head"><span>02</span><div><h2>Teaching Assignments</h2></div></div>
        <div className="table-scroll" role="region" aria-label="Edit teaching assignments" tabIndex={0}><table><thead><tr><th>Course</th><th>Title</th><th>Section</th><th>Lecture</th><th>Laboratory</th><th>Actions</th></tr></thead><tbody>
          {form.assignments.length ? form.assignments.map((assignment, index) => <tr key={index}><td>{assignment.course_code}</td><td>{assignment.course_title}</td><td>{assignment.year_section}</td><td>{assignment.lecture_hours}</td><td>{assignment.laboratory_hours}</td><td><button type="button" className="btn secondary" disabled={showEditor} onClick={() => { setDraft({ ...assignment }); setEditingIndex(index); setShowEditor(true); }}>Edit</button> <button type="button" className="btn secondary" disabled={showEditor} onClick={() => setForm((current) => ({ ...current, assignments: current.assignments.filter((_, itemIndex) => itemIndex !== index) }))}>Remove</button></td></tr>) : <tr><td colSpan={6} className="empty-table">No assignments added.</td></tr>}
        </tbody></table></div>
        {!showEditor ? <button type="button" className="btn secondary" onClick={() => { setEditingIndex(null); setDraft(blankAssignment()); setShowEditor(true); }}>Add Assignment</button> : <div className="relation-editor">
          <h3>{editingIndex === null ? "Add assignment" : "Edit assignment"}</h3>
          <div className="form-grid three">
            <label>Course Code<input maxLength={50} value={draft.course_code} onChange={(event) => setDraft({ ...draft, course_code: event.target.value })} /></label>
            <label>Course Title<input maxLength={300} value={draft.course_title} onChange={(event) => setDraft({ ...draft, course_title: event.target.value })} /></label>
            <label>Year &amp; Section<input maxLength={120} value={draft.year_section} onChange={(event) => setDraft({ ...draft, year_section: event.target.value })} /></label>
            <label>Lecture Hours<input type="number" min={0} max={80} step="any" value={draft.lecture_hours || ""} onChange={(event) => setDraft({ ...draft, lecture_hours: Number(event.target.value) || 0 })} /></label>
            <label>Laboratory Hours<input type="number" min={0} max={80} step="any" value={draft.laboratory_hours || ""} onChange={(event) => setDraft({ ...draft, laboratory_hours: Number(event.target.value) || 0 })} /></label>
          </div>
          <div className="form-actions"><button type="button" className="btn secondary" onClick={async () => { if (await confirmDiscard("Discard this assignment editor’s changes? Courses already added to the workload form will stay unchanged.")) closeEditor(); }}>Cancel</button><button type="button" className="btn primary" onClick={saveAssignment}>Save Assignment</button></div>
        </div>}
      </section>
      <div className="form-actions"><button className="btn primary" disabled={saving}>{saving ? "Saving…" : "Save Workload"}</button></div>
    </form>
  </div>;
}
