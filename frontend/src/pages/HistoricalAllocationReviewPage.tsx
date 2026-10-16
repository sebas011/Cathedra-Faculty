import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getHistoricalAllocationReview } from "../api";
import PageSkeleton from "../components/PageSkeleton";
import type { HistoricalAllocationReview } from "../types";

const money = (value: number) => new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP" }).format(value);

export default function HistoricalAllocationReviewPage() {
  const [report, setReport] = useState<HistoricalAllocationReview | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true;
    setReport(null);
    setError("");
    void getHistoricalAllocationReview()
      .then((result) => { if (active) setReport(result); })
      .catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "Unable to load the review."); });
    return () => { active = false; };
  }, [revision]);

  return <div className="stack-md">
    <section className="hero-card compact"><div><span className="eyebrow">OFFICE REVIEW</span><h1>Historical teaching allocations</h1><p>Approval records that do not establish a verified teaching-college allocation. This report makes no changes to approved amounts.</p></div><div className="action-group no-print"><button className="btn secondary" onClick={() => setRevision(value => value + 1)}>Refresh</button><button className="btn secondary" disabled={!report} onClick={() => window.print()}>Print review</button></div></section>
    <div className="notice">Frozen approvals show what was approved, not which college should pay. Course codes and source files help locate original records; they do not prove a teaching college. A reopened workload may now differ from its earlier approval. Do not reassign historical costs without an office decision.</div>
    {error && <div className="notice error" role="alert">{error}</div>}
    {!report && !error && <PageSkeleton label="Checking approval history" variant="table" />}
    {report && <>
      <section className="metric-grid three"><div className="metric-card"><span>Cases needing review</span><strong>{report.count}</strong></div><div className="metric-card"><span>Decision status</span><strong>{report.count ? "Pending" : "Clear"}</strong></div><div className="metric-card"><span>Records changed</span><strong>0</strong></div></section>
      {!report.count && <section className="data-card"><h2>No historical allocation cases found</h2><p>All surviving approval revisions have a usable frozen allocation without a review warning.</p></section>}
      {report.items.map((item) => <article className="data-card workspace-card" key={item.approval_revision_id}>
        <div className="section-heading"><div><span className="eyebrow">APPROVAL #{item.approval_revision_id} · WORKLOAD #{item.workload_id}</span><h2>{item.faculty_name || "Approval snapshot unavailable"}</h2><p>{item.academic_year || "Period unknown"} · {item.term || "Term unknown"} · Current workload status: {item.current_status}</p></div><span className="notice">{item.issue}</span></div>
        <div className="metric-grid three"><div className="metric-card"><span>Home college</span><strong>{item.home_college || "Unknown"}</strong></div><div className="metric-card"><span>Paid hours / week</span><strong>{item.paid_hours == null ? "Unknown" : `${item.paid_hours.toFixed(2)} h`}</strong></div><div className="metric-card"><span>Frozen term cost</span><strong>{item.term_pay == null ? "Unknown" : money(item.term_pay)}</strong></div></div>
        <p><strong>Frozen course codes:</strong> {item.course_codes?.join(", ") || "Not available"}</p>
        <p><strong>Source files recorded at approval:</strong> {item.source_files?.join(", ") || "Not available"}</p>
        <p><strong>Approved:</strong> {item.approved_by || "Unknown"} · {item.approved_at ? new Date(item.approved_at).toLocaleString() : "Date unavailable"}</p>
        <div className="no-print"><Link className="btn secondary" to={`/workload/${item.workload_id}`}>Open current workload</Link></div>
      </article>)}
    </>}
  </div>;
}
