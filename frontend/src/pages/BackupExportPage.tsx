import { useActionDialog } from "../hooks/useActionDialog";
import { useEffect, useState } from "react";
import { checkDatabaseIntegrity, clearSession, createDatabaseBackup, deleteDatabaseBackup, downloadDatabaseBackup, downloadExport, getCurrentUser, getMaintenanceStatus, restoreDatabase, setBackupProtection } from "../api";
import PageSkeleton from "../components/PageSkeleton";
import type { BackupResult, MaintenanceStatus } from "../types";

const formatBytes = (bytes: number) => bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
const formatDate = (value: string | null) => value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "No backup yet";
const exports = [
  { key: "faculty-profiles", title: "Faculty profiles", description: "Faculty appointments, ranks, and department information.", filename: "cathedra-faculty-profiles.csv" },
  { key: "workloads", title: "Faculty workloads", description: "Teaching loads and course assignment details.", filename: "cathedra-workloads.csv" },
] as const;

export default function BackupExportPage() {
  const { confirmAction, actionDialog } = useActionDialog();
  const [integrityBusy, setIntegrityBusy] = useState(false);
  const [integrityMessage, setIntegrityMessage] = useState("");
  const verifyIntegrity = async () => { setIntegrityBusy(true); setIntegrityMessage(""); try { const result = await checkDatabaseIntegrity(); setIntegrityMessage(`Integrity and record links verified at ${formatDate(result.checked_at)}.`); } catch (caught) { setIntegrityMessage(caught instanceof Error ? caught.message : "Verification failed."); } finally { setIntegrityBusy(false); } };
  const isAdmin = getCurrentUser()?.role === "admin";
  const [status, setStatus] = useState<MaintenanceStatus | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeExport, setActiveExport] = useState<string | null>(null);
  const [selectedBackup, setSelectedBackup] = useState("");
  const selected = status?.backups.find((item) => item.filename === selectedBackup);

  const load = async () => {
    try {
      setError("");
      const result = await getMaintenanceStatus();
      setStatus(result);
      setSelectedBackup((value) => value && result.backups.some((item) => item.filename === value) ? value : (result.backups[0]?.filename || ""));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to read database status."); }
  };
  useEffect(() => { void load(); }, []);

  const makeBackup = async () => {
    setBusy(true); setNotice(""); setError("");
    try {
      const result: BackupResult = await createDatabaseBackup();
      setNotice(`${result.filename} created (${formatBytes(result.size_bytes)}).`);
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to create database backup."); }
    finally { setBusy(false); }
  };
  const restore = async () => {
    if (!selectedBackup || !await confirmAction("Restore this backup? Cathedra will first create a safety backup of the current records. All sessions will be signed out.", "Restore backup?", "Restore backup")) return;
    setBusy(true); setNotice(""); setError("");
    try { await restoreDatabase(selectedBackup); clearSession(); window.location.assign("/login"); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to restore the selected backup."); }
    finally { setBusy(false); }
  };
  const downloadBackup = async () => {
    if (!selectedBackup) return;
    setBusy(true); setNotice(""); setError("");
    try { await downloadDatabaseBackup(selectedBackup); setNotice("Backup downloaded. Move it to a protected USB drive or another device, then keep it private."); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to download the selected backup."); }
    finally { setBusy(false); }
  };
  const deleteBackup = async () => {
    if (!selected || selected.protected !== false || !await confirmAction(`Permanently delete ${selected.filename}? This cannot be undone. Keep an off-device copy before removing a local backup.`, "Delete backup permanently?", "Delete backup")) return;
    setBusy(true); setNotice(""); setError("");
    try { await deleteDatabaseBackup(selected.filename); setNotice("The selected older backup was deleted. Protected backups were not changed."); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to delete the selected backup."); }
    finally { setBusy(false); }
  };
  const toggleProtection = async () => {
    if (!selected) return;
    if (selected.pinned && !await confirmAction("Remove this backup's manual protection? It may then be deleted by an administrator unless it is the newest backup.", "Remove backup protection?", "Unpin backup")) return;
    setBusy(true); setNotice(""); setError("");
    try {
      await setBackupProtection(selected.filename, !selected.pinned);
      setNotice(selected.pinned ? "This backup is no longer manually protected. The newest backup remains protected." : "This backup is protected from deletion.");
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to change backup protection."); }
    finally { setBusy(false); }
  };
  const exportCsv = async (key: (typeof exports)[number]["key"], filename: string) => {
    setActiveExport(key); setNotice(""); setError("");
    try { await downloadExport(key, filename); setNotice(`${filename} downloaded.`); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to export CSV."); }
    finally { setActiveExport(null); }
  };

  if (!status && !error) return <PageSkeleton label="Loading backup and export status" variant="dashboard" />;
  return <div className="stack-md maintenance-page">{actionDialog}
    <section className="hero-card compact"><div><span className="eyebrow">SYSTEM MAINTENANCE</span><h1>Backup &amp; Export</h1><p>Review local data, create a safe snapshot, restore a verified backup, or download directory data.</p></div><button className="btn secondary" type="button" onClick={() => void load()}>Refresh status</button></section>
    {error && <div className="notice error" role="alert">{error}</div>}
    {notice && <div className="notice success" role="status">{notice}</div>}
    {status?.backup_overdue && <div className="notice" role="status">No backup from the last seven days is available. Create a snapshot and keep a verified copy on protected storage outside this computer.</div>}
    {isAdmin && <div className="form-actions"><button className="btn secondary" type="button" disabled={integrityBusy || !status} onClick={() => void verifyIntegrity()}>{integrityBusy ? "Verifying…" : "Verify database integrity"}</button><span role="status">{integrityMessage}</span></div>}
    {status?.storage_warning && <div className="notice error" role="alert">This PC has limited free space. Move a verified backup to protected storage, then ask an administrator to review older local backups.</div>}
    <section className="maintenance-status-card"><div className="maintenance-status-copy"><span className="eyebrow">DATABASE STATUS</span><h2>{status?.database_status === "healthy" ? "Database connection is available" : "Checking database connection"}</h2><p>{status ? `${status.database_file} · ${formatBytes(status.database_size_bytes)}` : "Loading current database details…"}</p></div><span className={`health-pill ${status?.database_status === "healthy" ? "healthy" : "pending"}`}><i />{status?.database_status === "healthy" ? "Connected" : "Checking"}</span></section>
    <section className="maintenance-counts" aria-label="Record counts"><div><span>Faculty profiles</span><strong>{status?.faculty_profiles ?? "—"}</strong></div><div><span>Workload records</span><strong>{status?.workload_records ?? "—"}</strong></div></section>
    <section className="maintenance-grid">
      <article className="maintenance-card backup-card"><div><span className="eyebrow">LOCAL DATABASE BACKUP</span><h2>Create a timestamped snapshot</h2><p>Backups are not deleted automatically. Keep a separate protected copy before major changes.</p></div><dl><div><dt>Stored backups</dt><dd>{status?.backup_count ?? "—"}</dd></div><div><dt>Latest backup</dt><dd>{formatDate(status?.latest_backup_at ?? null)}</dd></div><div><dt>Backup storage</dt><dd>{status?.backup_storage_bytes !== undefined ? formatBytes(status.backup_storage_bytes) : "—"}</dd></div><div><dt>Free disk space</dt><dd>{status?.free_storage_bytes !== undefined ? formatBytes(status.free_storage_bytes) : "—"}</dd></div></dl><button className="btn primary" type="button" disabled={busy || !status || !isAdmin} title={!isAdmin ? "Administrator access is required" : undefined} onClick={() => void makeBackup()}>{busy ? "Working…" : "Create Backup"}</button></article>
      {isAdmin && <article className="maintenance-card backup-card"><div><span className="eyebrow">BACKUP RECOVERY &amp; TRANSFER</span><h2>Keep a second copy</h2><p>Choose a saved backup to download or restore. Downloads contain personnel records and account data; store them privately on another device. Restoring signs everyone out.</p></div><select aria-label="Backup to download or restore" value={selectedBackup} onChange={(event) => setSelectedBackup(event.target.value)} disabled={!status?.backups.length || busy}>{status?.backups.map((item) => <option key={item.filename} value={item.filename}>{formatDate(item.created_at)} · {formatBytes(item.size_bytes)}{item.protected ? " · Protected" : ""}</option>)}</select><p>{selected?.protected !== false ? "This safety, newest, or pinned backup cannot be deleted here." : "Older backups can be removed only after you confirm a protected off-device copy exists."}</p><div className="action-row"><button className="btn secondary" type="button" disabled={!selectedBackup || busy} onClick={() => void downloadBackup()}>{busy ? "Working…" : "Download Selected Backup"}</button><button className="btn secondary" type="button" disabled={!selectedBackup || busy} onClick={() => void restore()}>{busy ? "Working…" : "Restore Selected Backup"}</button><button className="btn secondary" type="button" disabled={!selected || selected.pinned === undefined || selected.filename.startsWith("cathedra-backup-before-restore-") || busy} onClick={() => void toggleProtection()}>{selected?.pinned ? "Unpin Backup" : "Pin Backup"}</button><button className="btn secondary danger" type="button" disabled={!selected || selected.protected !== false || busy} onClick={() => void deleteBackup()}>Delete Older Backup</button></div></article>}
      <article className="maintenance-card export-card"><div><span className="eyebrow">CSV EXPORTS</span><h2>Download directory data</h2><p>Exports use a simple, portable CSV format for review, reporting, or archival.</p></div><div className="export-list">{exports.map((item) => <div className="export-row" key={item.key}><div><strong>{item.title}</strong><span>{item.description}</span></div><button className="btn secondary" type="button" disabled={activeExport !== null} onClick={() => void exportCsv(item.key, item.filename)}>{activeExport === item.key ? "Preparing…" : "Download CSV"}</button></div>)}</div></article>
    </section>
  </div>;
}
