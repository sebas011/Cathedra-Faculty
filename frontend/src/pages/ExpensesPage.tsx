import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import useProjectionScope from "../hooks/useProjectionScope";
import TeachingCostBreakdown from "../components/TeachingCostBreakdown";
import ProjectionPeriodControls from "../components/ProjectionPeriodControls";
import SectionNav from "../components/SectionNav";
import PageSkeleton from "../components/PageSkeleton";
import { useDirectoryScroll, useDirectoryValue } from "../hooks/useDirectoryMemory";

import { confirmNoTeaching, downloadMonthlySalaryProjection, getMonthlySalaryProjection, getProjectionReadiness, removeNoTeachingConfirmation, saveProjection } from "../api";
import type { College, MonthlySalaryProjection, ProjectionReadiness } from "../types";

const colleges: { code: College; name: string }[] = [
  { code: "CAS", name: "College of Arts and Sciences" },
  { code: "COEd", name: "College of Education" },
  { code: "CBMA", name: "College of Business and Management Accountancy" },
  { code: "COE", name: "College of Engineering" },
  { code: "COF", name: "College of Fisheries" },
  { code: "CIT", name: "College of Industrial Technology" },
  { code: "CCS", name: "College of Computer Studies" },
  { code: "CCJ", name: "College of Criminal Justice" },
];

const peso = (value: number) =>
  new Intl.NumberFormat("en-PH", {
    style: "currency",
    currency: "PHP",
    maximumFractionDigits: 2,
  }).format(value);
const pageSize = 50;

