import { useActionDialog } from "../hooks/useActionDialog";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { createDatabaseBackup, downloadExport, getActiveProjectionPeriod, getApprovedWorkloadSummary, getCloseoutEstimate, getMaintenanceStatus, getMonthlySalaryProjection, saveCloseoutEstimate } from "../api";
import type { CloseoutTerm } from "../api";
import PageSkeleton from "../components/PageSkeleton";
import type { ApprovedWorkloadSummary, MaintenanceStatus, MonthlySalaryProjection, SavedProjection } from "../types";

type Scope = { year:string; term:CloseoutTerm; asOf:string };
type CloseoutData = { scope:Scope; summary:ApprovedWorkloadSummary; status:MaintenanceStatus; estimate:SavedProjection|null; projection:MonthlySalaryProjection };
const money = (value:number|null) => value === null ? "Incomplete" : new Intl.NumberFormat("en-PH", { style:"currency", currency:"PHP" }).format(value);
const localToday = () => {
  const today = new Date();
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
};
const validYear = (value:string) => /^\d{4}-\d{4}$/.test(value) && Number(value.slice(5)) === Number(value.slice(0, 4)) + 1;
const validTerm = (value:string|null):value is CloseoutTerm => ["First Semester", "Second Semester", "Summer"].includes(value || "");

