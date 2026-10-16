import TableRegion from "../components/TableRegion";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getSavedProjection, getSavedProjections } from "../api";
import PageSkeleton from "../components/PageSkeleton";
import type { SavedProjection, SavedProjectionSummary } from "../types";

const peso = (value: number) => new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP" }).format(value);
const capturedAt = (value: string) => new Date(value.endsWith("Z") ? value : `${value}Z`).toLocaleString("en-PH");

export default function SavedProjectionsPage() {
  const { id } = useParams();
  const [offset, setOffset] = useState(0);
  const [records, setRecords] = useState<SavedProjectionSummary[] | null>(null);
  const [selected, setSelected] = useState<SavedProjection | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [hasNext, setHasNext] = useState(false);

  useEffect(() => {
    let active = true;
    setError("");
    setRecords(null);
    setSelected(null);
    const request = id ? getSavedProjection(Number(id)) : getSavedProjections(offset, 51);
    void request.then((result) => {
      if (!active) return;
      if (Array.isArray(result)) { setHasNext(result.length > 50); setRecords(result.slice(0, 50)); }
      else setSelected(result);
    }).catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "Unable to load saved estimates."); });
    return () => { active = false; };
  }, [id, offset, revision]);

  const projection = selected?.projection;
  return <div className="stack-md">
    <section className="hero-card compact"><div><span className="eyebrow">REPORTS · SAVED ESTIMATES</span><h1>{selected ? `Estimate #${selected.id}` : "Saved planning estimates"}</h1><p>{selected ? `${selected.academic_year} · ${selected.term || "Full year"} · Saved ${capturedAt(selected.created_at)} by ${selected.created_by}` : "Permanent copies of estimates captured at a known time. These are not payroll records."}</p></div><div className="action-group no-print"><Link className="btn secondary" to={selected ? "/reports/saved-estimates" : "/reports/projection"}>{selected ? "All saved estimates" : "Current report"}</Link>{selected && <button className="btn primary" onClick={() => window.print()}>Print / Save PDF</button>}</div></section>
    {error && <div className="notice error" role="alert">{error} <button className="btn secondary" type="button" onClick={() => setRevision(value => value + 1)}>Retry</button></div>}
    {!error && !records && !selected && <PageSkeleton label="Loading saved estimates" variant="table" />}
    {records && <section className="data-card"><div className="section-heading"><div><h2>Captured reports</h2><p>Newest first. Saving a new estimate never replaces an earlier one.</p></div></div>{records.length ? <TableRegion label="Saved estimate records"><table><thead><tr><th>Saved</th><th>Period</th><th>Faculty</th><th className="right">Combined estimate</th><th>Action</th></tr></thead><tbody>{records.map(record => <tr key={record.id}><td>{capturedAt(record.created_at)}<br /><small>by {record.created_by}</small></td><td>{record.academic_year} · {record.term || "Full year"}{record.closeout && <div><span className="status-chip">Closeout</span></div>}</td><td>{record.included_count}</td><td className="right">{peso(record.combined_period_estimate)}</td><td><Link to={`/reports/saved-estimates/${record.id}`}>View saved report</Link></td></tr>)}</tbody></table></TableRegion> : <p>No estimates saved yet. Open Salary &amp; teaching and choose Save estimate when its figures are ready to retain.</p>}<div className="action-group no-print"><button className="btn secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button><span role="status">Page {Math.floor(offset / 50) + 1}</span><button className="btn secondary" disabled={!hasNext} onClick={() => setOffset(offset + 50)}>Next</button></div></section>}
    {projection && <>
      {selected?.closeout && <div className="notice" role="status">Closeout estimate for {selected.academic_year} · {selected.term}. <Link className="no-print" to={`/semester-closeout?${new URLSearchParams({academic_year:selected.academic_year,term:selected.term || ""})}`}>Open term checklist</Link></div>}
      <div className="notice" role="status">Saved planning estimate, not current data or actual payroll. Faculty salary, workload, and rules may have changed since capture. Status was assessed as of {projection.status_as_of}.</div>
      <section className="metric-grid three"><div className="metric-card"><span>Salary for period</span><strong>{peso(projection.total_period_salary)}</strong></div><div className="metric-card"><span>Teaching compensation</span><strong>{peso(projection.teaching_cost.total_term_pay)}</strong></div><div className="metric-card"><span>Combined estimate</span><strong>{peso(projection.combined_period_estimate)}</strong></div></section>
      <section className="data-card"><h2>Captured scope and coverage</h2><p>{projection.filters.college || "All departments"} · {projection.filters.employment_status || "All employment statuses"} · {projection.included_count} included faculty · {projection.salary_months} salary months</p>{projection.warnings.length ? <ul>{projection.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul> : <p>No coverage warnings at capture.</p>}</section>
      <section className="data-card"><h2>Faculty figures at capture</h2><TableRegion label="Saved estimate records"><table><thead><tr><th>Faculty member</th><th>Department</th><th className="right">Monthly salary then</th><th className="right">Overload / period</th><th>Teaching status</th></tr></thead><tbody>{projection.records.map(record => <tr key={record.faculty_id}><td>{record.faculty_name}</td><td>{record.college}</td><td className="right">{peso(record.monthly_salary)}</td><td className="right">{record.period_overload_pay == null ? "—" : peso(record.period_overload_pay)}</td><td>{record.teaching_status}</td></tr>)}</tbody></table></TableRegion></section>
    </>}
  </div>;
}
