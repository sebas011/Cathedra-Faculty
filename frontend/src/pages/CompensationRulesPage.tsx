import { FormEvent, useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { getCurrentUser, getWorkloadCostSettings, updateWorkloadCostSettings } from "../api";
import type { WorkloadCostSettings } from "../types";
import { useUnsavedChanges } from "../hooks/useUnsavedChanges";
import { useDiscardConfirmation } from "../hooks/useDiscardConfirmation";
import UnsavedChangesDialog from "../components/UnsavedChangesDialog";
import PageSkeleton from "../components/PageSkeleton";

type Settings = Omit<WorkloadCostSettings, "updated_at">;
const fields: { key: keyof Settings; label: string; min: number; max?: number; step: number }[] = [
  { key: "internal_monthly_equivalent_hours", label: "Internal monthly equivalent hours", min: 1, step: 0.01 },
  { key: "external_base_hourly_rate", label: "External base hourly rate (PHP)", min: 0, step: 0.01 },
  { key: "external_masters_increment", label: "Master’s addition (PHP)", min: 0, step: 0.01 },
  { key: "external_doctorate_increment", label: "Doctorate addition (PHP)", min: 0, step: 0.01 },
  { key: "external_doctor_increment", label: "Doctor addition (PHP)", min: 0, step: 0.01 },
  { key: "external_lawyer_increment", label: "Lawyer addition (PHP)", min: 0, step: 0.01 },
  { key: "first_semester_weeks", label: "First semester weeks", min: 0, max: 30, step: 1 },
  { key: "second_semester_weeks", label: "Second semester weeks", min: 0, max: 30, step: 1 },
  { key: "summer_weeks", label: "Summer weeks", min: 0, max: 30, step: 1 },
];
const values = ({ updated_at, ...settings }: WorkloadCostSettings): Settings => settings;

export default function CompensationRulesPage() {
  const isAdmin = getCurrentUser()?.role === "admin";
  const { confirmDiscard, discardDialog } = useDiscardConfirmation();
  const [form, setForm] = useState<Settings | null>(null);
  const [saved, setSaved] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loadRevision, setLoadRevision] = useState(0);
  const { blocker, dirty, resetBaseline } = useUnsavedChanges(form);
  useEffect(() => {
    if (!isAdmin) return;
    let active = true;
    setError("");
    void getWorkloadCostSettings().then(result => {
      if (!active) return;
      const settings = values(result);
      resetBaseline(settings); setForm(settings); setSaved(settings);
    }).catch(caught => { if (active) setError(caught instanceof Error ? caught.message : "Unable to load compensation rules."); });
    return () => { active = false; };
  }, [isAdmin, loadRevision]);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!form || saving) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const settings = values(await updateWorkloadCostSettings(form));
      resetBaseline(settings); setForm(settings); setSaved(settings); setNotice("Compensation rules saved.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to save compensation rules."); }
    finally { setSaving(false); }
  };
  if (!isAdmin) return <Navigate to="/workload" replace />;
  return <div className="stack-md">
    <UnsavedChangesDialog blocker={blocker} />
    {discardDialog}
    <section className="hero-card compact"><div><span className="eyebrow">SETTINGS</span><h1>Compensation Rules</h1><p>Manage the rates and teaching weeks used in planning estimates.</p></div><Link className="btn secondary" to="/expenses">Expenses Projection</Link></section>
    {error && <div className="notice error" role="alert">{error}{!form && <button className="btn secondary" type="button" onClick={() => setLoadRevision(value => value + 1)}>Retry</button>}</div>}
    {notice && <div className="notice" role="status">{notice}</div>}
    <section className="data-card compensation-rules-summary"><h2>Regular faculty rules</h2><p>Regular load is 21 hours for two or fewer preparations, or 18 hours for three or more. Overload hourly rate = monthly salary × 12 × 0.000781.</p><p>Semester pay = weekly overload × hourly rate × teaching weeks. Standard durations are 18 weeks per semester and 6 for summer. <Link to="/office-guide#planning-estimates">Read the projection guide</Link></p></section>
    {form ? <form className="form-card" onSubmit={save}><fieldset disabled={saving} className="profile-edit-fields"><div className="form-grid three">{fields.map(field => <label key={field.key}>{field.label}<input required type="number" min={field.min} max={field.max} step={field.step} value={Number.isNaN(form[field.key]) ? "" : form[field.key]} onChange={event => setForm({ ...form, [field.key]: event.target.valueAsNumber })} /></label>)}</div><div className="form-actions"><button className="btn secondary" type="button" disabled={!dirty || saving} onClick={async () => { if (!dirty || await confirmDiscard("Discard unsaved rule changes? Saved compensation rules will stay unchanged.")) { resetBaseline(saved); setForm(saved); setError(""); setNotice(""); } }}>Discard Changes</button><button className="btn primary" disabled={!dirty || saving}>{saving ? "Saving…" : "Save Rules"}</button></div></fieldset></form> : !error && <PageSkeleton label="Loading compensation rules" variant="form" />}
  </div>;
}
