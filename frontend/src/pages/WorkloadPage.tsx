import { useActionDialog } from "../hooks/useActionDialog";
import { useDirectoryValue, useDirectoryScroll } from "../hooks/useDirectoryMemory";
import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import SectionNav from "../components/SectionNav";
import PageSkeleton, { SkeletonTableRows } from "../components/PageSkeleton";

import {
  deleteWorkload,
  getCurrentUser,
  getWorkloadReview,
  getWorkloads,
  downloadWorkloadReview,
  approveWorkload,
  reopenWorkload,
  reviewWorkload,
} from "../api";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import type { FacultyWorkload, WorkloadReview } from "../types";
import "../records-redesign.css";

const terms = ["First Semester", "Second Semester", "Summer"];
const displayTerm = (value: string) => value === "1st Semester" ? "First Semester" : value === "2nd Semester" ? "Second Semester" : value;
const colleges = ["CAS", "COEd", "CBMA", "COE", "COF", "CIT", "CCS", "CCJ"];
const recordInitials = (name: string) => name.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join("").toUpperCase();
const hours = (value: number | null | undefined) => {
  const safeValue = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return `${safeValue.toFixed(1)} h`;
};
const money = (value: number | null | undefined) => {
  const safeValue = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP" }).format(safeValue);
};


function getPreparationCount(record: FacultyWorkload) {
  if (Number.isFinite(record.preparation_count)) return record.preparation_count;
  return new Set(record.assignments.map((assignment) => assignment.course_code.trim().toLocaleLowerCase())).size;
}

function getRegularWeeklyHours(record: FacultyWorkload) {
  if (Number.isFinite(record.regular_weekly_hours)) return record.regular_weekly_hours;
  return getPreparationCount(record) <= 2 ? 21 : 18;
}

function getOverloadWeeklyHours(record: FacultyWorkload) {
  if (Number.isFinite(record.overload_weekly_hours)) return record.overload_weekly_hours;
  return Math.max(record.total_weekly_hours - getRegularWeeklyHours(record), 0);
}

function getEstimatedTeachingPay(record: FacultyWorkload) {
  if (Number.isFinite(record.estimated_teaching_pay_weekly)) {
    return record.estimated_teaching_pay_weekly;
  }
  return getOverloadWeeklyHours(record) * (record.compensation_hourly_rate || 0);
}


