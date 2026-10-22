import { useEffect, useId, useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { getCurrentUser } from "../api";
import { canonicalGoogleSheetUrl, configureGoogleSheets, disconnectGoogleSheets, downloadGoogleSheetsGuide, getGoogleSheetsStatus, testGoogleSheetsConnection, updateGoogleSheet } from "../api/googleSheets";
import type { GoogleSheetsStatus } from "../api/googleSheets";
import { useActionDialog } from "../hooks/useActionDialog";
import "../google-sheets.css";

type Operation = "load" | "save" | "test" | "confirm-sync" | "sync" | "confirm-disconnect" | "disconnect" | "guide";
const operationMessage: Record<Operation, string> = {
  load: "Loading the saved Google Sheets connection…",
  save: "Saving the connection settings…",
  test: "Checking access to the Google Sheet…",
  "confirm-sync": "Waiting for your confirmation to update the Google Sheet.",
  sync: "Updating the Google Sheet. Keep this page open until the result appears.",
  "confirm-disconnect": "Waiting for your confirmation to disconnect Google Sheets.",
  disconnect: "Removing the saved connection…",
  guide: "Downloading the setup guide…",
};
const keyLimit = 64 * 1024;
const includedData = ["Overview", "Faculty", "Workloads", "Assignments", "Approved Workloads", "Cost Settings", "Qualification Draft", "Salary Projection", "Teaching Projection", "Saved Estimates", "Overload Budgets", "No Teaching"];
const errorMessage = (caught: unknown, fallback: string) => caught instanceof Error ? caught.message : fallback;
const updatedDate = (value: string | null) => {
  if (!value || Number.isNaN(new Date(value).getTime())) return "No successful update yet";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
};

export default function GoogleSheetsCard() {
  return getCurrentUser()?.role === "admin" ? <AdminGoogleSheetsCard /> : null;
}

function AdminGoogleSheetsCard() {
  const identity = useId();
  const { confirmAction, actionDialog } = useActionDialog();
  const [status, setStatus] = useState<GoogleSheetsStatus | null>(null);
  const [operation, setOperation] = useState<Operation | null>("load");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [spreadsheetUrl, setSpreadsheetUrl] = useState("");
  const [keyEmail, setKeyEmail] = useState("");
  const [readingKey, setReadingKey] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const credential = useRef("");
  const fileReader = useRef<FileReader | null>(null);
  const readingKeyRef = useRef(false);
  const keyVersion = useRef(0);
  const mounted = useRef(false);
  const inFlight = useRef(true);
  const busy = operation !== null;
  const sheetLink = canonicalGoogleSheetUrl(status?.spreadsheet_url ?? null);

  const clearCredential = () => {
    keyVersion.current += 1;
    const reader = fileReader.current;
    fileReader.current = null;
    if (reader?.readyState === FileReader.LOADING) reader.abort();
    credential.current = "";
    readingKeyRef.current = false;
    if (fileInput.current) fileInput.current.value = "";
    if (mounted.current) { setKeyEmail(""); setReadingKey(false); }
  };

  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    void getGoogleSheetsStatus().then(result => {
      if (!cancelled) setStatus(result);
    }).catch(caught => {
      if (!cancelled) setError(errorMessage(caught, "Unable to read the Google Sheets connection."));
    }).finally(() => {
      if (!cancelled) { inFlight.current = false; setOperation(null); }
    });
    return () => {
      cancelled = true;
      mounted.current = false;
      keyVersion.current += 1;
      credential.current = "";
      readingKeyRef.current = false;
      const reader = fileReader.current;
      fileReader.current = null;
      if (reader?.readyState === FileReader.LOADING) reader.abort();
      if (fileInput.current) fileInput.current.value = "";
    };
  }, []);

  const begin = (next: Operation) => {
    if (inFlight.current || readingKeyRef.current) return false;
    inFlight.current = true;
    if (next !== "save") clearCredential();
    setOperation(next); setError(""); setNotice("");
    return true;
  };
  const finish = () => {
    inFlight.current = false;
    if (mounted.current) setOperation(null);
  };
  const recoverStatus = async () => {
    try { const next = await getGoogleSheetsStatus(); if (mounted.current) setStatus(next); }
    catch { /* Keep the original operation error visible if the status refresh also fails. */ }
  };
  const toggleForm = () => {
    if (inFlight.current) return;
    clearCredential(); setError(""); setNotice("");
    if (!formOpen) setSpreadsheetUrl(sheetLink ?? "");
    setFormOpen(!formOpen);
  };
  const chooseKey = (event: ChangeEvent<HTMLInputElement>) => {
    if (inFlight.current || readingKeyRef.current) return;
    const file = event.target.files?.[0];
    clearCredential(); setError(""); setNotice("");
    if (!file) return;
    if (file.size > keyLimit) { setError("Choose a Google service account JSON key file no larger than 64 KiB."); return; }
    const version = keyVersion.current;
    const reader = new FileReader();
    fileReader.current = reader; readingKeyRef.current = true; setReadingKey(true);
    reader.onload = () => {
      if (!mounted.current || version !== keyVersion.current) return;
      fileReader.current = null;
      try {
        const text = typeof reader.result === "string" ? reader.result : "";
        const key: unknown = JSON.parse(text);
        if (typeof key !== "object" || key === null || !("type" in key) || key.type !== "service_account" || !("client_email" in key) || typeof key.client_email !== "string" || !/^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.iam\.gserviceaccount\.com$/.test(key.client_email) || key.client_email.length > 254 || !("private_key" in key) || typeof key.private_key !== "string" || !key.private_key.trim()) throw new Error("Invalid key");
        credential.current = text; readingKeyRef.current = false; setKeyEmail(key.client_email); setReadingKey(false);
      } catch {
        clearCredential(); setError("Choose a valid service account JSON key downloaded from Google Cloud.");
      }
    };
    reader.onerror = () => {
      if (!mounted.current || version !== keyVersion.current) return;
      clearCredential(); setError("The key file could not be read. Choose the JSON file again.");
    };
    try { reader.readAsText(file); }
    catch { clearCredential(); setError("The key file could not be read. Choose the JSON file again."); }
  };
  const saveConnection = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (inFlight.current || readingKeyRef.current) return;
    const url = canonicalGoogleSheetUrl(spreadsheetUrl.trim());
    if (!url) { clearCredential(); setError("Enter a Google Sheet link beginning with https://docs.google.com/spreadsheets/d/."); return; }
    if (!status?.configured && !credential.current) { setError("Choose the service account JSON key file before saving this connection."); return; }
    if (!begin("save")) return;
    try {
      const pending = configureGoogleSheets(url, credential.current || null);
      clearCredential();
      const next = await pending;
      if (mounted.current) { setStatus(next); setSpreadsheetUrl(canonicalGoogleSheetUrl(next.spreadsheet_url) ?? ""); setFormOpen(false); setNotice("Connection saved. Test the connection, then update the Google Sheet when ready. No sheet data was changed."); }
    } catch (caught) {
      if (mounted.current) setError(errorMessage(caught, "Unable to save the Google Sheets connection."));
    } finally { clearCredential(); finish(); }
  };
  const testConnection = async () => {
    if (!status?.configured || !begin("test")) return;
    try {
      const next = await testGoogleSheetsConnection();
      if (mounted.current) { setStatus(next); setNotice(next.message || "Connection verified. No sheet data was changed."); }
    } catch (caught) { if (mounted.current) setError(errorMessage(caught, "Unable to verify the Google Sheets connection.")); }
    finally { finish(); }
  };
  const sync = async () => {
    if (!status?.configured || !status.ready || !status.spreadsheet_id || !begin("confirm-sync")) return;
    const spreadsheetId = status.spreadsheet_id;
    try {
      const confirmed = await confirmAction("Send the current faculty profiles, workloads, approvals and financial summaries, including salary information, to the connected Google Sheet? Cathedra will replace its own Cathedra tabs. Other tabs will be kept. Anyone with access to the sheet may see this information.", "Update Google Sheet?", "Update Google Sheet");
      if (!confirmed || !mounted.current) return;
      setOperation("sync");
      const next = await updateGoogleSheet(spreadsheetId);
      if (mounted.current) { setStatus(next); setNotice(next.message || next.last_message || "Google Sheet updated successfully."); }
    } catch (caught) {
      if (mounted.current) setError(errorMessage(caught, "The Google Sheet update was not confirmed. Check the sheet before retrying."));
      await recoverStatus();
    } finally { finish(); }
  };
  const disconnect = async () => {
    if (!status?.configured || !begin("confirm-disconnect")) return;
    try {
      const confirmed = await confirmAction("Remove the saved Google Sheets connection and its service account key from this computer? The Google Sheet and its existing data will be kept.", "Disconnect Google Sheet?", "Disconnect");
      if (!confirmed || !mounted.current) return;
      setOperation("disconnect");
      const next = await disconnectGoogleSheets();
      if (mounted.current) { setStatus(next); clearCredential(); setFormOpen(false); setSpreadsheetUrl(""); setNotice("Google Sheets disconnected. The sheet and its data were kept."); }
    } catch (caught) { if (mounted.current) setError(errorMessage(caught, "Unable to disconnect Google Sheets.")); }
    finally { finish(); }
  };
  const downloadGuide = async () => {
    if (!begin("guide")) return;
    try { await downloadGoogleSheetsGuide(); if (mounted.current) setNotice("Google Sheets setup guide downloaded."); }
    catch (caught) { if (mounted.current) setError(errorMessage(caught, "Unable to download the setup guide.")); }
    finally { finish(); }
  };
  const retryLoad = async () => {
    if (!begin("load")) return;
    try { const next = await getGoogleSheetsStatus(); if (mounted.current) setStatus(next); }
    catch (caught) { if (mounted.current) setError(errorMessage(caught, "Unable to read the Google Sheets connection.")); }
    finally { finish(); }
  };

  return <section className="maintenance-card google-sheets-card" aria-labelledby={`${identity}-title`} aria-busy={busy || readingKey}>
    {actionDialog}
    <div className="google-sheets-header"><div><span className="eyebrow">GOOGLE SHEETS</span><h2 id={`${identity}-title`}>Keep your shared sheet up to date</h2><p>Send faculty, workloads, approvals and financial summaries, including salary information. Updates run only when you choose Update Google Sheet.</p></div><span className={`health-pill ${status?.ready ? "healthy" : "pending"}`}><i />{operation === "load" ? "Loading…" : status?.configured ? status.ready ? "Connection saved" : "Connection needs attention" : "Not connected"}</span></div>
    {error && <div className="notice error" role="alert">{error}</div>}
    {notice && <div className="notice success" role="status">{notice}</div>}
    {operation && <p role="status">{operationMessage[operation]}</p>}
    {!status && error && <div className="google-sheets-actions"><button className="btn secondary" type="button" disabled={busy} onClick={() => void retryLoad()}>Retry connection status</button></div>}
    {!error && status?.last_result && status.last_result !== "success" && <div className="notice error" role="alert">{status.last_message || "The last update was not confirmed. Review the Google Sheet before retrying."}</div>}
    {status?.configured && !status.ready && !error && <div className="notice error" role="alert">The saved connection needs a valid service account key before it can update the sheet. Edit the connection and choose the JSON key again.</div>}
    {status?.configured && <dl className="google-sheets-summary"><div><dt>Connected sheet</dt><dd>{status.spreadsheet_title || "Google Sheet"}</dd></div><div><dt>Service account</dt><dd>{status.service_account_email || "Saved locally"}</dd></div><div><dt>Last successful update</dt><dd>{updatedDate(status.last_updated_at)}</dd></div></dl>}
    {!!status?.row_counts.length && <div className="google-sheets-counts" aria-label="Rows from the last successful update">{status.row_counts.map(item => <div key={item.title}><span>{item.title}</span><strong>{item.rows.toLocaleString()} {item.rows === 1 ? "row" : "rows"}</strong></div>)}</div>}
    <div className="google-sheets-actions"><button className="btn primary" type="button" disabled={!status?.configured || !status.ready || !status.spreadsheet_id || busy || readingKey} onClick={() => void sync()}>{operation === "sync" ? "Updating…" : "Update Google Sheet"}</button>{status?.configured && <button className="btn secondary" type="button" disabled={busy || readingKey} onClick={() => void testConnection()}>{operation === "test" ? "Testing…" : "Test connection"}</button>}{sheetLink && <a className="btn secondary" href={sheetLink} target="_blank" rel="noopener noreferrer">Open Google Sheet</a>}<button className="btn secondary" type="button" aria-expanded={formOpen} aria-controls={`${identity}-connection`} disabled={busy} onClick={toggleForm}>{formOpen ? "Close connection settings" : status?.configured ? "Edit connection" : "Connect Google Sheet"}</button>{status?.configured && <button className="btn secondary danger" type="button" disabled={busy || readingKey} onClick={() => void disconnect()}>{operation === "disconnect" ? "Disconnecting…" : "Disconnect"}</button>}</div>
    <details className="google-sheets-coverage"><summary>What is included in the 12 Cathedra tabs?</summary><p>Every update replaces the current contents of these Cathedra tabs. Your other tabs stay in place.</p><ul>{includedData.map(title => <li key={title}>Cathedra {title}</li>)}</ul><p>Salary and teaching projections use the current office period. Saved estimates remain separate from current projections.</p></details>
    {formOpen && <div className="google-sheets-connection" id={`${identity}-connection`}>
      <div className="google-sheets-setup"><h3>One-time setup</h3><ol><li>Enable the Google Sheets API in Google Cloud and download a service account JSON key.</li><li>Choose that key below, then share your Google Sheet with the displayed service account email as an <strong>Editor</strong>.</li><li>Save the connection and test it. Use <strong>Update Google Sheet</strong> to send your current records.</li></ol><button className="btn secondary" type="button" disabled={busy || readingKey} onClick={() => void downloadGuide()}>{operation === "guide" ? "Downloading guide…" : "Download detailed setup guide"}</button></div>
      <form onSubmit={event => void saveConnection(event)} className="google-sheets-form">
        <label htmlFor={`${identity}-url`}>Google Sheet link<input id={`${identity}-url`} type="url" autoComplete="off" required value={spreadsheetUrl} disabled={busy || readingKey} placeholder="https://docs.google.com/spreadsheets/d/…/edit" onChange={event => setSpreadsheetUrl(event.target.value)} /></label>
        <label htmlFor={`${identity}-key`}>Service account JSON key{status?.configured ? " (optional replacement)" : ""}<input ref={fileInput} id={`${identity}-key`} type="file" accept=".json,application/json" disabled={busy || readingKey} onChange={chooseKey} aria-describedby={`${identity}-key-help`} /></label>
        <p id={`${identity}-key-help`}>{status?.configured ? "Leave the key unselected to keep the saved key. " : ""}Choose the JSON key downloaded from Google Cloud (up to 64 KiB). Only its service account email is shown here.</p>
        {readingKey && <p role="status">Reading key file…</p>}
        {keyEmail && <p className="google-sheets-share" role="status">Share your Google Sheet with <strong>{keyEmail}</strong> as an <strong>Editor</strong> before testing the connection.</p>}
        <div className="google-sheets-actions"><button className="btn primary" type="submit" disabled={busy || readingKey || !spreadsheetUrl.trim() || (!status?.configured && !keyEmail)}>{operation === "save" ? "Saving connection…" : "Save connection"}</button><span className="google-sheets-save-hint">Saving connection settings does not change the Google Sheet.</span></div>
      </form>
    </div>}
    {!status?.configured && !formOpen && <p>Connect once with a Google service account. Cathedra creates and updates its own tabs while keeping your other tabs.</p>}
  </section>;
}