export default function SemesterCloseoutPage() {
  const { confirmAction, actionDialog } = useActionDialog();
  const [params] = useSearchParams();
  const [year, setYear] = useState("");
  const [term, setTerm] = useState<CloseoutTerm>("First Semester");
  const [asOf, setAsOf] = useState(localToday);
  const [data, setData] = useState<CloseoutData|null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const requestId = useRef(0);

  const loadFor = useCallback(async (scope:Scope) => {
    const current = ++requestId.current;
    setError("");
    setData(null);
    if (!validYear(scope.year) || !scope.asOf) {
      setError("Enter a consecutive academic year, such as 2026-2027, and a status assessment date.");
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [summary, status, estimate, projection] = await Promise.all([
        getApprovedWorkloadSummary(scope.year, scope.term), getMaintenanceStatus(),
        getCloseoutEstimate(scope.year, scope.term),
        getMonthlySalaryProjection("", "", scope.year, scope.term, scope.term === "Summer" ? "summer" : "semester", scope.asOf),
      ]);
      if (current === requestId.current) setData({ scope, summary, status, estimate, projection });
    } catch (caught) {
      if (current === requestId.current) setError(caught instanceof Error ? caught.message : "Unable to prepare the closeout check.");
    } finally {
      if (current === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const requestedYear = params.get("academic_year");
        const requestedTerm = params.get("term");
        const defaults = requestedYear && validYear(requestedYear) && validTerm(requestedTerm)
          ? { academic_year:requestedYear, term:requestedTerm }
          : await getActiveProjectionPeriod();
        if (!active) return;
        if (!defaults) { setError("Choose an academic year and term, or set the office period in Settings."); setLoading(false); return; }
        setYear(defaults.academic_year);
        setTerm(defaults.term);
        await loadFor({ year:defaults.academic_year, term:defaults.term, asOf:localToday() });
      } catch (caught) {
        if (active) { setError(caught instanceof Error ? caught.message : "Unable to load the office period."); setLoading(false); }
      }
    })();
    return () => { active = false; requestId.current += 1; };
  }, [loadFor, params]);

  const scope = { year:year.trim(), term, asOf };
  const scopeMatches = !!data && data.scope.year === scope.year && data.scope.term === term && data.scope.asOf === asOf;
  const load = () => { setNotice(""); void loadFor(scope); };
  const capture = async () => {
    if (!data || !scopeMatches || data.estimate) return;
    const warningText = data.projection.warnings.length ? ` ${data.projection.warnings.length} coverage warnings will be retained.` : "";
    if (!await confirmAction(`Save the planning estimate for ${data.scope.year} ${data.scope.term} as its permanent closeout record? Status is assessed as of ${data.scope.asOf}. This includes current planning workloads, including drafts.${warningText}`, "Save closeout estimate?", "Save closeout estimate")) return;
    setBusy(true);
    setError("");
    try {
      const estimate = await saveCloseoutEstimate({ academic_year:data.scope.year, term:data.scope.term, as_of:data.scope.asOf });
      setData(previous => previous ? { ...previous, estimate } : previous);
      setNotice(`Closeout estimate #${estimate.id} saved for ${estimate.academic_year} ${estimate.term}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save the closeout estimate.");
    } finally { setBusy(false); }
  };
  const backup = async () => {
    setBusy(true); setError("");
    try { const result = await createDatabaseBackup(); await loadFor(scope); setNotice(`Closeout backup created: ${result.filename}`); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to create backup."); }
    finally { setBusy(false); }
  };
  const exportAll = async () => {
    setBusy(true); setError("");
    try { await Promise.all([downloadExport("faculty-profiles", "cathedra-faculty-all-records.csv"), downloadExport("workloads", "cathedra-workloads-all-records.csv")]); setNotice("All-record CSV exports downloaded."); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to download exports."); }
    finally { setBusy(false); }
  };

  return <div className="stack-md">{actionDialog}
    <section className="hero-card compact"><div><span className="eyebrow">SEMESTER CLOSEOUT</span><h1>Prepare a term for closeout</h1><p>Review approvals, capture the planning estimate, and prepare your archive.</p></div><button className="btn secondary no-print" disabled={loading || busy} onClick={load}>Refresh</button></section>
    {error && <div className="notice error" role="alert">{error}</div>}
    {notice && <div className="notice success" role="status">{notice}</div>}
    <section className="data-card approved-filter-card no-print"><div className="approved-filter">
      <label>Academic year<input disabled={busy} value={year} placeholder="2026-2027" onChange={event => setYear(event.target.value)} /></label>
      <label>Term<select disabled={busy} value={term} onChange={event => setTerm(event.target.value as CloseoutTerm)}><option>First Semester</option><option>Second Semester</option><option>Summer</option></select></label>
      <label>Faculty status as of<input disabled={busy} type="date" value={asOf} onChange={event => setAsOf(event.target.value)} /></label>
      <div className="approved-filter-actions"><button className="btn primary" disabled={loading || busy} onClick={load}>Check term</button></div>
    </div></section>
    {loading && <PageSkeleton label="Loading semester closeout" variant="dashboard" />}
    {data && !scopeMatches && <div className="notice" role="status">Select Check term to load the changed reporting scope.</div>}
    {data && scopeMatches && <>
      <section className="metric-grid three"><div className="metric-card"><span>Approved workloads</span><strong>{data.summary.workloads}</strong></div><div className="metric-card"><span>Approved teaching cost</span><strong>{money(data.summary.term_pay)}</strong><small>From frozen approval records</small></div><div className="metric-card"><span>Closeout estimate</span><strong>{data.estimate ? "Saved" : "To capture"}</strong></div></section>
      <section className="data-card"><div className="section-heading"><div><h2>{data.scope.year} · {data.scope.term}</h2><p>{data.estimate ? `Closeout estimate #${data.estimate.id} retained with its original figures.` : "Current planning figures can include unapproved workloads. Review before capture."}</p></div>{data.estimate && <Link className="btn secondary" to={`/reports/saved-estimates/${data.estimate.id}`}>View saved estimate</Link>}</div>
        {!data.estimate && <><div className="metric-grid three"><div className="metric-card"><span>Period salary</span><strong>{money(data.projection.total_period_salary)}</strong></div><div className="metric-card"><span>Planning teaching cost</span><strong>{money(data.projection.teaching_cost.total_term_pay)}</strong></div><div className="metric-card"><span>Combined planning estimate</span><strong>{money(data.projection.combined_period_estimate)}</strong></div></div>{data.projection.warnings.length > 0 && <details><summary>{data.projection.warnings.length} coverage warnings</summary><ul>{data.projection.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}</>}
      </section>
      <section className="data-card"><h2>Archive checklist</h2><div className="table-scroll"><table><thead><tr><th>Step</th><th>Status</th><th className="no-print">Action</th></tr></thead><tbody>
        <tr><td>Review approved workloads</td><td>{data.summary.workloads} approved records</td><td className="no-print"><Link className="btn secondary" to={`/reports/workload?${new URLSearchParams({academic_year:data.scope.year,term:data.scope.term})}`}>Open summary</Link></td></tr>
        <tr><td>Save the closeout planning estimate</td><td>{data.estimate ? `Saved as #${data.estimate.id}` : "Awaiting administrator capture"}</td><td className="no-print">{data.estimate ? <Link className="btn secondary" to={`/reports/saved-estimates/${data.estimate.id}`}>View / Print</Link> : <button className="btn primary" disabled={busy} onClick={() => void capture()}>{busy ? "Working…" : "Save closeout estimate"}</button>}</td></tr>
        <tr><td>Create a current database backup</td><td>{data.status.backup_count} local backups · check latest date</td><td className="no-print"><button className="btn secondary" disabled={busy} onClick={() => void backup()}>Create backup</button></td></tr>
        <tr><td>Export all office records</td><td>All years and terms</td><td className="no-print"><button className="btn secondary" disabled={busy} onClick={() => void exportAll()}>Export all records</button></td></tr>
      </tbody></table></div></section>
    </>}
  </div>;
}
