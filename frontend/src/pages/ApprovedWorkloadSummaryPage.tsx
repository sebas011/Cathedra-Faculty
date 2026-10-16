import TableRegion from "../components/TableRegion";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import PageSkeleton from "../components/PageSkeleton";
import { getApprovedWorkloadSummary } from "../api";
import type { ApprovedWorkloadSummary } from "../types";

const terms = ["First Semester", "Second Semester", "Summer"];
const colleges = ["CAS", "COEd", "CBMA", "COE", "COF", "CIT", "CCS", "CCJ"];
const money = (value: number|null) => value === null ? "Incomplete" : new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP" }).format(value || 0);
const hours = (value: number) => `${(value || 0).toFixed(1)} h`;

export default function ApprovedWorkloadSummaryPage() {
  const [params] = useSearchParams();
  const [academicYear, setAcademicYear] = useState(params.get("academic_year") || "");
  const [term, setTerm] = useState(terms.includes(params.get("term") || "") ? params.get("term")! : "");
  const [college, setCollege] = useState("");
  const [report, setReport] = useState<ApprovedWorkloadSummary | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [applied, setApplied] = useState({ academicYear: "", term: "", college: "" });
  const requestId = useRef(0);
  const scopeChanged = academicYear !== applied.academicYear || term !== applied.term || college !== applied.college;

  const load = (scope = { academicYear, term, college }) => {
    const current = ++requestId.current;
    setLoading(true);
    setError("");
    setReport(null);
    void getApprovedWorkloadSummary(scope.academicYear, scope.term, scope.college)
      .then((result) => { if (current === requestId.current) { setReport(result); setApplied(scope); } })
      .catch((caught) => { if (current === requestId.current) setError(caught instanceof Error ? caught.message : "Unable to load the approved summary."); })
      .finally(() => { if (current === requestId.current) setLoading(false); });
  };

  useEffect(() => { load(); return () => { requestId.current += 1; }; }, []);

  return <div className="approved-summary stack-md">
    <section className="hero-card compact"><div><span className="eyebrow">FACULTY WORKLOAD</span><h1>Approved Semester Summary</h1><p>Approved amounts come from frozen records. Teaching cost follows the department allocation captured at approval.</p></div><div className="action-group no-print"><button className="btn secondary" disabled={loading || !report || scopeChanged} onClick={() => window.print()}>Print Summary</button><Link className="btn secondary" to="/workload">Back to Workloads</Link></div></section>
    <section className="data-card approved-filter-card no-print"><div className="approved-filter">
      <label>Academic year<input value={academicYear} onChange={(event) => setAcademicYear(event.target.value)} placeholder="e.g. 2026-2027" /></label>
      <label>Term<select value={term} onChange={(event) => setTerm(event.target.value)}><option value="">All terms</option>{terms.map((item) => <option key={item}>{item}</option>)}</select></label>
      <label>Teaching department<select value={college} onChange={(event) => setCollege(event.target.value)}><option value="">All departments</option>{colleges.map((item) => <option key={item}>{item}</option>)}</select></label>
      <div className="approved-filter-actions"><button className="btn primary" onClick={() => load()}>Apply Filters</button><button className="btn secondary" onClick={() => { setAcademicYear(""); setTerm(""); setCollege(""); load({ academicYear: "", term: "", college: "" }); }}>Clear</button></div>
    </div></section>
    {scopeChanged && report && <div className="notice" role="status">Filters have changed. Apply Filters to update the report before printing.</div>}
    {error && <div role="alert" className="notice error">{error}</div>}
    {loading && <PageSkeleton label="Loading approved workloads" variant="table" />}
    {report && <>
      {report.term_pay === null && <div className="notice" role="status">One or more approval records have no configured term cost. The term total is incomplete. Current compensation settings do not change frozen approval records.</div>}
      <div className="notice">Report scope: {applied.academicYear || "All academic years"} · {applied.term || "All terms"} · {applied.college || "All teaching departments"}. Workload hours describe entire approved records; costs follow the selected teaching department.</div>
      {report.allocation_warnings.map((warning, index) => <div className="notice" role="status" key={`${index}-${warning}`}>{warning}</div>)}
      <section className="metric-grid four">
        <div className="metric-card"><span>Approved workloads</span><strong>{report.workloads}</strong></div>
        <div className="metric-card"><span>Full workload hours / week</span><strong>{hours(report.weekly_hours)}</strong></div>
        <div className="metric-card"><span>Teaching cost / week</span><strong>{money(report.weekly_pay)}</strong></div>
        <div className="metric-card"><span>Term teaching cost</span><strong>{money(report.term_pay)}</strong></div>
      </section>
      <section className="data-card"><div className="section-heading"><span className="eyebrow">BY TEACHING DEPARTMENT</span><h2>Approved teaching cost</h2></div><TableRegion label="Approved workload report"><table><thead><tr><th>Teaching department</th><th>Workloads</th><th>Paid hours / week</th><th>Weekly cost</th><th>Term cost</th></tr></thead><tbody>
        {report.college_totals.length === 0 ? <tr><td colSpan={5} className="empty-table">No approved workloads match these filters.</td></tr> : report.college_totals.map((item) => <tr key={item.college}><td><strong>{item.college}</strong></td><td>{item.workloads}</td><td>{hours(item.paid_hours)}</td><td>{money(item.weekly_pay)}</td><td>{money(item.term_pay)}</td></tr>)}
      </tbody></table></TableRegion></section>
      <section className="data-card"><div className="section-heading"><span className="eyebrow">APPROVED RECORDS</span><h2>Semester workload register</h2></div><TableRegion label="Approved workload report"><table><thead><tr><th>Faculty member</th><th>Period</th><th>Full hours / overload</th><th>Teaching-department cost</th><th>Approved</th><th className="right no-print">Record</th></tr></thead><tbody>
        {report.items.length === 0 ? <tr><td colSpan={6} className="empty-table">No approved workloads match these filters.</td></tr> : report.items.map((item) => <tr key={item.workload_id}><td><strong>{item.faculty_name}</strong><br /><small>{item.rank || "—"} · Home: {item.college}{item.department ? ` · ${item.department}` : ""}</small></td><td>{item.academic_year}<br /><small>{item.term}</small></td><td>{hours(item.weekly_hours)} / {hours(item.overload_hours)}</td><td>{money(item.term_pay)}<br /><small>{item.allocation_basis}</small></td><td>{item.approved_by || "—"}<br /><small>{item.approved_at ? new Date(item.approved_at).toLocaleDateString() : "—"}</small></td><td className="right no-print"><Link className="btn secondary" to={`/workload/${item.workload_id}/approval-record`}>View Record</Link></td></tr>)}
      </tbody></table></TableRegion></section>
    </>}
  </div>;
}
