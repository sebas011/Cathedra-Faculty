import { downloadFile, request } from "./client";

export interface GoogleSheetsStatus {
  configured: boolean;
  ready: boolean;
  spreadsheet_id: string | null;
  spreadsheet_url: string | null;
  spreadsheet_title: string | null;
  service_account_email: string | null;
  last_updated_at: string | null;
  last_result: "success" | "error" | "uncertain" | null;
  last_message: string | null;
  row_counts: { title: string; rows: number }[];
  message?: string;
}

const path = "/maintenance/google-sheets";
export type GoogleSheetsDestination = "workloads" | "overload" | "profiles";
const destinationPath = (destination?: GoogleSheetsDestination) => destination ? `${path}/destinations/${destination}` : path;
export const getGoogleSheetsStatus = (destination?: GoogleSheetsDestination) => request<GoogleSheetsStatus>(destinationPath(destination));
export const configureGoogleSheets = (spreadsheet_url: string, service_account_json: string | null, destination?: GoogleSheetsDestination) =>
  request<GoogleSheetsStatus>(destinationPath(destination), { method: "PUT", body: JSON.stringify({ spreadsheet_url, service_account_json }) });
export const testGoogleSheetsConnection = (destination?: GoogleSheetsDestination) => request<GoogleSheetsStatus>(`${destinationPath(destination)}/test`, { method: "POST" });
export const updateGoogleSheet = (spreadsheet_id: string, destination?: GoogleSheetsDestination) => request<GoogleSheetsStatus>(`${destinationPath(destination)}/sync`, { method: "POST", body: JSON.stringify({ spreadsheet_id }) });
export const disconnectGoogleSheets = (destination?: GoogleSheetsDestination) => request<GoogleSheetsStatus>(destinationPath(destination), { method: "DELETE" });
export const downloadGoogleSheetsGuide = () => downloadFile(`${path}/setup-guide`, "cathedra-google-sheets-setup.md");

/** Always build an outbound link ourselves; never render an arbitrary returned URL. */
export function canonicalGoogleSheetUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    const match = /^\/spreadsheets\/d\/([A-Za-z0-9_-]{10,200})(?:\/|$)/.exec(url.pathname);
    if (url.protocol !== "https:" || url.hostname !== "docs.google.com" || url.port || url.username || url.password || !match) return null;
    return `https://docs.google.com/spreadsheets/d/${match[1]}/edit`;
  } catch { return null; }
}
