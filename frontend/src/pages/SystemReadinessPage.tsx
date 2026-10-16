import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getMaintenanceStatus } from "../api";
import PageSkeleton from "../components/PageSkeleton";
import type { MaintenanceStatus } from "../types";

const when = (value: string | null) => value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "No backup yet";
const backupIsRecent = (value: string | null) => value !== null && Date.now() - new Date(value).getTime() < 24 * 60 * 60 * 1000;

export default function SystemReadinessPage() {
  const [status, setStatus] = useState<MaintenanceStatus | null>(null);
  const [error, setError] = useState("");
  const load = () => {
    setStatus(null);
    setError("");
    void getMaintenanceStatus().then(setStatus).catch((caught) => setError(caught instanceof Error ? caught.message : "Unable to check system readiness."));
  };
  useEffect(load, []);
  const healthy = status?.database_status === "healthy";
  const recentBackup = backupIsRecent(status?.latest_backup_at ?? null);

  return <div className="stack-md">
    <section className="hero-card compact"><div><span className="eyebrow">SYSTEM READINESS</span><h1>Office Pre-flight Check</h1></div><button className="btn secondary" onClick={load}>Refresh Check</button></section>
    {error && <div className="notice error" role="alert">Readiness could not be checked: {error} Please retry before relying on this page.</div>}
    {!status ? error ? null : <PageSkeleton label="Checking the local office workspace" variant="dashboard" /> : <>
      <section className="metric-grid four">
        <div className="metric-card"><span>Database connection</span><strong className={healthy ? "green" : "amber"}>{healthy ? "Available" : "Check"}</strong><small>{status.database_file}</small></div>
        <div className="metric-card"><span>Recent local backup</span><strong className={recentBackup ? "green" : "amber"}>{recentBackup ? "Within 24 hours" : "Review"}</strong><small>{when(status.latest_backup_at)}</small></div>
        <div className="metric-card"><span>Faculty workloads</span><strong>{status.workload_records}</strong><small>Workload records stored locally</small></div>
      </section>
      <section className="data-card"><div className="section-heading"><div><span className="eyebrow">CHECKLIST</span><h2>Before you proceed</h2><p>These checks are local. A database connection and saved backup do not prove a successful off-device restore.</p></div></div><div className="table-scroll"><table><thead><tr><th>Check</th><th>Status</th><th>What to do</th><th className="right">Action</th></tr></thead><tbody>
        <tr><td><strong>Database connection</strong></td><td><span className={healthy ? "ok-chip" : "warning-chip"}>{healthy ? "Available" : "Needs attention"}</span></td><td>{healthy ? "The local database answered this check." : "Open Backup & Export and refresh the database status."}</td><td className="right"><Link className="btn secondary" to="/backup-export">Open Backups</Link></td></tr>
        <tr><td><strong>Backup age</strong></td><td><span className={recentBackup ? "ok-chip" : "warning-chip"}>{recentBackup ? "Recent" : "Review"}</span></td><td>{recentBackup ? `Latest local backup: ${when(status.latest_backup_at)}.` : "Create and download a verified backup before major changes."}</td><td className="right"><Link className="btn secondary" to="/backup-export">Create Backup</Link></td></tr>
        <tr><td><strong>Disk space</strong></td><td><span className={status.storage_warning ? "warning-chip" : "ok-chip"}>{status.storage_warning ? "Low" : "Available"}</span></td><td>{status.storage_warning ? "Move a protected copy off this PC and ask an administrator to review older backups." : "No low-storage warning was detected."}</td><td className="right"><Link className="btn secondary" to="/backup-export">Review Backups</Link></td></tr>
        <tr><td><strong>Restore rehearsal</strong></td><td><span className="warning-chip">Not recorded here</span></td><td>Confirm a recent isolated restore test separately. This page does not certify that backups were restored.</td><td className="right"><Link className="btn secondary" to="/office-guide">Open Guide</Link></td></tr>
      </tbody></table></div></section>
    </>}
  </div>;
}
