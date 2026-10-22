import { useEffect, useId, useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { getCurrentUser } from "../api";
import { canonicalGoogleSheetUrl, configureGoogleSheets, disconnectGoogleSheets, downloadGoogleSheetsGuide, getGoogleSheetsStatus, testGoogleSheetsConnection, updateGoogleSheet } from "../api/googleSheets";
import type { GoogleSheetsDestination, GoogleSheetsStatus } from "../api/googleSheets";
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
const destinations: Record<GoogleSheetsDestination, { title: string; update: string; description: string; confirmation: string; tabs: string[]; note: string }> = {
  workloads: {
    title: "Faculty Workload", update: "Update workload sheet",
    description: "Keep workload records, teaching assignments and approved workloads in their own spreadsheet.",
    confirmation: "current faculty workloads, teaching assignments and approved workload records",
    tabs: ["Overview", "Workloads", "Assignments", "Approved Workloads"],
    note: "This destination excludes salary and compensation columns.",
  },
  overload: {
    title: "Overload Projection", update: "Update overload sheet",
    description: "Keep Regular Faculty overload projections, overload budgets and teaching cost settings in their own spreadsheet.",
    confirmation: "current Regular Faculty overload projections, overload budgets and teaching cost settings, including projected overload teaching costs",
    tabs: ["Overview", "Overload Projection", "Overload Budgets", "Cost Settings"],
    note: "The projection uses the current office period and includes Regular Faculty overload only. Part-time teaching, monthly salary projections and saved estimates are excluded.",
  },
  profiles: {
    title: "Faculty Profile", update: "Update profile sheet",
    description: "Keep faculty profile records, including their recorded salary information, in their own spreadsheet.",
    confirmation: "current faculty profiles, including recorded salary information",
    tabs: ["Overview", "Faculty"],
    note: "Faculty profiles include the salary information recorded in the app.",
  },
};
const errorMessage = (caught: unknown, fallback: string) => caught instanceof Error ? caught.message : fallback;
const updatedDate = (value: string | null) => {
  if (!value || Number.isNaN(new Date(value).getTime())) return "No successful update yet";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
};

export default function GoogleSheetsCard() {
  return getCurrentUser()?.role === "admin" ? <AdminGoogleSheetsDestinations /> : null;
}

function AdminGoogleSheetsDestinations() {
  const { confirmAction, actionDialog } = useActionDialog();
  const [legacy, setLegacy] = useState<GoogleSheetsStatus | null>(null);
  const [legacyUnavailable, setLegacyUnavailable] = useState(false);
  const [legacyBusy, setLegacyBusy] = useState(false);
  const [legacyError, setLegacyError] = useState("");
  const [legacyNotice, setLegacyNotice] = useState("");
  const legacyMounted = useRef(false);
  const legacyInFlight = useRef(false);
  useEffect(() => {
    legacyMounted.current = true;
    let cancelled = false;
    void getGoogleSheetsStatus().then(result => { if (!cancelled) setLegacy(result); })
      .catch(() => { if (!cancelled) setLegacyUnavailable(true); });
    return () => { cancelled = true; legacyMounted.current = false; };
  }, []);
  const disconnectPrevious = async () => {
    if (legacyInFlight.current) return;
    legacyInFlight.current = true;
    setLegacyBusy(true); setLegacyError(""); setLegacyNotice("");
    try {
      const confirmed = await confirmAction("Remove the previous combined connection and its saved service account key from this computer? Its Google spreadsheet and all existing tabs will be kept. The three category connections will also be kept.", "Disconnect previous connection?", "Disconnect previous connection");
      if (!confirmed || !legacyMounted.current) return;
      await disconnectGoogleSheets();
      if (legacyMounted.current) {
        setLegacy(null); setLegacyUnavailable(false);
        setLegacyNotice("Previous connection removed. Its Google spreadsheet and existing tabs were kept. You can now use its link for one category if needed.");
      }
    } catch (caught) {
      if (legacyMounted.current) setLegacyError(errorMessage(caught, "Unable to disconnect the previous connection."));
    } finally {
      legacyInFlight.current = false;
      if (legacyMounted.current) setLegacyBusy(false);
    }
  };
  return <div className="google-sheets-destinations">
    {actionDialog}
    <div className="google-sheets-intro"><span className="eyebrow">GOOGLE SHEETS</span><h2>Three sheets, each with its own purpose</h2><p>Create three separate Google spreadsheets and connect a different link below for each category. You can use the same service account and JSON key for all three; share each spreadsheet with that service account as an Editor.</p><p>Each connection has its own update button and update history. Saving app records does not update the sheets automatically.</p></div>
    {(legacy?.configured || legacy?.message || legacyUnavailable) && <div className="notice google-sheets-legacy" aria-busy={legacyBusy}>
      <p role="status">{legacyUnavailable || legacy?.message && !legacy.ready ? <>The previous combined connection could not be checked. It has not been changed. The three category connections below load independently.</> : <><strong>Your previous combined connection is kept.</strong> Connect the three category sheets below. The previous connection and its sheet have not been changed, copied or updated automatically.</>}</p>
      {legacy?.message && <p>{legacy.message}</p>}
      <p>To reuse the previous spreadsheet for one category, disconnect its previous connection here first. Existing Google tabs will remain in that spreadsheet.</p>
      <button className="btn secondary" type="button" disabled={legacyBusy} onClick={() => void disconnectPrevious()}>{legacyBusy ? "Waiting for previous connection removal…" : "Disconnect previous connection"}</button>
      {legacyError && <p className="notice error" role="alert">{legacyError}</p>}
    </div>}
    {legacyNotice && <div className="notice success" role="status">{legacyNotice}</div>}
    {(["workloads", "overload", "profiles"] as const).map(destination => <GoogleSheetsDestinationCard key={destination} destination={destination} />)}
  </div>;
}

export function GoogleSheetsDestinationCard({ destination }: { destination: GoogleSheetsDestination }) {
  return getCurrentUser()?.role === "admin" ? <AdminGoogleSheetsCard key={destination} destination={destination} /> : null;
}

function AdminGoogleSheetsCard({ destination }: { destination: GoogleSheetsDestination }) {
  const content = destinations[destination];
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
    void getGoogleSheetsStatus(destination).then(result => {
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
  }, [destination]);

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
    try { const next = await getGoogleSheetsStatus(destination); if (mounted.current) setStatus(next); }
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
      const pending = configureGoogleSheets(url, credential.current || null, destination);
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
      const next = await testGoogleSheetsConnection(destination);
      if (mounted.current) { setStatus(next); setNotice(next.message || "Connection verified. No sheet data was changed."); }
    } catch (caught) { if (mounted.current) setError(errorMessage(caught, "Unable to verify the Google Sheets connection.")); }
    finally { finish(); }
  };
  const sync = async () => {
    if (!status?.configured || !status.ready || !status.spreadsheet_id || !begin("confirm-sync")) return;
    const spreadsheetId = status.spreadsheet_id;
    try {
      const confirmed = await confirmAction(`Send ${content.confirmation} to the ${content.title} spreadsheet: ${status.spreadsheet_title || "Google Sheet"} (${sheetLink || spreadsheetId})? Cathedra will replace only its own ${content.tabs.map(title => `Cathedra ${title}`).join(", ")} tabs in this spreadsheet. Other tabs will be kept. Anyone with access to this spreadsheet may see this information.`, `${content.update}?`, content.update);
      if (!confirmed || !mounted.current) return;
      setOperation("sync");
      const next = await updateGoogleSheet(spreadsheetId, destination);
      if (mounted.current) { setStatus(next); setNotice(next.message || next.last_message || "Google Sheet updated successfully."); }
    } catch (caught) {
      if (mounted.current) setError(errorMessage(caught, "The Google Sheet update was not confirmed. Check the sheet before retrying."));
      await recoverStatus();
    } finally { finish(); }
  };
  const disconnect = async () => {
    if (!status?.configured || !begin("confirm-disconnect")) return;
    try {
      const confirmed = await confirmAction(`Remove the saved ${content.title} connection and its service account key from this computer? The Google Sheet and its existing data will be kept. Your other category connections will also be kept.`, "Disconnect Google Sheet?", "Disconnect");
      if (!confirmed || !mounted.current) return;
      setOperation("disconnect");
      const next = await disconnectGoogleSheets(destination);
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
    try { const next = await getGoogleSheetsStatus(destination); if (mounted.current) setStatus(next); }
    catch (caught) { if (mounted.current) setError(errorMessage(caught, "Unable to read the Google Sheets connection.")); }
    finally { finish(); }
  };

  return <section className="maintenance-card google-sheets-card" aria-labelledby={`${identity}-title`} aria-busy={busy || readingKey}>
    {actionDialog}
    <div className="google-sheets-header"><div><span className="eyebrow">GOOGLE SHEETS</span><h2 id={`${identity}-title`}>{content.title}</h2><p>{content.description}</p></div><span className={`health-pill ${status?.ready ? "healthy" : "pending"}`}><i />{operation === "load" ? "Loading…" : status?.configured ? status.ready ? "Connection saved" : "Connection needs attention" : "Not connected"}</span></div>
    {error && <div className="notice error" role="alert">{error}</div>}
    {notice && <div className="notice success" role="status">{notice}</div>}
    {operation && <p role="status">{operationMessage[operation]}</p>}
    {!status && error && <div className="google-sheets-actions"><button className="btn secondary" type="button" disabled={busy} onClick={() => void retryLoad()}>Retry connection status</button></div>}
    {!error && status?.last_result && status.last_result !== "success" && <div className="notice error" role="alert">{status.last_message || "The last update was not confirmed. Review the Google Sheet before retrying."}</div>}
    {status?.configured && !status.ready && !error && <div className="notice error" role="alert">The saved connection needs a valid service account key before it can update the sheet. Edit the connection and choose the JSON key again.</div>}
    {status?.configured && <dl className="google-sheets-summary"><div><dt>Connected sheet</dt><dd>{status.spreadsheet_title || "Google Sheet"}</dd></div><div><dt>Service account</dt><dd>{status.service_account_email || "Saved locally"}</dd></div><div><dt>Last successful update</dt><dd>{updatedDate(status.last_updated_at)}</dd></div></dl>}
    {!!status?.row_counts.length && <div className="google-sheets-counts" aria-label="Rows from the last successful update">{status.row_counts.map(item => <div key={item.title}><span>{item.title}</span><strong>{item.rows.toLocaleString()} {item.rows === 1 ? "row" : "rows"}</strong></div>)}</div>}
    <div className="google-sheets-actions"><button className="btn primary" type="button" disabled={!status?.configured || !status.ready || !status.spreadsheet_id || busy || readingKey} onClick={() => void sync()}>{operation === "sync" ? "Updating…" : content.update}</button>{status?.configured && <button className="btn secondary" type="button" disabled={busy || readingKey} onClick={() => void testConnection()}>{operation === "test" ? "Testing…" : "Test connection"}</button>}{sheetLink && <a className="btn secondary" href={sheetLink} target="_blank" rel="noopener noreferrer">Open Google Sheet</a>}<button className="btn secondary" type="button" aria-expanded={formOpen} aria-controls={`${identity}-connection`} disabled={busy} onClick={toggleForm}>{formOpen ? "Close connection settings" : status?.configured ? "Edit connection" : "Connect Google Sheet"}</button>{status?.configured && <button className="btn secondary danger" type="button" disabled={busy || readingKey} onClick={() => void disconnect()}>{operation === "disconnect" ? "Disconnecting…" : "Disconnect"}</button>}</div>
    <details className="google-sheets-coverage"><summary>What is included in this sheet?</summary><p>Every update replaces only the current contents of these Cathedra tabs in this spreadsheet. Your other tabs stay in place.</p><ul>{content.tabs.map(title => <li key={title}>Cathedra {title}</li>)}</ul><p>{content.note}</p></details>
    {formOpen && <div className="google-sheets-connection" id={`${identity}-connection`}>
      <div className="google-sheets-setup"><h3>One-time setup</h3><ol><li>Create a separate Google spreadsheet for {content.title}. Enable the Google Sheets API in Google Cloud and download a service account JSON key.</li><li>Choose that key below, then share this Google spreadsheet with the displayed service account email as an <strong>Editor</strong>. The same service account and key can be used for all three category sheets.</li><li>Save this connection and test it. Use <strong>{content.update}</strong> to send this category’s current records.</li></ol><button className="btn secondary" type="button" disabled={busy || readingKey} onClick={() => void downloadGuide()}>{operation === "guide" ? "Downloading guide…" : "Download detailed setup guide"}</button></div>
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