export default function ExpensesPage({ planning = false }: { planning?: boolean }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const view = ["summary","calculations","checks"].includes(params.get("view") || "") ? params.get("view") : "summary";
  const [college, setCollege] = useState(params.get("college") || "");
  const [employmentStatus, setEmploymentStatus] = useState(params.get("status") || "");
  const [asOf, setAsOf] = useState(params.get("as_of") || "");
  const [search, setSearch] = useDirectoryValue<string>("expenses:search", "");
  const [page, setPage] = useDirectoryValue<number>("expenses:page", 1);
  const requestId = useRef(0);
  const { period, setPeriod, academicYear, setAcademicYear, term, setTerm, scopeReady, scopeNotice, saving, useActive } = useProjectionScope(!planning || params.get("active") === "1");
  const [data, setData] = useState<MonthlySalaryProjection | null>(null);
  const [readiness, setReadiness] = useState<ProjectionReadiness | null>(null);
  const [readinessError, setReadinessError] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useDirectoryScroll("expenses", !planning && !loading && !error);
  const [exporting, setExporting] = useState(false);
  const [savingSnapshot, setSavingSnapshot] = useState(false);
  const [confirmationBusy, setConfirmationBusy] = useState<number | null>(null);
  const [confirmationError, setConfirmationError] = useState("");
  const scopeQuery = new URLSearchParams({ college, status: employmentStatus, ...(asOf ? {as_of: asOf} : {}) }).toString();
  const accessDenied = error === "Administrator access is required for this action.";
  const matchingRecords = useMemo(() => data?.records.filter(record => planning || `${record.faculty_name} ${record.college} ${record.department} ${record.rank}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())).sort((left, right) => left.faculty_name.localeCompare(right.faculty_name) || left.faculty_id - right.faculty_id) ?? [], [data, planning, search]);
  const totalPages = Math.max(1, Math.ceil(matchingRecords.length / pageSize));
  const currentPage = Math.min(Math.max(1, page), totalPages);
  const visibleRecords = matchingRecords.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  useEffect(() => {
    if (!planning && data && page !== currentPage) setPage(currentPage);
  }, [planning, data, page, currentPage, setPage]);

  const loadProjection = useCallback(async () => {
    if (!scopeReady) return;
    const currentRequest = ++requestId.current;
    setData(null);
    setLoading(true);
    setError("");
    setReadiness(null);
    setReadinessError(false);
    try {
      if (!academicYear.trim()) throw new Error("Enter an academic year.");
      const projection = await getMonthlySalaryProjection(college, employmentStatus, academicYear, term, period, asOf);
      if (currentRequest !== requestId.current) return;
      setData(projection);
      void getProjectionReadiness().then((result) => { if (currentRequest === requestId.current) setReadiness(result); }).catch(() => { if (currentRequest === requestId.current) setReadinessError(true); });
    } catch (requestError) {
      if (currentRequest !== requestId.current) return;
      setData(null);
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to load the monthly salary projection.",
      );
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }, [college, employmentStatus, academicYear, term, period, asOf, scopeReady]);

  const exportProjection = async () => {
    setExporting(true);
    setError("");
    try {
      await downloadMonthlySalaryProjection(college, employmentStatus, academicYear, term, period, asOf);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to export the expense projection.");
    } finally {
      setExporting(false);
    }
  };

  const captureProjection = async () => {
    if (!data?.filters.academic_year || !window.confirm("Save this estimate as a permanent planning record? It cannot be edited later.")) return;
    setSavingSnapshot(true);
    setError("");
    try {
      const saved = await saveProjection({
        academic_year:data.filters.academic_year, term:data.filters.term,
        period:data.period, college:data.filters.college,
        employment_status:data.filters.employment_status, as_of:data.status_as_of,
      });
      navigate(`/reports/saved-estimates/${saved.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save this estimate.");
    } finally {
      setSavingSnapshot(false);
    }
  };

  const updateNoTeaching = async (facultyId: number, remove: boolean) => {
    if (!data?.overload_coverage || !data.filters.academic_year || !data.filters.term || !["First Semester", "Second Semester"].includes(data.filters.term)) return;
    const selectedPeriod = { academic_year: data.filters.academic_year, term: data.filters.term as "First Semester" | "Second Semester" };
    setConfirmationBusy(facultyId);
    setConfirmationError("");
    try {
      if (remove) await removeNoTeachingConfirmation(facultyId, selectedPeriod);
      else await confirmNoTeaching(facultyId, selectedPeriod);
      await loadProjection();
    } catch (requestError) {
      setConfirmationError(requestError instanceof Error ? requestError.message : "Unable to update the semester confirmation.");
    } finally {
      setConfirmationBusy(null);
    }
  };

  useEffect(() => {
    void loadProjection();
    return () => { requestId.current += 1; };
  }, [loadProjection]);

  if (accessDenied) {
    return (
      <div className="stack-md expenses-page">
        <section className="hero-card compact">
          <div>
            <span className="eyebrow">EXPENSES PROJECTION</span>
            <h1>Administrator access required</h1>
            <p>Monthly salary planning details are available to Cathedra administrators only.</p>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="stack-md expenses-page">
      <section className="hero-card compact">
        <div>
          <span className="eyebrow">EXPENSES PROJECTION</span>
          <h1>{planning ? "Salary & Teaching Report" : "Faculty Expenses Projection"}</h1>
          <p>{planning ? "Selected report scope" : "Office active period"} · {academicYear || "No period selected"} · {period === "yearly" ? "Full academic year" : term} · {college || "All departments"} · {employmentStatus || "All employment statuses"}</p>
        </div>
        <div className="action-group no-print"><Link className="btn secondary" to={`${planning ? "/expenses" : "/reports/projection"}?${scopeQuery}`}>{planning ? "Faculty breakdown" : "Reports & review"}</Link>{planning && <button className="btn secondary" type="button" disabled={loading || !data || savingSnapshot} onClick={() => void captureProjection()}>{savingSnapshot ? "Saving…" : "Save estimate"}</button>}<button className="btn secondary" type="button" disabled={loading || !data} onClick={() => window.print()}>{planning ? "Print Report" : "Print Page"}</button><button className="btn primary" type="button" onClick={() => void exportProjection()} disabled={exporting || loading || !data}>{exporting ? "Preparing…" : "Export CSV"}</button></div>
      </section>

      {planning && <SectionNav label="Planning views" items={[{ value: "summary", label: "Overview" }, { value: "calculations", label: "Detailed calculations" }, { value: "checks", label: "Data checks" }]} />}
      {planning && <>
      <section className="data-card expense-filter-card">
        <div className="expense-filter-heading"><div><span className="eyebrow">PROJECTION FILTERS</span><h2>Choose report scope</h2><p>Filters affect this report only. Set the shared active semester in Settings → Office period.</p></div></div>
        <div className="projection-filter">
          <label>
            College
            <select value={college} onChange={(event) => setCollege(event.target.value)}>
              <option value="">All departments</option>
              {colleges.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.code} — {item.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Employment status
            <select
              value={employmentStatus}
              onChange={(event) => setEmploymentStatus(event.target.value)}
            >
              <option value="">All employment statuses</option>
              <option value="Full-time">Full-time</option>
              <option value="Part-time">Part-time</option>
            </select>
          </label>
          <label>Faculty status as of<input type="date" value={asOf} onChange={event => setAsOf(event.target.value)} /><small>Leave blank for today. This does not reconstruct historical payroll.</small></label>
          <ProjectionPeriodControls period={period} year={academicYear} term={term} onPeriod={setPeriod} onYear={setAcademicYear} onTerm={setTerm} useActive={() => void useActive()} saving={saving} notice={scopeNotice} />
          <div className="expense-filter-actions"><button className="btn secondary" type="button" onClick={() => { setCollege(""); setEmploymentStatus(""); void useActive(); }}>Clear filters</button><button className="btn primary" type="button" onClick={() => void loadProjection()} disabled={loading}>{loading ? "Updating…" : "Update projection"}</button></div>
        </div>
      </section>

      </>}
      {error && <div className="notice error" role="alert">{error}{!academicYear.trim() && <> <Link className="btn primary" to="/settings/office-period">Set office period</Link><span> An administrator can set the shared academic year and semester there.</span></>}</div>}
      {loading && <PageSkeleton label="Loading expenses projection" variant="table" />}

      {data && (
        <>
          {!planning && data.teaching_details.length === 0 && <div className="notice" role="status">No teaching workloads are included for the active semester, so load and overload columns cannot be calculated. Check the <Link to="/settings/office-period">office reporting period</Link> and <Link to={`/reports/projection?${scopeQuery}&view=checks`}>report checks</Link>.</div>}
          {data.provisional_status_count > 0 && <div className="notice" role="status">{data.provisional_status_count} faculty salary records need status confirmation. Potential salary cost, shown separately: {peso(data.provisional_monthly_salary_total)} monthly{data.period !== "summer" ? ` · ${peso(data.provisional_period_salary_total)} for the selected period` : ""}. These amounts are not included in confirmed salary totals. Status assessed as of {data.status_as_of}. <Link to={`/reports/projection?${scopeQuery}&view=checks`}>Review faculty</Link>.</div>}
          {data.provisional_teaching_cost.workloads > 0 && <div className="notice" role="status">{data.provisional_teaching_cost.workloads} workload{data.provisional_teaching_cost.workloads === 1 ? "" : "s"} need faculty status review. Potential teaching cost of {peso(data.provisional_teaching_cost.total_term_pay)} is separate from confirmed totals. <Link to={`/reports/projection?${scopeQuery}&view=checks`}>Review workloads</Link>.</div>}
          {!planning && <p className="table-meta">{data.warnings.length ? `${data.warnings.length} coverage notice${data.warnings.length === 1 ? "" : "s"}` : "Coverage review available"} · <Link to={`/reports/projection?${scopeQuery}&view=checks`}>Open report checks</Link></p>}
          {planning && data.warnings.length > 0 && <Link className="report-quality-link" to={`/reports/projection?${scopeQuery}&view=checks`}>{data.warnings.length} coverage checks · Open details</Link>}
          {planning && view === "calculations" && <TeachingCostBreakdown data={data} />}
          <section hidden={!planning || view !== "summary"} className="metric-grid three">
            <div className="metric-card">
              <span>{data.period === "summer" ? "Monthly salary reference" : "Monthly salary cost"}</span>
              <strong className="green">{peso(data.total_monthly_salary)}</strong>
              <small>{data.period === "summer" ? "Not included in the summer total" : "Current included Faculty Profiles"}</small>
            </div>
            <div className="metric-card">
              <span>{data.period === "summer" ? "Summer salary cost" : data.period === "semester" ? "Semester salary cost" : "Yearly salary cost"}</span>
              <strong className="green">{data.period === "summer" ? "Not included" : peso(data.total_period_salary)}</strong>
              <small>{data.period === "summer" ? "No approved summer salary-month basis" : `Monthly salary estimate × ${data.salary_months} months`}</small>
            </div>
            <div className="metric-card">
              <span>{data.period === "summer" ? "Summer teaching estimate" : `Combined ${data.period} estimate`}</span>
              <strong className="green">{peso(data.combined_period_estimate)}</strong>
              <small>{data.period === "summer" ? "Teaching compensation only" : "Salary plus teaching cost for this period"}</small>
            </div>
            <div className="metric-card">
              <span>Included faculty</span>
              <strong>{data.included_count}</strong>
              <small>Profiles with a valid monthly salary</small>
            </div>
            <div className="metric-card">
              <span>Profiles to complete</span>
              <strong className={data.incomplete_count ? "amber" : "green"}>
                {data.incomplete_count}
              </strong>
              <small>Excluded from the estimate</small>
            </div>
            <div className="metric-card">
              <span>Department totals</span>
              <strong>{data.college_totals.filter((item) => item.included_count > 0 || item.term_teaching_cost > 0).length}</strong>
              <small>Departments with included profiles</small>
            </div>
          </section>

          <section hidden={!planning || view !== "summary"} className="data-card">
            <div className="section-heading">
              <div>
                <span className="eyebrow">TEACHING COMPENSATION</span>
                <h2>Current workload cost snapshot</h2>
                <p>Separate from regular monthly salary costs and based on the saved Compensation Rules.</p>
              </div>
              <div className="action-group"><Link className="btn secondary" to="/expenses?view=faculty">Faculty breakdown</Link><Link className="btn secondary" to="/settings/compensation">Compensation Rules</Link></div>
            </div>
            <section className="metric-grid three">
              <div className="metric-card"><span>Included workloads</span><strong>{data.teaching_cost.workloads}</strong><small>{data.filters.academic_year} · {data.filters.term || "All terms, including summer"}</small></div>
              <div className="metric-card"><span>Period teaching cost</span><strong>{peso(data.teaching_cost.total_term_pay)}</strong><small>Uses configured semester weeks</small></div>
              <div className="metric-card"><span>Terms to configure</span><strong className={data.teaching_cost.unconfigured_term_count ? "amber" : "green"}>{data.teaching_cost.unconfigured_term_count}</strong><small>Excluded from term total</small></div>
            </section>
          </section>

          <section hidden={!planning || view !== "summary"} className="data-card">
            <div className="section-heading">
              <div>
                <span className="eyebrow">MANAGEMENT COST REPORT</span>
                <h2>{data.period === "summer" ? "Summer teaching cost by college" : "Salary and teaching cost by college"}</h2>
                <p>{data.period === "summer" ? "Salary is not included; no summer salary-month basis is approved." : `Salary for ${data.salary_months} months plus teaching cost for the same period.`}</p>
              </div>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Department</th>
                    <th>Included faculty</th>
                    <th className="right">Period salary cost</th>
                    <th className="right">Period teaching cost</th>
                    <th className="right">Combined estimate</th>
                  </tr>
                </thead>
                <tbody>
                  {data.college_totals.map((item) => (
                    <tr key={item.college}>
                      <td>{item.college}</td>
                      <td>{item.included_count}</td>
                      <td className="right"><strong>{data.period === "summer" ? "Not included" : peso(item.monthly_salary_total * data.salary_months)}</strong></td>
                      <td className="right">{peso(item.term_teaching_cost)}</td>
                      <td className="right"><strong>{peso(item.combined_estimate)}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {planning && view === "checks" && data.warnings.length > 0 && <section className="data-card"><div className="section-heading"><div><span className="eyebrow">REPORT COVERAGE</span><h2>Items affecting this estimate</h2></div></div><ul className="report-coverage-list">{data.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></section>}
          {planning && view === "checks" && (data.provisional_records.length > 0 || data.provisional_teaching_details.length > 0) && <section className="data-card"><div className="section-heading"><div><span className="eyebrow">FACULTY STATUS REVIEW</span><h2>Potential costs outside confirmed totals</h2><p>Open a faculty profile to confirm status or a workload to review its period. These amounts do not alter approved workload history.</p></div></div>
            {data.provisional_records.length > 0 && <div className="table-scroll" role="region" aria-label="Provisional faculty salary records" tabIndex={0}><table><thead><tr><th scope="col">Faculty member</th><th scope="col">Status</th><th scope="col">Effective date</th><th scope="col" className="right">Potential monthly salary</th></tr></thead><tbody>{data.provisional_records.map(item => <tr key={item.faculty_id}><td><Link to={`/faculty-profiles/${item.faculty_id}`}>{item.faculty_name}</Link></td><td>{item.service_status}</td><td>{item.status_effective_date || "To verify"}</td><td className="right">{peso(item.monthly_salary)}</td></tr>)}</tbody></table></div>}
            {data.provisional_teaching_details.length > 0 && <div className="table-scroll" role="region" aria-label="Provisional teaching workloads" tabIndex={0}><table><thead><tr><th scope="col">Faculty member</th><th scope="col">Workload period</th><th scope="col">Faculty status</th><th scope="col" className="right">Potential period teaching cost</th><th scope="col" className="right">Action</th></tr></thead><tbody>{data.provisional_teaching_details.map(item => <tr key={item.workload_id}><td><Link to={`/faculty-profiles/${item.faculty_id}`}>{item.faculty_name}</Link></td><td>{item.term}</td><td>{item.faculty_status}{item.status_effective_date ? ` · ${item.status_effective_date}` : ""}</td><td className="right">{item.term_pay === null ? "Weeks not configured" : peso(item.term_pay)}</td><td className="right"><Link to={`/workload/${item.workload_id}`}>Review workload</Link></td></tr>)}</tbody></table></div>}
          </section>}
          {planning && view === "checks" && <section className="data-card"><div className="section-heading"><div><span className="eyebrow">OVERLOAD COVERAGE</span><h2>Semester records behind the budget comparison</h2></div></div>
            {data.overload_coverage ? <>
              <p className="table-meta">{data.overload_coverage.included_workloads} of {data.overload_coverage.regular_workloads} regular-faculty workloads included · {data.overload_coverage.missing_workloads} faculty without a workload to confirm · {data.overload_coverage.confirmed_not_teaching} confirmed not teaching · {data.overload_coverage.excluded_workloads} excluded · {data.overload_coverage.missing_rates} missing rates · {data.overload_coverage.missing_weeks} missing teaching-week settings</p>
              {data.overload_coverage.provisional ? <p className="notice" role="status">The budget difference is provisional until these coverage items are reviewed.</p> : <p className="notice" role="status">No structural overload coverage gaps found in saved records. This remains a planning estimate, not verified payroll.</p>}
              {confirmationError && <p className="notice error" role="alert">{confirmationError}</p>}
              {data.overload_coverage.issues.length > 0 && <div className="table-scroll"><table><thead><tr><th>Faculty member</th><th>Coverage item</th><th className="right">Action</th></tr></thead><tbody>{data.overload_coverage.issues.map((item) => <tr key={`${item.reason}-${item.faculty_id}-${item.workload_id}`}><td>{item.faculty_name}</td><td>{item.reason}</td><td className="right"><Link className="btn secondary" to={item.action_path}>Review</Link>{item.workload_id === null && <button type="button" className="btn secondary" disabled={confirmationBusy !== null} onClick={() => void updateNoTeaching(item.faculty_id, false)}>{confirmationBusy === item.faculty_id ? "Saving…" : "Confirm not teaching"}</button>}</td></tr>)}</tbody></table></div>}
              {data.overload_coverage.confirmations.length > 0 && <div className="table-scroll"><h3>Confirmed not teaching this semester</h3><table><thead><tr><th>Faculty member</th><th>Confirmed by</th><th>Date</th><th className="right">Action</th></tr></thead><tbody>{data.overload_coverage.confirmations.map((item) => <tr key={item.faculty_id}><td>{item.faculty_name}</td><td>{item.confirmed_by}</td><td>{new Date(item.confirmed_at).toLocaleDateString()}</td><td className="right"><button type="button" className="btn secondary" disabled={confirmationBusy !== null} onClick={() => void updateNoTeaching(item.faculty_id, true)}>{confirmationBusy === item.faculty_id ? "Saving…" : "Undo confirmation"}</button></td></tr>)}</tbody></table></div>}
              {data.overload_coverage.missing_weeks > 0 && <p>Teaching weeks are set in <Link to="/settings/compensation">Compensation rules</Link>.</p>}
            </> : <p className="notice">Choose an unfiltered semester report to review office-wide overload coverage.</p>}
          </section>}
          {readiness && <section hidden={!planning || view !== "checks"} className="data-card"><div className="section-heading"><div><span className="eyebrow">PROJECTION READINESS</span><h2>{readiness.ready ? "Ready for planning" : "Items to complete before relying on totals"}</h2><p>{readiness.ready ? "Salary and workload information is complete for the current checks." : `${readiness.blocked_count} record issue${readiness.blocked_count === 1 ? "" : "s"} need attention.`}</p></div></div><div className="table-scroll"><table><thead><tr><th>Check</th><th>Records</th><th>What to do</th><th className="right">Action</th></tr></thead><tbody>{readiness.items.map((item) => <tr key={item.key}><td><strong>{item.title}</strong></td><td>{item.count}</td><td>{item.detail}</td><td className="right"><Link className="btn secondary" to={item.action_path}>Review</Link></td></tr>)}</tbody></table></div></section>}
          {planning && view === "checks" && readinessError && <div className="notice error" role="alert">Profile readiness checks could not load. Refresh this report before relying on its totals.</div>}

          <section hidden={!planning || view !== "calculations"} className="data-card">
            <div className="section-heading"><div><span className="eyebrow">SALARY BREAKDOWN</span><h2>Monthly cost by status and grade</h2></div></div>
            <div className="table-scroll"><table><thead><tr><th>Employment status</th><th>Included faculty</th><th className="right">Monthly salary cost</th></tr></thead><tbody>{data.employment_status_totals.map((item) => <tr key={item.label}><td>{item.label}</td><td>{item.included_count}</td><td className="right"><strong>{peso(item.monthly_salary_total)}</strong></td></tr>)}</tbody></table></div>
            <div className="table-scroll"><table><thead><tr><th>Salary grade</th><th>Included faculty</th><th className="right">Monthly salary cost</th></tr></thead><tbody>{data.salary_grade_totals.map((item) => <tr key={item.label}><td>{item.label}</td><td>{item.included_count}</td><td className="right"><strong>{peso(item.monthly_salary_total)}</strong></td></tr>)}</tbody></table></div>
          </section>

          <section hidden={planning} className="data-card expense-table-card">
            <div className="section-heading">
              <div>
                <span className="eyebrow">FACULTY BREAKDOWN</span>
                <h2>Teaching load and overload by faculty</h2><p>{academicYear} · {term} estimates. A dash means no regular-faculty workload figure is available for this period, not zero pay.</p>
              </div>
              <span className="table-meta">{data.records.length} included faculty across all pages</span>
            </div>
            <div className="toolbar directory-toolbar no-print"><div className="search-wrap"><input value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} placeholder="Search faculty, department, or program" aria-label="Search faculty expenses" /></div>{search && <button className="btn secondary" type="button" onClick={() => { setSearch(""); setPage(1); }}>Clear search</button>}</div>
            <div className="table-meta">{matchingRecords.length} matching faculty · Alphabetical · Page {currentPage} of {totalPages}</div>
            {matchingRecords.length === 0 ? (
              <div className="empty-state">{search ? "No faculty match this search." : "No faculty profiles match the selected filters."}</div>
            ) : (
              <div className="table-scroll expense-faculty-scroll" role="region" aria-label="Faculty expenses breakdown" tabIndex={0}>
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Faculty member</th>
                      <th scope="col" className="right">Regular load / week</th>
                      <th scope="col" className="right">Overload / week</th>
                      <th scope="col" className="right">Overload compensation / semester</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRecords.map((record) => (
                      <tr key={record.faculty_id}>
                        <td><Link className="faculty-profile-link" to={`/faculty-profiles/${record.faculty_id}`}><strong>{record.faculty_name}</strong></Link></td>
                        <td className="right">{record.regular_weekly_hours === null ? "—" : `${record.regular_weekly_hours.toFixed(1)} h`}</td>
                        <td className="right">{record.overload_weekly_hours === null ? "—" : `${record.overload_weekly_hours.toFixed(1)} h`}</td>
                        <td className="right">{record.regular_weekly_hours === null || record.period_overload_pay === null ? "—" : peso(record.period_overload_pay)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="form-actions no-print"><button className="btn secondary" type="button" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>Previous</button><button className="btn secondary" type="button" disabled={currentPage >= totalPages} onClick={() => setPage(currentPage + 1)}>Next</button></div>
          </section>

          <div className="report-quality"><span className="warning-chip">Planning estimate · not payroll</span><Link to="/office-guide#planning-estimates">Calculation guide</Link></div>
        </>
      )}
    </div>
  );
}
