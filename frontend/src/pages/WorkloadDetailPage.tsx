import TableRegion from "../components/TableRegion";
import { Link, useParams } from "react-router-dom";
import { useRecord } from "../hooks/useRecord";
import { getWorkload } from "../api";
import ImportedOverloadNotice from "../components/ImportedOverloadNotice";
import PageSkeleton from "../components/PageSkeleton";

const hours = (value: number) => `${value.toFixed(1)} h`;
const money = (value: number | null) => value === null ? "Not configured" : new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP" }).format(value);

export default function WorkloadDetailPage() {
  const { id } = useParams();
  const { record, error, retry } = useRecord(id, getWorkload, "Unable to load workload.");
  if (error) return <div className="notice error" role="alert">{error}<div className="action-group"><button className="btn secondary" type="button" onClick={retry}>Retry</button><Link to="/workload">Back to workloads</Link></div></div>;
  if (!record) return <PageSkeleton label="Loading workload profile" />;

  return (
    <div className="stack-md workload-detail">
      <section className="hero-card workload-detail-hero">
        <div>
          <span className="eyebrow light">FACULTY WORKLOAD PROFILE</span>
          <h1>{record.faculty_name}</h1>
          <p>{record.academic_year} · {record.term} · {record.college}{record.department ? ` · ${record.department}` : ""}</p><div className="record-status-line"><span className="status-badge">{record.workflow_status}</span><span>Teaching assignments and weekly hours</span></div>
        </div>
        <div className="action-group no-print">
          <Link className="btn secondary" to="/workload">Back to Workloads</Link>
          {!["Approved", "Reviewed"].includes(record.workflow_status) && <Link className="btn primary" to={`/workload/${record.id}/edit`}>Edit Workload</Link>}
          {record.workflow_status === "Approved" && <Link className="btn primary" to={`/workload/${record.id}/approval-record`}>Approval record</Link>}
        </div>
      </section>

      <ImportedOverloadNotice record={record} />
      {["Approved", "Reviewed"].includes(record.workflow_status) && <div className="notice" role="status">This workload is {record.workflow_status.toLowerCase()}. An administrator must reopen it from the workload directory before editing.</div>}

      <section className="workload-detail-overview">
        <article><span>Preparations</span><strong>{record.preparation_count}</strong></article>
        <article><span>Total weekly hours</span><strong>{hours(record.total_weekly_hours)}</strong></article>
        <article><span>Regular load</span><strong>{hours(record.regular_weekly_hours)}</strong></article>
        <article><span>Overload</span><strong>{hours(record.overload_weekly_hours)}</strong></article>
      </section>

      <section className="data-card workload-detail-section">
        <div className="section-heading">
          <div><span className="eyebrow">TEACHING ASSIGNMENTS</span><h2>Courses and sections</h2></div>
        </div>
        <TableRegion label="Teaching assignments">
          <table>
            <thead><tr><th>Course code</th><th>Course title</th><th>Year / section</th><th className="right">Lecture hours</th><th className="right">Laboratory hours</th><th className="right">Weekly total</th></tr></thead>
            <tbody>{record.assignments.map((item) => (
              <tr key={item.id}>
                <td><strong>{item.course_code || "—"}</strong></td>
                <td>{item.course_title || "—"}</td>
                <td>{item.year_section || "—"}</td>
                <td className="right">{hours(item.lecture_hours)}</td>
                <td className="right">{hours(item.laboratory_hours)}</td>
                <td className="right"><strong>{hours(item.lecture_hours + item.laboratory_hours)}</strong></td>
              </tr>
            ))}</tbody>
          </table>
        </TableRegion>
      </section>
      <section className="data-card workload-detail-section">
        <div className="section-heading"><div><span className="eyebrow">TEACHING COMPENSATION</span><h2>Rate and teaching estimate</h2><p>Estimated teaching compensation excludes base salary. Approved figures are recorded separately in the approval record.</p></div></div>
        <div className="workload-detail-grid">
          <span>Compensation category<strong>{record.compensation_category}</strong></span>
          <span>Hourly rate<strong>{money(record.compensation_hourly_rate)}</strong></span>
          <span>Teaching weeks<strong>{record.projection_weeks || "Not configured"}</strong></span>
          <span>Estimated {record.compensation_category === "Regular Faculty" ? "overload" : "teaching"} pay / week<strong>{money(record.estimated_teaching_pay_weekly)}</strong></span>
          <span>Estimated teaching pay / term<strong>{money(record.estimated_teaching_pay_term)}</strong></span>
        </div>
        {record.estimated_teaching_pay_term === null && <p className="notice" role="status">Teaching weeks are not configured for this term. An unavailable term estimate does not mean zero teaching pay.</p>}
      </section>
      <section className="data-card workload-detail-section">
        <div className="section-heading"><div><span className="eyebrow">RECORD REVIEW</span><h2>Review and approval</h2><p>Review actions are available in the workload directory under the existing account permissions.</p></div></div>
        <div className="workload-detail-grid">
          <span>Workflow status<strong>{record.workflow_status}</strong></span>
          <span>Reviewed by<strong>{record.reviewed_by || "Not reviewed"}</strong></span>
          <span>Approved by<strong>{record.approved_by || "Not approved"}</strong></span>
        </div>
        <div className="action-group no-print"><Link className="btn secondary" to="/workload">Open workload directory</Link>{record.workflow_status === "Approved" && <Link className="btn primary" to={`/workload/${record.id}/approval-record`}>View approved figures</Link>}</div>
      </section>
      {record.remarks && <section className="workload-detail-remarks"><span className="eyebrow">REMARKS</span><p>{record.remarks}</p></section>}
    </div>
  );
}
