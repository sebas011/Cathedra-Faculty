import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getWorkload, getWorkloadApprovalHistory } from "../api";
import PageSkeleton from "../components/PageSkeleton";
import type { FacultyWorkload, WorkloadApprovalRevision } from "../types";
import "./ApprovalRecordPage.css";

const peso = (value: number) => new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP" }).format(value);
const amount = (value: unknown) => typeof value === "number" ? peso(value) : "—";
const value = (item: unknown) => item == null || item === "" ? "—" : String(item);

export default function ApprovalRecordPage() {
  const { id } = useParams();
  const [record, setRecord] = useState<FacultyWorkload | null>(null);
  const [history, setHistory] = useState<WorkloadApprovalRevision[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setRecord(null);
    setHistory([]);
    setError("");
    void Promise.all([getWorkload(Number(id)), getWorkloadApprovalHistory(Number(id))])
      .then(([workload, revisions]) => {
        if (active) {
          setRecord(workload);
          setHistory(revisions);
        }
      })
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "Unable to load approval record.");
      });
    return () => { active = false; };
  }, [id]);

  if (error) return <div className="notice error" role="alert">{error}</div>;
  if (!record) return <PageSkeleton label="Loading approval record" />;
  if (!history.length) return <div className="stack-md"><section className="hero-card compact"><div><span className="eyebrow">FACULTY WORKLOAD</span><h1>Approval Record</h1><p>This workload has not been approved yet.</p></div><Link className="btn secondary" to="/workload">Back to Workloads</Link></section></div>;

  const current = history[history.length - 1];
  const faculty = current.snapshot.faculty ?? {};
  const workload = current.snapshot.workload ?? {};

  return <div className="approval-record stack-md">
    <section className="hero-card approval-record-hero"><div><span className="eyebrow light">APPROVED WORKLOAD RECORD</span><h1>{value(faculty.name ?? record.faculty_name)}</h1><p>{value(workload.academic_year ?? record.academic_year)} · {value(workload.term ?? record.term)}</p></div><div className="action-group no-print"><button className="btn secondary" onClick={() => window.print()}>Print Record</button><Link className="btn secondary" to={`/workload/${record.id}`}>Back to Workload</Link></div></section>
    <section className="approval-audit-card"><div><span className="eyebrow">LATEST APPROVAL · REVISION #{current.id}</span><h2>Approved by {value(current.approved_by)}</h2><p>{new Date(current.approved_at).toLocaleString()}</p></div><div><span>Current status</span><strong>{record.workflow_status}</strong>{record.reopen_reason && <small>Reopened: {record.reopen_reason}</small>}</div></section>
    <section className="approval-grid"><article><span>Academic rank</span><strong>{value(faculty.rank)}</strong></article><article><span>Salary grade</span><strong>{value(faculty.salary_grade)}</strong></article><article><span>Monthly salary</span><strong>{amount(faculty.monthly_salary)}</strong></article><article><span>Estimated term cost</span><strong>{amount(workload.estimated_teaching_pay_term)}</strong></article><article><span>Preparation count</span><strong>{value(workload.preparation_count)}</strong></article><article><span>Weekly teaching hours</span><strong>{typeof workload.total_weekly_hours === "number" ? `${workload.total_weekly_hours.toFixed(1)} h` : "—"}</strong></article><article><span>Hourly rate</span><strong>{amount(workload.compensation_hourly_rate)}</strong></article><article><span>Semester weeks</span><strong>{value(workload.projection_weeks)}</strong></article></section>
    <section className="data-card"><div className="section-heading"><div><span className="eyebrow">AUDIT HISTORY</span><h2>Approval revisions</h2><p>Earlier decisions remain unchanged when a corrected approval is recorded.</p></div></div><div className="table-wrap"><table><thead><tr><th>Revision</th><th>Approved</th><th>Hourly rate</th><th>Term cost</th><th>Correction</th></tr></thead><tbody>{[...history].reverse().map((revision) => <tr key={revision.id}><td>#{revision.id}</td><td>{revision.approved_by}<br /><small>{new Date(revision.approved_at).toLocaleString()}</small></td><td>{amount(revision.snapshot.workload?.compensation_hourly_rate)}</td><td>{amount(revision.snapshot.workload?.estimated_teaching_pay_term)}</td><td>{revision.snapshot.correction_of_revision_id ? <>Supersedes #{revision.snapshot.correction_of_revision_id}<br /><small>{revision.snapshot.correction_reason || "Reason not recorded"}</small></> : "Original approval"}</td></tr>)}</tbody></table></div></section>
  </div>;
}
