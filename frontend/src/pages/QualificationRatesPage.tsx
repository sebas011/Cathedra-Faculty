import { FormEvent, useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { getCurrentUser, getQualificationDraft, saveQualificationDraft } from "../api";
import type { QualificationDraft, QualificationDraftInput, QualificationRate } from "../types";
import { useUnsavedChanges } from "../hooks/useUnsavedChanges";
import UnsavedChangesDialog from "../components/UnsavedChangesDialog";
import { useDiscardConfirmation } from "../hooks/useDiscardConfirmation";
import PageSkeleton from "../components/PageSkeleton";

const emptyPlan = (): QualificationDraftInput => ({ revision: 0, combination_rule: "Unconfirmed", rates: [] });
const emptyRate = (): QualificationRate => ({ category: "Professional credential", qualification: "", hourly_addition: 0, effective_from: "", effective_to: null, reference: "" });
const inputValues = (value: QualificationDraft): QualificationDraftInput => ({ revision: value.revision, combination_rule: value.combination_rule, rates: value.rates });
const peso = (value: number) => new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP" }).format(value);

export default function QualificationRatesPage() {
  const admin = getCurrentUser()?.role === "admin";
  const { confirmDiscard, discardDialog } = useDiscardConfirmation();
  const [plan, setPlan] = useState(emptyPlan);
  const [saved, setSaved] = useState<QualificationDraft | null>(null);
  const [draft, setDraft] = useState(emptyRate);
  const [editing, setEditing] = useState<number | null>(null);
  const [showEditor, setShowEditor] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const { blocker, dirty, resetBaseline } = useUnsavedChanges({ plan, draft: showEditor ? draft : null });
  useEffect(() => {
    if (!admin) return;
    let active = true;
    setLoading(true); setError(""); setNotice("");
    void getQualificationDraft().then(value => {
      if (!active) return;
      const current = inputValues(value);
      resetBaseline({ plan: current, draft: null }); setPlan(current); setSaved(value); setShowEditor(false); setEditing(null); setDraft(emptyRate());
    }).catch(caught => { if (active) setError(caught instanceof Error ? caught.message : "Unable to load qualification settings."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [admin, revision]);
  const reload = async () => { if (!dirty || await confirmDiscard("Discard local changes and reload the saved draft? Current compensation will stay unchanged.")) setRevision(value => value + 1); };
  const addRate = (event: FormEvent) => {
    event.preventDefault();
    const value = { ...draft, qualification: draft.qualification.trim(), reference: draft.reference.trim() };
    if (!value.qualification || !value.effective_from || !Number.isFinite(value.hourly_addition) || value.hourly_addition < 0 || (value.effective_to && value.effective_to < value.effective_from)) {
      setError("Enter a qualification, a valid amount, and an end date on or after the start date."); return;
    }
    if (plan.rates.some((rate, index) => index !== editing && rate.category === value.category && rate.qualification.trim().toLocaleLowerCase() === value.qualification.toLocaleLowerCase() && (!rate.effective_to || rate.effective_to >= value.effective_from) && (!value.effective_to || value.effective_to >= rate.effective_from))) {
      setError("This qualification already has a rate for part of that date range. End the earlier rate before the next starts."); return;
    }
    setPlan(current => ({ ...current, rates: editing === null ? [...current.rates, value] : current.rates.map((rate, index) => index === editing ? value : rate) }));
    setShowEditor(false); setEditing(null); setDraft(emptyRate()); setError(""); setNotice("Rate added to the local draft. Save draft settings to keep your changes.");
  };
  const save = async () => {
    if (saving || showEditor) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const result = await saveQualificationDraft(plan);
      const current = inputValues(result);
      resetBaseline({ plan: current, draft: null }); setSaved(result); setPlan(current);
      setNotice("Draft settings saved. No compensation calculations or approved records were changed.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to save draft settings."); }
    finally { setSaving(false); }
  };
  if (!admin) return <Navigate to="/settings" replace />;
  return <div className="stack-md"><UnsavedChangesDialog blocker={blocker} />{discardDialog}
    <section className="hero-card compact"><div><span className="eyebrow">SETTINGS · EXTERNAL PART-TIME</span><h1>Qualification rate drafts</h1><p>Prepare degree and professional-credential additions without changing current pay.</p></div><Link className="btn secondary" to="/settings/compensation">Current compensation rules</Link></section>
    <div className="notice" role="status"><strong>Draft — not applied.</strong> These entries do not affect any calculation, even after their dates arrive. Current Compensation Rules remain in use. Activation requires confirmation of the approved amounts, combination rule, and which workload date selects a rate.</div>
    {error && <div className="notice error" role="alert">{error}</div>}{notice && <div className="notice" role="status">{notice}</div>}
    {loading ? <PageSkeleton label="Loading qualification settings" variant="form" /> : !saved ? <button className="btn secondary" onClick={reload}>Retry loading</button> : <>
      <section className="data-card workspace-card"><h2>How additions should combine</h2><div className="form-grid three"><label>Proposed combination rule<select disabled={saving} value={plan.combination_rule} onChange={event => setPlan({ ...plan, combination_rule: event.target.value as QualificationDraftInput["combination_rule"] })}><option>Unconfirmed</option><option>Combine additions</option><option>Highest addition only</option></select></label></div><p>Combine additions proposes adding the applicable degree and professional-credential amounts. Highest addition only proposes using the largest applicable addition. Neither choice changes the current calculation until the policy is confirmed and activated.</p><small>{saved.updated_at ? `Last saved by ${saved.updated_by} · ${new Date(saved.updated_at).toLocaleString("en-PH")} · revision ${saved.revision}` : "No draft settings saved yet."}</small></section>
      <section className="data-card workspace-card"><div className="section-heading"><div><h2>Proposed hourly additions</h2><p>Amounts are additions per teaching hour, not full hourly rates. New entries start at ₱0. Date ranges include both start and end dates.</p></div><button className="btn secondary" disabled={saving || showEditor || plan.rates.length >= 200} onClick={() => { setDraft(emptyRate()); setEditing(null); setShowEditor(true); setError(""); setNotice(""); }}>Add qualification rate</button></div>
        <div className="table-scroll"><table><thead><tr><th>Qualification</th><th>Category</th><th>Hourly addition</th><th>Effective dates</th><th>Reference / notes</th><th>Actions</th></tr></thead><tbody>{plan.rates.length === 0 ? <tr><td colSpan={6} className="empty-table">No draft rates yet. Add CPA, Engineer, a degree, or another named qualification.</td></tr> : plan.rates.map((rate, index) => <tr key={index}><td><strong>{rate.qualification}</strong></td><td>{rate.category}</td><td>{peso(rate.hourly_addition)}</td><td>{rate.effective_from} → {rate.effective_to || "No end date"}</td><td>{rate.reference || "—"}</td><td><div className="action-group"><button className="btn secondary" disabled={saving || showEditor} onClick={() => { setDraft({ ...rate }); setEditing(index); setShowEditor(true); setNotice(""); }}>Edit</button><button className="btn secondary danger" disabled={saving || showEditor} onClick={() => { if (confirm("Remove this rate from the draft? Current compensation is unchanged.")) setPlan(current => ({ ...current, rates: current.rates.filter((_, position) => position !== index) })); }}>Remove</button></div></td></tr>)}</tbody></table></div>
      </section>
      {showEditor && <form className="form-card" onSubmit={addRate}><h2>{editing === null ? "Add qualification rate" : "Edit qualification rate"}</h2><fieldset className="profile-edit-fields" disabled={saving}><div className="form-grid three">
        <label>Category<select value={draft.category} onChange={event => setDraft({ ...draft, category: event.target.value as QualificationRate["category"] })}><option>Academic degree</option><option>Professional credential</option></select></label>
        <label>Qualification name<input required maxLength={120} list="qualification-suggestions" value={draft.qualification} onChange={event => setDraft({ ...draft, qualification: event.target.value })} /><datalist id="qualification-suggestions">{(draft.category === "Academic degree" ? ["Bachelor’s degree", "Master’s degree", "Doctorate"] : ["Medical doctor", "Lawyer", "CPA", "Engineer"]).map(name => <option key={name} value={name} />)}</datalist></label>
        <label>Hourly addition (PHP)<input required type="number" min="0" max="100000" step="0.01" value={Number.isNaN(draft.hourly_addition) ? "" : draft.hourly_addition} onChange={event => setDraft({ ...draft, hourly_addition: event.target.valueAsNumber })} /></label>
        <label>Effective from<input required type="date" value={draft.effective_from} onChange={event => setDraft({ ...draft, effective_from: event.target.value })} /></label>
        <label>Effective through (optional)<input type="date" min={draft.effective_from || undefined} value={draft.effective_to || ""} onChange={event => setDraft({ ...draft, effective_to: event.target.value || null })} /></label>
        <label>Policy reference / notes<input maxLength={500} value={draft.reference} onChange={event => setDraft({ ...draft, reference: event.target.value })} /></label>
      </div><div className="form-actions"><button className="btn secondary" type="button" onClick={async () => { if (await confirmDiscard("Discard this rate editor’s changes? Rates already added to the draft will stay unchanged.")) { setShowEditor(false); setEditing(null); setDraft(emptyRate()); setError(""); } }}>Cancel rate</button><button className="btn primary">{editing === null ? "Add to draft" : "Update draft row"}</button></div></fieldset></form>}
      <section className="data-card workspace-card"><p>{showEditor ? "Finish or cancel the open rate editor before saving." : dirty ? "You have unsaved draft changes." : "Saved draft is up to date."}</p><div className="action-group"><button className="btn secondary" disabled={saving} onClick={reload}>Reload saved draft</button><button className="btn primary" disabled={saving || showEditor || !dirty} onClick={() => void save()}>{saving ? "Saving…" : "Save draft settings"}</button></div></section>
    </>}
  </div>;
}