export default function WorkloadPage() {
  const { confirmAction, requestInput, actionDialog } = useActionDialog();
  const [params] = useSearchParams();
  const view = ["records","review"].includes(params.get("view") || "") ? params.get("view") : "records";
  const canDelete = getCurrentUser()?.role === "admin";
  const [records, setRecords] = useState<FacultyWorkload[]>([]);
  const [search, setSearch] = useDirectoryValue<string>("workload:search", "");
  const [academicYear, setAcademicYear] = useDirectoryValue<string>("workload:academicYear", "");
  const [term, setTerm] = useDirectoryValue<string>("workload:term", "");
  const selectedTerm = displayTerm(term);
  const [college, setCollege] = useDirectoryValue<string>("workload:college", "");
  const [error, setError] = useState("");
  const [page, setPage] = useDirectoryValue<number>("workload:page", 1); const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<Record<string, number> | null>(null);
  const [review, setReview] = useState<WorkloadReview | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [exportingReview, setExportingReview] = useState(false);
  const debouncedSearch = useDebouncedValue(search);

  const requestId = useRef(0);
  const [loading, setLoading] = useState(true);
  useDirectoryScroll("workload", !loading && !error);

  const load = async () => {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setReviewLoading(false);
    setReview(null);
    setReviewError("");
    try {
      setError("");
        const result = await getWorkloads(debouncedSearch, academicYear, term, college, page);
        if (currentRequest !== requestId.current) return;
        const lastPage = Math.max(1, Math.ceil(result.total / 50)); if (page > lastPage || page < 1) setPage(lastPage);
        setRecords(result.items); setTotal(result.total); setReview(null); setReviewError("");
        setSummary(result.summary ?? null);
        if (view === "review") {
          setReviewLoading(true);
          void getWorkloadReview(academicYear, term, college)
            .then((result) => { if (currentRequest === requestId.current) setReview(result); })
            .catch((caught) => { if (currentRequest === requestId.current) setReviewError(caught instanceof Error ? caught.message : "Unable to load workload checks."); })
            .finally(() => { if (currentRequest === requestId.current) setReviewLoading(false); });
        } else {
          setReviewLoading(false);
        }
    } catch (caughtError) {
      if (currentRequest !== requestId.current) return;
      setError(caughtError instanceof Error ? caughtError.message : "Unable to load workloads.");
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  };

  useEffect(() => { void load(); return () => { requestId.current += 1; }; }, [debouncedSearch, academicYear, term, college, page, view]);

  const removeRecord = async (record: FacultyWorkload) => {
    if (!await confirmAction(`Delete the workload for ${record.faculty_name}?`, "Delete workload?", "Delete workload")) return;
    try {
      setError("");
      await deleteWorkload(record.id, record.revision);
      await load();
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unable to delete workload.");
    }
  };

  const moveWorkflow = async (record: FacultyWorkload, action: "review" | "approve" | "reopen") => {
    try {
      setError("");
      if (action === "review") await reviewWorkload(record.id, record.revision);
      if (action === "approve") await approveWorkload(record.id, record.revision);
      if (action === "reopen") {
        const reason = await requestInput("Reopening allows changes to this workload. The reason will be retained in its history.", "Reopen workload?", "Reopen workload", "Reason for reopening");
        if (!reason) return;
        await reopenWorkload(record.id, reason, record.revision);
      }
      await load();
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unable to update workload review status.");
    }
  };

  const exportReview = async () => {
    try {
      setExportingReview(true);
      setError("");
      await downloadWorkloadReview(academicYear, term, college);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unable to export the workload review.");
    } finally {
      setExportingReview(false);
    }
  };

  if (params.get("view") === "costs") return <Navigate to="/expenses" replace />;
  if (params.get("view") === "rules") return <Navigate to="/compensation-rules" replace />;
  return (
    <div className="stack-md workload-page">{actionDialog}
      <section className="hero-card compact"><div><span className="eyebrow">FACULTY WORKLOAD</span><h1>Weekly Teaching Loads</h1><p>Plan teaching assignments, resolve exceptions, and move each workload toward approval.</p></div><div className="action-group"><Link className="btn secondary" to="/workload/approved-summary">Approved Summary</Link><Link className="btn primary" to="/workload/new">Add Workload</Link></div></section>
      <SectionNav label="Workload views" items={[{ value: "records", label: "Workload records" }, { value: "review", label: "Data checks" }]} />
      <section className="data-card record-filter-panel"><div className="section-heading"><div><h2>Filter workloads</h2><p>Choose a teaching period or college to focus the workspace.</p></div><span className="record-filter-state">{academicYear || selectedTerm || college || search ? "Filtered view" : "All records"}</span></div>
        <div className="toolbar workload-toolbar"><div className="search-wrap" hidden={view !== "records"}><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Search faculty, department, rank, or term" aria-label="Search faculty workloads" /></div><input value={academicYear} onChange={(event) => { setAcademicYear(event.target.value); setPage(1); }} placeholder="Academic year" aria-label="Filter by academic year" /><select value={selectedTerm} onChange={(event) => { setTerm(event.target.value); setPage(1); }} aria-label="Filter by term"><option value="">All terms</option>{terms.map((item) => <option key={item} value={item}>{item}</option>)}</select><select value={college} onChange={(event) => { setCollege(event.target.value); setPage(1); }} aria-label="Filter by college"><option value="">All colleges</option>{colleges.map((item) => <option key={item} value={item}>{item}</option>)}</select><button className="btn secondary" type="button" onClick={() => { setSearch(""); setAcademicYear(""); setTerm(""); setCollege(""); setPage(1); }}>Reset</button></div>
      </section>
      {error && <div className="notice error" role="alert">{error}</div>}
      {view === "review" && reviewLoading && <PageSkeleton label="Loading workload checks" variant="table" />}
      {view === "review" && reviewError && <div className="notice error" role="alert">{reviewError}<button className="btn secondary" type="button" onClick={() => void load()}>Retry checks</button></div>}
      {review && <section hidden={view !== "review"} className="data-card"><div className="section-header"><div><span className="eyebrow">WORKLOAD DATA REVIEW</span><h2>Loads and assignment exceptions</h2><p>Flags workloads above 30 weekly hours, duplicate-looking course sections, and incomplete imported course details. The regular-load comparison remains visible in the workload list.</p></div><button className="btn secondary no-print" type="button" onClick={() => void exportReview()} disabled={exportingReview}>{exportingReview ? "Preparing…" : "Export Review CSV"}</button></div><section className="metric-grid four"><div className="metric-card"><span>Reviewed workloads</span><strong>{review.workloads}</strong></div><div className="metric-card"><span>Above 30 hours</span><strong className={review.high_load_count ? "amber" : "green"}>{review.high_load_count}</strong></div><div className="metric-card"><span>With overload</span><strong className={review.overload_count ? "amber" : "green"}>{review.overload_count}</strong></div><div className="metric-card"><span>Course data issues</span><strong className={review.duplicate_assignment_count + review.incomplete_assignment_count ? "amber" : "green"}>{review.duplicate_assignment_count + review.incomplete_assignment_count}</strong></div></section>{review.items.length === 0 ? <div className="empty-state">No high-load, duplicate-section, or incomplete-course exceptions match these filters.</div> : <div className="table-scroll"><table><thead><tr><th>Faculty member</th><th>Period</th><th>Preps / regular load</th><th>Total / overload</th><th>Review flags</th><th className="right">Action</th></tr></thead><tbody>{review.items.map((item) => <tr key={item.workload_id}><td><strong>{item.faculty_name}</strong><br/><small>{item.college}</small></td><td>{item.academic_year}<br/><small>{item.term}</small></td><td>{item.preparation_count} / {hours(item.regular_weekly_hours)}</td><td>{hours(item.total_weekly_hours)} / {hours(item.overload_weekly_hours)}</td><td>{item.flags.join(" · ")}</td><td className="right"><Link className="btn secondary" to={`/workload/${item.workload_id}/edit`}>Edit</Link></td></tr>)}</tbody></table></div>}</section>}
      <section hidden={view !== "records"} className="data-card workload-table-card">
        <div className="record-table-heading"><div><span className="eyebrow">TEACHING RECORDS</span><h2>Workload register</h2></div><span className="record-count-label">{loading ? "Updating records…" : `${total.toLocaleString()} ${total === 1 ? "workload" : "workloads"}`}</span></div>
        <div className="table-meta record-table-meta"><span>{total} workloads · Page {page} of {Math.max(1, Math.ceil(total / 50))}</span><span>{[academicYear || "All academic years", selectedTerm || "All terms", college || "All colleges"].join(" · ")}</span></div>
        <p className="record-scroll-hint">Scroll the table horizontally to see all columns.</p>
        <div className="table-scroll" role="region" aria-label="Faculty workload directory" tabIndex={0}><table><thead><tr><th scope="col">Faculty member</th><th scope="col">Period</th><th scope="col">Preps</th><th scope="col">Regular load</th><th scope="col">Total / week</th><th scope="col">Overload / week</th><th scope="col">Est. pay / week</th><th scope="col">Status</th><th scope="col" className="right">Actions</th></tr></thead><tbody>
          {loading ? <SkeletonTableRows columns={9} /> : records.length === 0 ? <tr><td colSpan={9} className="empty-table"><strong>No workload records found.</strong><span>{search || academicYear || term || college ? "Try changing or clearing the filters." : "Add a weekly teaching workload to get started."}</span></td></tr> : records.map((record) => {
            const preparationCount = getPreparationCount(record);
            const regularWeeklyHours = getRegularWeeklyHours(record);
            const overloadWeeklyHours = getOverloadWeeklyHours(record);
            const estimatedTeachingPay = getEstimatedTeachingPay(record);
            const workflowStatus = record.workflow_status || "Draft";
            return <tr key={record.id}>
            <td><div className="record-identity"><span className="record-avatar" aria-hidden="true">{recordInitials(record.faculty_name)}</span><div className="person-cell"><Link className="faculty-profile-link" to={`/workload/${record.id}`}><strong>{record.faculty_name}</strong></Link><span>{record.rank || "Faculty"} · {record.college}{record.department ? ` · ${record.department}` : ""} · {record.compensation_category}</span></div></div></td>
            <td><div className="person-cell"><strong>{record.academic_year}</strong><span>{displayTerm(record.term)}</span></div></td>
            <td>{preparationCount}</td><td>{hours(regularWeeklyHours)}</td><td><strong>{hours(record.total_weekly_hours)}</strong></td><td><strong className={overloadWeeklyHours ? "amber" : "green"}>{hours(overloadWeeklyHours)}</strong></td><td><strong className={estimatedTeachingPay ? "amber" : "green"}>{money(estimatedTeachingPay)}</strong></td>
            <td><span className={`status-badge status-${workflowStatus.toLowerCase()}`}>{workflowStatus}</span></td>

            <td className="right"><div className="action-group"><Link className="btn secondary" to={`/workload/${record.id}`}>View</Link>{workflowStatus === "Approved" && <Link className="btn secondary" to={`/workload/${record.id}/approval-record`}>Approval Record</Link>}{workflowStatus !== "Approved" && workflowStatus !== "Reviewed" && <Link className="btn secondary" to={`/workload/${record.id}/edit`}>Edit</Link>}{canDelete && workflowStatus !== "Approved" && workflowStatus !== "Reviewed" && <button className="btn secondary" type="button" onClick={() => void moveWorkflow(record, "review")}>Review</button>}{canDelete && workflowStatus === "Reviewed" && <button className="btn secondary" type="button" onClick={() => void moveWorkflow(record, "approve")}>Approve</button>}{canDelete && (workflowStatus === "Reviewed" || workflowStatus === "Approved") && <button className="btn secondary" type="button" onClick={() => void moveWorkflow(record, "reopen")}>Reopen</button>}{canDelete && workflowStatus !== "Approved" && workflowStatus !== "Reviewed" && <button className="btn secondary danger" type="button" onClick={() => void removeRecord(record)}>Delete</button>}</div></td>
          </tr>;
          })}
        </tbody></table></div><div className="form-actions no-print"><button className="btn secondary" disabled={loading || !!error || page===1} onClick={()=>setPage(page-1)}>Previous</button><button className="btn secondary" disabled={loading || !!error || page>=Math.max(1,Math.ceil(total/50))} onClick={()=>setPage(page+1)}>Next</button></div>
      </section>
      {view === "records" && <details className="data-card directory-summary-details"><summary>Workload overview</summary><div className="metric-grid four" aria-label="Workload totals across all matching records"><div className="metric-card"><span>Total workloads</span><strong>{total}</strong><small>All matching records · every page</small></div><div className="metric-card"><span>Total assignments</span><strong>{summary?.assignments ?? "—"}</strong><small>Across all matching workloads</small></div><div className="metric-card"><span>Total preparations</span><strong>{summary?.preparations ?? "—"}</strong><small>Distinct subjects per workload, added together</small></div><div className="metric-card"><span>Estimated teaching pay / week</span><strong className={summary?.weekly_pay ? "amber" : "green"}>{summary ? money(summary.weekly_pay) : "—"}</strong><small>Across all matching workloads</small></div></div></details>}
    </div>
  );
}
