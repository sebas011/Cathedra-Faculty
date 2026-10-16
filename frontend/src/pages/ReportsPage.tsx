import TableRegion from "../components/TableRegion";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import PageSkeleton from "../components/PageSkeleton";
import { getActiveProjectionPeriod, getCurrentUser, getFacultyProfiles, getMonthlySalaryProjection, getVerificationQueue, getWorkloadSummary } from "../api";
import type { MonthlySalaryProjection, VerificationQueue, WorkloadSummary } from "../types";

type OverallReport = { faculty: number; workload: WorkloadSummary; projection: MonthlySalaryProjection | null; verification: VerificationQueue | null; generated: string };
const peso = (value: number) => new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP" }).format(value);

export default function ReportsPage() {
  const admin = getCurrentUser()?.role === "admin";
  const [data, setData] = useState<OverallReport | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setData(null); setError("");
    void (async () => {
      try {
        const [faculty, workload] = await Promise.all([getFacultyProfiles(), getWorkloadSummary()]);
        const period = admin ? await getActiveProjectionPeriod() : null;
        const projection = period ? await getMonthlySalaryProjection("", "", period.academic_year, period.term, "semester") : null;
        const verification = await getVerificationQueue().catch(() => null);
        if (active) setData({ faculty: faculty.total, workload, projection, verification, generated: new Date().toLocaleString("en-PH") });
      } catch (caught) { if (active) setError(caught instanceof Error ? caught.message : "Unable to load the overall report."); }
    })();
    return () => { active = false; };
  }, [admin, revision]);
  return <div className="stack-md overall-report">
    <section className="hero-card compact"><div><span className="eyebrow">CATHEDRA REPORTS</span><h1>Overall office report</h1>{data && <p>Generated: {data.generated}</p>}</div><div className="action-group no-print"><button className="btn secondary" onClick={() => setRevision(value => value + 1)}>Refresh report</button><button className="btn primary" disabled={!data || !!error} onClick={() => window.print()}>Print / Save PDF</button></div></section>
    {error && <div className="notice error" role="alert">{error} Refresh the report to retry. No incomplete report is available for printing.</div>}
    {!data && !error && <PageSkeleton label="Preparing the overall report" variant="dashboard" />}
    {data && <>
      <div className="report-quality"><span className="warning-chip">Planning report · not payroll</span><Link to="/verification">{data.verification ? `${data.verification.total} records need verification` : "Verification status unavailable"}</Link></div>
      <section className="data-card workspace-card"><h2>Office record coverage</h2><p>All saved records, across all academic years. Workload records are not unique faculty counts.</p><div className="metric-grid three"><div className="metric-card"><span>Faculty profiles</span><strong>{data.faculty}</strong></div><div className="metric-card"><span>Workload records</span><strong>{data.workload.workloads}</strong></div><div className="metric-card"><span>Teaching assignments</span><strong>{data.workload.assignments}</strong></div></div></section>
      {data.projection ? <section className="data-card workspace-card"><div className="section-heading"><div><h2>Active-semester salary & teaching estimate</h2><p>{data.projection.filters.academic_year} · {data.projection.filters.term} · All departments · {data.projection.salary_months} salary months</p></div><Link className="btn secondary no-print" to="/reports/projection">Detailed cost report</Link></div><TableRegion label="Office report"><table><thead><tr><th>Salary estimate</th><th>Teaching compensation</th><th>Combined estimate</th></tr></thead><tbody><tr><td>{peso(data.projection.total_period_salary)}</td><td>{peso(data.projection.teaching_cost.total_term_pay)}</td><td>{peso(data.projection.combined_period_estimate)}</td></tr></tbody></table></TableRegion>
        <h3>By department</h3><TableRegion label="Office report"><table><thead><tr><th>Department</th><th>Included salary records</th><th>Period salary</th><th>Teaching cost</th><th>Combined estimate</th></tr></thead><tbody>{data.projection.college_totals.map(item => <tr key={item.college}><td>{item.college}</td><td>{item.included_count}</td><td>{peso(item.monthly_salary_total * data.projection!.salary_months)}</td><td>{peso(item.term_teaching_cost)}</td><td>{peso(item.combined_estimate)}</td></tr>)}</tbody></table></TableRegion>
        {data.projection.warnings.length > 0 && <Link className="report-quality-link" to="/reports/projection?view=checks&active=1">{data.projection.warnings.length} coverage checks · Open details</Link>}
      </section> : <div className="notice">{admin ? <>Set an active semester in <Link to="/settings/office-period">Settings → Office period</Link> to include salary estimates.</> : "Salary estimates are available to administrators only."}</div>}
    </>}
  </div>;
}
