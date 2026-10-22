import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import GoogleSheetsCard from "../src/components/GoogleSheetsCard";
import { canonicalGoogleSheetUrl } from "../src/api/googleSheets";
import type { GoogleSheetsStatus } from "../src/api/googleSheets";
import { administrator } from "./fixtures";

const api = vi.hoisted(() => ({ getCurrentUser: vi.fn() }));
const sheets = vi.hoisted(() => ({
  getGoogleSheetsStatus: vi.fn(), configureGoogleSheets: vi.fn(), testGoogleSheetsConnection: vi.fn(),
  updateGoogleSheet: vi.fn(), disconnectGoogleSheets: vi.fn(), downloadGoogleSheetsGuide: vi.fn(),
}));
const transport = vi.hoisted(() => ({ request: vi.fn(), downloadFile: vi.fn() }));
vi.mock("../src/api", () => api);
vi.mock("../src/api/client", () => transport);
vi.mock("../src/api/googleSheets", async importOriginal => ({
  ...await importOriginal<typeof import("../src/api/googleSheets")>(), ...sheets,
}));

const spreadsheetId = "synthetic_sheet_12345";
const spreadsheetUrl = `https://docs.google.com/spreadsheets/d/${spreadsheetId}/edit`;
const serviceEmail = "synthetic-export@synthetic-project.iam.gserviceaccount.com";
const syntheticKey = JSON.stringify({ type: "service_account", client_email: serviceEmail, private_key: "SYNTHETIC TEST VALUE; NOT A REAL KEY" });
const disconnected: GoogleSheetsStatus = {
  configured: false, ready: false, spreadsheet_id: null, spreadsheet_url: null, spreadsheet_title: null,
  service_account_email: null, last_updated_at: null, last_result: null, last_message: null, row_counts: [],
};
const connected: GoogleSheetsStatus = {
  ...disconnected, configured: true, ready: true, spreadsheet_id: spreadsheetId, spreadsheet_url: spreadsheetUrl,
  spreadsheet_title: "Synthetic faculty export", service_account_email: serviceEmail,
};
const completed: GoogleSheetsStatus = {
  ...connected, last_updated_at: "2026-10-20T10:30:00Z", last_result: "success", last_message: "Google Sheet updated.",
  row_counts: [{ title: "Cathedra Faculty", rows: 2 }, { title: "Cathedra Workloads", rows: 1 }],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
async function openCard(status: GoogleSheetsStatus = connected) {
  sheets.getGoogleSheetsStatus.mockResolvedValue(status);
  const view = render(<GoogleSheetsCard />);
  await waitFor(() => expect((screen.getByRole("button", { name: status.configured ? "Edit connection" : "Connect Google Sheet" }) as HTMLButtonElement).disabled).toBe(false));
  return view;
}
async function openForm(status: GoogleSheetsStatus = disconnected) {
  const view = await openCard(status);
  fireEvent.click(screen.getByRole("button", { name: status.configured ? "Edit connection" : "Connect Google Sheet" }));
  return view;
}
async function chooseKey(text = syntheticKey) {
  fireEvent.change(screen.getByLabelText(/Service account JSON key/), { target: { files: [new File([text], "synthetic-service-account.json", { type: "application/json" })] } });
  await screen.findByText(serviceEmail, { selector: "strong" });
}

beforeEach(() => {
  vi.resetAllMocks();
  api.getCurrentUser.mockReturnValue(administrator);
  sheets.getGoogleSheetsStatus.mockResolvedValue(disconnected);
  sheets.configureGoogleSheets.mockResolvedValue(connected);
  sheets.testGoogleSheetsConnection.mockResolvedValue({ ...connected, message: "Connection verified. No sheet data was changed." });
  sheets.updateGoogleSheet.mockResolvedValue(completed);
  sheets.disconnectGoogleSheets.mockResolvedValue(disconnected);
  sheets.downloadGoogleSheetsGuide.mockResolvedValue(undefined);
});

test.each([null, { ...administrator, role: "staff" as const }])("non-admin viewers never mount the card or request Google Sheets state", user => {
  api.getCurrentUser.mockReturnValue(user);
  const { container } = render(<GoogleSheetsCard />);
  expect(container.textContent).toBe("");
  expect(sheets.getGoogleSheetsStatus).not.toHaveBeenCalled();
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
});

test("loading and unavailable state disable updates and offer a recoverable status request", async () => {
  const pending = deferred<GoogleSheetsStatus>();
  sheets.getGoogleSheetsStatus.mockReturnValueOnce(pending.promise).mockResolvedValueOnce(connected);
  render(<GoogleSheetsCard />);
  expect((screen.getByRole("button", { name: "Update Google Sheet" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByRole("region").getAttribute("aria-busy")).toBe("true");
  await act(async () => pending.reject(new Error("The local service is unavailable.")));
  expect((await screen.findByRole("alert")).textContent).toContain("local service is unavailable");
  fireEvent.click(screen.getByRole("button", { name: "Retry connection status" }));
  await screen.findByText("Synthetic faculty export");
  expect(screen.queryByRole("alert")).toBeNull();
  expect(sheets.getGoogleSheetsStatus).toHaveBeenCalledTimes(2);
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
});

test("saved connections show a canonical safe link and never sync automatically", async () => {
  await openCard({ ...connected, spreadsheet_url: `${spreadsheetUrl}?usp=sharing#gid=42` });
  const link = screen.getByRole("link", { name: "Open Google Sheet" });
  expect(link.getAttribute("href")).toBe(spreadsheetUrl);
  expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  expect(screen.getByText(serviceEmail)).toBeTruthy();
  expect(screen.getByText("No successful update yet")).toBeTruthy();
  expect(sheets.testGoogleSheetsConnection).not.toHaveBeenCalled();
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
});

test("a saved connection with an unreadable key needs repair before updating", async () => {
  await openCard({ ...connected, ready: false });
  expect((screen.getByRole("button", { name: "Update Google Sheet" }) as HTMLButtonElement).disabled).toBe(true);
  expect((await screen.findByRole("alert")).textContent).toContain("choose the JSON key again");
  fireEvent.click(screen.getByRole("button", { name: "Update Google Sheet" }));
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
});

test("the data coverage names all 12 owned worksheets", async () => {
  await openCard();
  fireEvent.click(screen.getByText("What is included in the 12 Cathedra tabs?"));
  const coverage = screen.getByText("What is included in the 12 Cathedra tabs?").closest("details")!;
  expect(within(coverage).getAllByRole("listitem")).toHaveLength(12);
  expect(within(coverage).getByText("Cathedra Salary Projection")).toBeTruthy();
  expect(within(coverage).getByText("Cathedra Teaching Projection")).toBeTruthy();
  expect(within(coverage).getByText("Cathedra No Teaching")).toBeTruthy();
});

test.each([
  "https://docs.google.com.evil.example/spreadsheets/d/synthetic_sheet_12345/edit",
  "https://docs.google.com@evil.example/spreadsheets/d/synthetic_sheet_12345/edit",
  "https://someone@docs.google.com/spreadsheets/d/synthetic_sheet_12345/edit",
  "https://docs.google.com:8443/spreadsheets/d/synthetic_sheet_12345/edit",
  "http://docs.google.com/spreadsheets/d/synthetic_sheet_12345/edit",
  "javascript:alert(1)", "https://docs.google.com/document/d/synthetic_sheet_12345/edit",
  "https://docs.google.com/spreadsheets/d/short/edit",
])("rejects unsafe or unsupported outbound Sheet URLs: %s", value => {
  expect(canonicalGoogleSheetUrl(value)).toBeNull();
});

test("an unsafe returned URL is never offered as an outbound link", async () => {
  await openCard({ ...connected, spreadsheet_url: "https://evil.example/" });
  expect(screen.queryByRole("link", { name: "Open Google Sheet" })).toBeNull();
});

test("one-time setup keeps the key out of rendered content and browser storage, and sends it only on save", async () => {
  await openForm();
  fireEvent.change(screen.getByLabelText("Google Sheet link"), { target: { value: `${spreadsheetUrl}?usp=sharing` } });
  await chooseKey();
  expect(document.body.textContent).not.toContain("SYNTHETIC TEST VALUE");
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
  const pending = deferred<GoogleSheetsStatus>();
  sheets.configureGoogleSheets.mockReturnValueOnce(pending.promise);
  const save = screen.getByRole("button", { name: "Save connection" });
  fireEvent.click(save);
  fireEvent.click(save);
  expect(sheets.configureGoogleSheets).toHaveBeenCalledTimes(1);
  expect(sheets.configureGoogleSheets).toHaveBeenCalledWith(spreadsheetUrl, syntheticKey);
  expect(screen.queryByText(serviceEmail, { selector: "strong" })).toBeNull();
  expect((screen.getByLabelText(/Service account JSON key/) as HTMLInputElement).value).toBe("");
  await act(async () => pending.resolve(connected));
  await screen.findByText(/Connection saved\. Test the connection/);
  expect(screen.queryByLabelText("Google Sheet link")).toBeNull();
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
});

test("editing only the URL retains the saved key and canonicalizes the new destination", async () => {
  await openForm(connected);
  const newUrl = "https://docs.google.com/spreadsheets/d/synthetic_replacement_98765/edit";
  fireEvent.change(screen.getByLabelText("Google Sheet link"), { target: { value: `${newUrl}#gid=9` } });
  fireEvent.click(screen.getByRole("button", { name: "Save connection" }));
  await waitFor(() => expect(sheets.configureGoogleSheets).toHaveBeenCalledWith(newUrl, null));
});

test("closing setup forgets the selected key before the form is opened again", async () => {
  await openForm();
  await chooseKey();
  fireEvent.click(screen.getByRole("button", { name: "Close connection settings" }));
  fireEvent.click(screen.getByRole("button", { name: "Connect Google Sheet" }));
  fireEvent.change(screen.getByLabelText("Google Sheet link"), { target: { value: spreadsheetUrl } });
  expect(screen.queryByText(serviceEmail, { selector: "strong" })).toBeNull();
  expect((screen.getByRole("button", { name: "Save connection" }) as HTMLButtonElement).disabled).toBe(true);
});

test("a failed save forgets the key and requires it again for a new connection", async () => {
  sheets.configureGoogleSheets.mockRejectedValueOnce(new Error("Connection settings could not be saved."));
  await openForm();
  fireEvent.change(screen.getByLabelText("Google Sheet link"), { target: { value: spreadsheetUrl } });
  await chooseKey();
  fireEvent.click(screen.getByRole("button", { name: "Save connection" }));
  await screen.findByRole("alert");
  expect(screen.queryByText(serviceEmail, { selector: "strong" })).toBeNull();
  expect((screen.getByRole("button", { name: "Save connection" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByLabelText(/Service account JSON key/) as HTMLInputElement).value).toBe("");
});

test.each([
  ["malformed JSON", "not JSON"],
  ["a different account type", JSON.stringify({ type: "authorized_user", client_email: serviceEmail, private_key: "synthetic" })],
  ["an invalid service account email", JSON.stringify({ type: "service_account", client_email: "person@example.com", private_key: "synthetic" })],
  ["a missing private key", JSON.stringify({ type: "service_account", client_email: serviceEmail })],
])("invalid file content (%s) clears a previously selected key", async (_label, value) => {
  await openForm();
  await chooseKey();
  fireEvent.change(screen.getByLabelText(/Service account JSON key/), { target: { files: [new File([value], "invalid.json")] } });
  expect((await screen.findByRole("alert")).textContent).toContain("valid service account JSON key");
  expect(screen.queryByText(serviceEmail, { selector: "strong" })).toBeNull();
  expect(sheets.configureGoogleSheets).not.toHaveBeenCalled();
});

test("files larger than 64 KiB are rejected before reading and clear the previous key", async () => {
  await openForm();
  await chooseKey();
  const read = vi.spyOn(FileReader.prototype, "readAsText");
  fireEvent.change(screen.getByLabelText(/Service account JSON key/), { target: { files: [new File(["x".repeat(64 * 1024 + 1)], "too-large.json")] } });
  expect((await screen.findByRole("alert")).textContent).toContain("no larger than 64 KiB");
  expect(read).not.toHaveBeenCalled();
  expect(screen.queryByText(serviceEmail, { selector: "strong" })).toBeNull();
});

test("a synchronous file-read failure clears credentials and is announced", async () => {
  await openForm();
  await chooseKey();
  vi.spyOn(FileReader.prototype, "readAsText").mockImplementationOnce(() => { throw new Error("Synthetic read failure"); });
  fireEvent.change(screen.getByLabelText(/Service account JSON key/), { target: { files: [new File([syntheticKey], "unreadable.json")] } });
  expect((await screen.findByRole("alert")).textContent).toContain("could not be read");
  expect(screen.queryByText(serviceEmail, { selector: "strong" })).toBeNull();
});

test("a file-reader error forgets the chosen key and lets another file be selected", async () => {
  await openForm();
  await chooseKey();
  const read = vi.spyOn(FileReader.prototype, "readAsText").mockImplementationOnce(() => {});
  fireEvent.change(screen.getByLabelText(/Service account JSON key/), { target: { files: [new File([syntheticKey], "unreadable.json")] } });
  const reader = read.mock.instances[0] as FileReader;
  act(() => reader.onerror?.(new ProgressEvent("error") as ProgressEvent<FileReader>));
  expect((await screen.findByRole("alert")).textContent).toContain("could not be read");
  expect(screen.queryByText(serviceEmail, { selector: "strong" })).toBeNull();
  expect((screen.getByLabelText(/Service account JSON key/) as HTMLInputElement).disabled).toBe(false);
});

test("cancelling the file picker clears the previous unsaved key", async () => {
  await openForm();
  await chooseKey();
  fireEvent.change(screen.getByLabelText(/Service account JSON key/), { target: { files: [] } });
  expect(screen.queryByText(serviceEmail, { selector: "strong" })).toBeNull();
  expect(sheets.configureGoogleSheets).not.toHaveBeenCalled();
});

test("reading a key blocks concurrent writes and closing setup invalidates a late file-read result", async () => {
  await openForm(connected);
  const read = vi.spyOn(FileReader.prototype, "readAsText").mockImplementation(() => {});
  const file = screen.getByLabelText(/Service account JSON key/);
  fireEvent.change(file, { target: { files: [new File([syntheticKey], "pending.json")] } });
  expect(screen.getByText("Reading key file…")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
  fireEvent.click(screen.getByRole("button", { name: "Update Google Sheet" }));
  fireEvent.submit(screen.getByRole("button", { name: "Save connection" }).closest("form")!);
  expect(sheets.testGoogleSheetsConnection).not.toHaveBeenCalled();
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
  expect(sheets.configureGoogleSheets).not.toHaveBeenCalled();
  const reader = read.mock.instances[0] as FileReader;
  fireEvent.click(screen.getByRole("button", { name: "Close connection settings" }));
  Object.defineProperty(reader, "result", { value: syntheticKey });
  act(() => reader.onload?.(new ProgressEvent("load") as ProgressEvent<FileReader>));
  fireEvent.click(screen.getByRole("button", { name: "Edit connection" }));
  expect(screen.queryByText(serviceEmail, { selector: "strong" })).toBeNull();
  expect(screen.queryByText("Reading key file…")).toBeNull();
});

test("unmounting during file reading discards late key content", async () => {
  const view = await openForm();
  const read = vi.spyOn(FileReader.prototype, "readAsText").mockImplementation(() => {});
  fireEvent.change(screen.getByLabelText(/Service account JSON key/), { target: { files: [new File([syntheticKey], "pending.json")] } });
  const reader = read.mock.instances[0] as FileReader;
  view.unmount();
  Object.defineProperty(reader, "result", { value: syntheticKey });
  act(() => reader.onload?.(new ProgressEvent("load") as ProgressEvent<FileReader>));
  expect(sheets.configureGoogleSheets).not.toHaveBeenCalled();
  await openForm();
  expect(screen.queryByText(serviceEmail, { selector: "strong" })).toBeNull();
});

test("connection testing is read-only and blocks duplicate clicks until its result arrives", async () => {
  const pending = deferred<GoogleSheetsStatus>();
  sheets.testGoogleSheetsConnection.mockReturnValueOnce(pending.promise);
  await openCard();
  const testButton = screen.getByRole("button", { name: "Test connection" });
  fireEvent.click(testButton);
  fireEvent.click(testButton);
  expect(sheets.testGoogleSheetsConnection).toHaveBeenCalledTimes(1);
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
  await act(async () => pending.resolve({ ...connected, message: "Connection verified. No sheet data was changed." }));
  await screen.findByText("Connection verified. No sheet data was changed.");
});

test("sync warns about salary data and owned tabs, and cancellation never writes", async () => {
  await openCard();
  const update = screen.getByRole("button", { name: "Update Google Sheet" });
  fireEvent.click(update);
  fireEvent.click(update);
  const dialog = await screen.findByRole("dialog", { name: "Update Google Sheet?" });
  expect(dialog.textContent).toContain("including salary information");
  expect(dialog.textContent).toContain("Other tabs will be kept");
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
  fireEvent.click(update);
  fireEvent(await screen.findByRole("dialog"), new Event("cancel", { cancelable: true }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
});

test("explicit sync writes once to the confirmed sheet and displays successful row counts", async () => {
  const pending = deferred<GoogleSheetsStatus>();
  sheets.updateGoogleSheet.mockReturnValueOnce(pending.promise);
  await openCard();
  fireEvent.click(screen.getByRole("button", { name: "Update Google Sheet" }));
  const dialog = await screen.findByRole("dialog", { name: "Update Google Sheet?" });
  const confirm = within(dialog).getByRole("button", { name: "Update Google Sheet" });
  fireEvent.click(confirm);
  fireEvent.click(confirm);
  await waitFor(() => expect(sheets.updateGoogleSheet).toHaveBeenCalledTimes(1));
  expect(sheets.updateGoogleSheet).toHaveBeenCalledWith(spreadsheetId);
  fireEvent.click(screen.getByRole("button", { name: "Updating…" }));
  expect(sheets.updateGoogleSheet).toHaveBeenCalledTimes(1);
  await act(async () => pending.resolve(completed));
  await screen.findByText("Google Sheet updated.");
  expect(screen.getByText("2 rows")).toBeTruthy();
  expect(screen.getByText("1 row")).toBeTruthy();
  expect(screen.getByLabelText("Rows from the last successful update")).toBeTruthy();
});

test("an uncertain sync refreshes persisted status without retrying the write", async () => {
  await openCard();
  sheets.updateGoogleSheet.mockRejectedValueOnce(new Error("The Google Sheet update could not be confirmed."));
  sheets.getGoogleSheetsStatus.mockResolvedValueOnce({ ...connected, last_result: "uncertain", last_message: "Review the sheet before retrying." });
  fireEvent.click(screen.getByRole("button", { name: "Update Google Sheet" }));
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Update Google Sheet" }));
  expect((await screen.findByRole("alert")).textContent).toContain("could not be confirmed");
  await waitFor(() => expect(sheets.getGoogleSheetsStatus).toHaveBeenCalledTimes(2));
  await waitFor(() => expect((screen.getByRole("button", { name: "Update Google Sheet" }) as HTMLButtonElement).disabled).toBe(false));
  expect(sheets.updateGoogleSheet).toHaveBeenCalledTimes(1);
});

test("unmounting a pending confirmation never starts a sync", async () => {
  const view = await openCard();
  fireEvent.click(screen.getByRole("button", { name: "Update Google Sheet" }));
  await screen.findByRole("dialog");
  view.unmount();
  await act(async () => {});
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
});

test("disconnect requires confirmation and keeps the remote sheet", async () => {
  await openCard();
  fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  let dialog = await screen.findByRole("dialog", { name: "Disconnect Google Sheet?" });
  expect(dialog.textContent).toContain("Google Sheet and its existing data will be kept");
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(sheets.disconnectGoogleSheets).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Disconnect" }));
  await screen.findByText("Google Sheets disconnected. The sheet and its data were kept.");
  expect(sheets.disconnectGoogleSheets).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("link", { name: "Open Google Sheet" })).toBeNull();
  expect((screen.getByRole("button", { name: "Update Google Sheet" }) as HTMLButtonElement).disabled).toBe(true);
});

test("the detailed setup guide downloads without configuring or updating a sheet", async () => {
  await openForm();
  fireEvent.click(screen.getByRole("button", { name: "Download detailed setup guide" }));
  await screen.findByText("Google Sheets setup guide downloaded.");
  expect(sheets.downloadGoogleSheetsGuide).toHaveBeenCalledTimes(1);
  expect(sheets.configureGoogleSheets).not.toHaveBeenCalled();
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
});

test("API helpers match the server contract and use the authenticated download helper", async () => {
  const actual = await vi.importActual<typeof import("../src/api/googleSheets")>("../src/api/googleSheets");
  await actual.getGoogleSheetsStatus();
  await actual.configureGoogleSheets(spreadsheetUrl, null);
  await actual.testGoogleSheetsConnection();
  await actual.updateGoogleSheet(spreadsheetId);
  await actual.disconnectGoogleSheets();
  await actual.downloadGoogleSheetsGuide();
  expect(transport.request.mock.calls).toEqual([
    ["/maintenance/google-sheets"],
    ["/maintenance/google-sheets", { method: "PUT", body: JSON.stringify({ spreadsheet_url: spreadsheetUrl, service_account_json: null }) }],
    ["/maintenance/google-sheets/test", { method: "POST" }],
    ["/maintenance/google-sheets/sync", { method: "POST", body: JSON.stringify({ spreadsheet_id: spreadsheetId }) }],
    ["/maintenance/google-sheets", { method: "DELETE" }],
  ]);
  expect(transport.downloadFile).toHaveBeenCalledWith("/maintenance/google-sheets/setup-guide", "cathedra-google-sheets-setup.md");
});
