import { useActionDialog } from "../hooks/useActionDialog";
import { FormEvent, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { deleteSemesterOverloadBudget, getActiveProjectionPeriod, getCurrentUser, getSemesterOverloadBudgets, saveActiveProjectionPeriod, saveSemesterOverloadBudget } from "../api";
import type { ActiveProjectionPeriod, SemesterOverloadBudget } from "../api";
import UnsavedChangesDialog from "../components/UnsavedChangesDialog";
import { useDiscardConfirmation } from "../hooks/useDiscardConfirmation";
import PageSkeleton from "../components/PageSkeleton";
import { useUnsavedChanges } from "../hooks/useUnsavedChanges";

const peso = (value: number) => new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);

export default function OfficePeriodPage() {
  const { confirmAction, actionDialog } = useActionDialog();
  const admin = getCurrentUser()?.role === "admin";
  const { confirmDiscard, discardDialog } = useDiscardConfirmation();
  const [form, setForm] = useState<ActiveProjectionPeriod>({ academic_year: "", term: "First Semester" });
  const [savedForm, setSavedForm] = useState(form);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [budgets, setBudgets] = useState<SemesterOverloadBudget[] | null>(null);
  const [budgetYear, setBudgetYear] = useState("");
  const [budgetTerm, setBudgetTerm] = useState<ActiveProjectionPeriod["term"]>("First Semester");
  const [budgetAmount, setBudgetAmount] = useState("");
  const [savedBudgetAmount, setSavedBudgetAmount] = useState("");
  const [budgetSaving, setBudgetSaving] = useState(false);
  const [budgetError, setBudgetError] = useState("");
  const [budgetNotice, setBudgetNotice] = useState("");
  const officeDirty = JSON.stringify(form) !== JSON.stringify(savedForm);
  const budgetDirty = budgetAmount !== savedBudgetAmount;
  const { blocker, dirty } = useUnsavedChanges({ officeDirty, budgetDirty });
  const selectedBudget = budgets?.find((item) => item.academic_year === budgetYear && item.term === budgetTerm);
  useEffect(() => {
    if (!admin) return;
    let active = true;
    setLoading(true); setError("");
    void getActiveProjectionPeriod().then(value => {
      if (!active) return;
      const current = value || { academic_year: "", term: "First Semester" as const };
      setForm(current); setSavedForm(current);
      setBudgetYear(current.academic_year); setBudgetTerm(current.term);
    }).catch(caught => { if (active) setError(caught instanceof Error ? caught.message : "Unable to load the office period."); })
      .finally(() => { if (active) setLoading(false); });
    setBudgets(null); setBudgetError("");
    void getSemesterOverloadBudgets().then(value => { if (active) setBudgets(value); })
      .catch(caught => { if (active) setBudgetError(caught instanceof Error ? caught.message : "Unable to load semester budgets."); });
    return () => { active = false; };
  }, [admin, revision]);

  useEffect(() => {
    const amount = budgets?.find((item) => item.academic_year === budgetYear && item.term === budgetTerm)?.amount.toFixed(2) ?? "";
    setBudgetAmount(amount);
    setSavedBudgetAmount(amount);
  }, [budgets, budgetYear, budgetTerm]);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (saving) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const saved = await saveActiveProjectionPeriod({ ...form, academic_year: form.academic_year.trim() });
      setForm(saved); setSavedForm(saved); setNotice("Office period saved. Dashboard and overall report will use this semester.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to save the office period."); }
    finally { setSaving(false); }
  };

  const saveBudget = async (event: FormEvent) => {
    event.preventDefault();
    if (budgetSaving) return;
    setBudgetSaving(true); setBudgetError(""); setBudgetNotice("");
    try {
      const saved = await saveSemesterOverloadBudget({ academic_year: budgetYear.trim(), term: budgetTerm, amount: budgetAmount, revision: selectedBudget?.revision ?? 0 });
      setBudgets((current) => [...(current ?? []).filter((item) => item.id !== saved.id), saved]);
      setBudgetNotice(`Overload budget saved for A.Y. ${saved.academic_year} ${saved.term}.`);
    } catch (caught) { setBudgetError(caught instanceof Error ? caught.message : "Unable to save the semester budget."); }
    finally { setBudgetSaving(false); }
  };

  const removeBudget = async () => {
    if (!selectedBudget || budgetSaving || !await confirmAction(`Remove the overload budget for A.Y. ${selectedBudget.academic_year} ${selectedBudget.term}?`, "Remove semester budget?", "Remove budget")) return;
    setBudgetSaving(true); setBudgetError(""); setBudgetNotice("");
    try {
      await deleteSemesterOverloadBudget(selectedBudget.id, selectedBudget.revision ?? 0);
      setBudgets((current) => current?.filter((item) => item.id !== selectedBudget.id) ?? []);
      setBudgetNotice("Semester overload budget removed. The Dashboard will show no budget for this semester.");
    } catch (caught) { setBudgetError(caught instanceof Error ? caught.message : "Unable to remove the semester budget."); }
    finally { setBudgetSaving(false); }
  };

  const selectBudgetPeriod = async (year: string, term: ActiveProjectionPeriod["term"]) => {
    if (budgetDirty && !(await confirmDiscard("Discard the unsaved budget amount? Saved semester budgets will stay unchanged."))) return;
    setBudgetYear(year); setBudgetTerm(term);
    const amount = budgets?.find((item) => item.academic_year === year && item.term === term)?.amount.toFixed(2) ?? "";
    setBudgetAmount(amount); setSavedBudgetAmount(amount);
    setBudgetError(""); setBudgetNotice("");
  };
  if (!admin) return <Navigate to="/settings" replace />;
  return <div className="stack-md"><UnsavedChangesDialog blocker={blocker} />{discardDialog}{actionDialog}
    <section className="hero-card compact"><div><span className="eyebrow">SETTINGS</span><h1>Office reporting period</h1><p>Choose the default semester for shared statistics. No salaries, workloads, or approved records are changed.</p></div></section>
    {error && <div role="alert" className="notice error">{error} <button className="btn secondary" type="button" disabled={saving || dirty} onClick={() => setRevision(value => value + 1)}>Retry loading</button></div>}
    {notice && <div role="status" className="notice">{notice}</div>}
    {loading ? <PageSkeleton label="Loading office period" variant="form" /> : <form className="form-card" onSubmit={save}><fieldset className="profile-edit-fields" disabled={saving}>
      <h2>Active semester</h2>
      <div className="form-grid three"><label>Academic year<input required pattern="[0-9]{4}-[0-9]{4}" placeholder="e.g. 2026-2027" value={form.academic_year} onChange={event => setForm({ ...form, academic_year: event.target.value })} /></label>
      <label>Semester<select value={form.term} onChange={event => setForm({ ...form, term: event.target.value as ActiveProjectionPeriod["term"] })}><option>First Semester</option><option>Second Semester</option></select></label></div>
      <p>Enter consecutive years. Personal salary-report selections remain separate; choose Use office active period in a report to reset its scope.</p>
      <div className="form-actions"><button className="btn primary" disabled={!officeDirty || saving}>{saving ? "Saving…" : "Save office period"}</button></div>
    </fieldset></form>}
    <section className="form-card" aria-labelledby="overload-budget-heading">
      <span className="eyebrow">OVERLOAD PLANNING</span><h2 id="overload-budget-heading">Semester overload budgets</h2>
      <p>Save a separate amount for each academic year and semester. The Dashboard compares this amount with projected regular-faculty overload only. It is not a cash balance or approved payment.</p>
      {budgetError && <div className="notice error" role="alert">{budgetError} {budgets === null && <button className="btn secondary" type="button" disabled={dirty} onClick={() => setRevision((value) => value + 1)}>Retry loading</button>}</div>}
      {budgetNotice && <div className="notice" role="status">{budgetNotice}</div>}
      {budgets === null && !budgetError ? <PageSkeleton label="Loading semester budgets" variant="form" /> : budgets !== null && <>
        <form onSubmit={saveBudget}><fieldset className="profile-edit-fields" disabled={budgetSaving}>
          <div className="form-grid three">
            <label>Academic year<input required pattern="[0-9]{4}-[0-9]{4}" placeholder="e.g. 2026-2027" value={budgetYear} onChange={(event) => selectBudgetPeriod(event.target.value, budgetTerm)} /></label>
            <label>Semester<select value={budgetTerm} onChange={(event) => selectBudgetPeriod(budgetYear, event.target.value as ActiveProjectionPeriod["term"])}><option>First Semester</option><option>Second Semester</option></select></label>
            <label>Overload budget (₱)<input required type="number" min="0.01" max="999999999.99" step="0.01" value={budgetAmount} onChange={(event) => setBudgetAmount(event.target.value)} /></label>
          </div>
          <div className="form-actions"><button className="btn primary" disabled={!budgetDirty || budgetSaving}>{budgetSaving ? "Saving…" : "Save semester budget"}</button>{selectedBudget && <button className="btn secondary danger" type="button" onClick={() => void removeBudget()} disabled={budgetSaving}>Remove budget</button>}</div>
        </fieldset></form>
        {budgets.length > 0 && <div className="table-scroll"><table><thead><tr><th>Academic year</th><th>Semester</th><th className="right">Overload budget</th><th>Action</th></tr></thead><tbody>{budgets.map((item) => <tr key={item.id}><td>{item.academic_year}</td><td>{item.term}</td><td className="right">{peso(item.amount)}</td><td><button type="button" className="btn secondary" onClick={() => selectBudgetPeriod(item.academic_year, item.term)}>Edit</button></td></tr>)}</tbody></table></div>}
      </>}
    </section>
  </div>;
}
