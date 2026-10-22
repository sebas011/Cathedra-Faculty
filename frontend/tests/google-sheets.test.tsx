import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import GoogleSheetsCards, { GoogleSheetsDestinationCard } from "../src/components/GoogleSheetsCard";
import { canonicalGoogleSheetUrl } from "../src/api/googleSheets";
import type { GoogleSheetsStatus } from "../src/api/googleSheets";
import { administrator } from "./fixtures";

function GoogleSheetsCard() { return <GoogleSheetsDestinationCard destination="workloads" />; }

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
  expect((screen.getByRole("button", { name: "Update workload sheet" }) as HTMLButtonElement).disabled).toBe(true);
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
  expect((screen.getByRole("button", { name: "Update workload sheet" }) as HTMLButtonElement).disabled).toBe(true);
  expect((await screen.findByRole("alert")).textContent).toContain("choose the JSON key again");
  fireEvent.click(screen.getByRole("button", { name: "Update workload sheet" }));
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
});

test("workload coverage names only its four owned worksheets", async () => {
  await openCard();
  fireEvent.click(screen.getByText("What is included in this sheet?"));
  const coverage = screen.getByText("What is included in this sheet?").closest("details")!;
  expect(within(coverage).getAllByRole("listitem")).toHaveLength(4);
  expect(within(coverage).getByText("Cathedra Workloads")).toBeTruthy();
  expect(within(coverage).getByText("Cathedra Assignments")).toBeTruthy();
  expect(within(coverage).getByText("Cathedra Approved Workloads")).toBeTruthy();
  expect(within(coverage).queryByText("Cathedra Salary Projection")).toBeNull();
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
  expect(sheets.configureGoogleSheets).toHaveBeenCalledWith(spreadsheetUrl, syntheticKey, "workloads");
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
  await waitFor(() => expect(sheets.configureGoogleSheets).toHaveBeenCalledWith(newUrl, null, "workloads"));
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
  fireEvent.click(screen.getByRole("button", { name: "Update workload sheet" }));
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

test("workload sync confirms its destination and owned tabs, and cancellation never writes", async () => {
  await openCard();
  const update = screen.getByRole("button", { name: "Update workload sheet" });
  fireEvent.click(update);
  fireEvent.click(update);
  const dialog = await screen.findByRole("dialog", { name: "Update workload sheet?" });
  expect(dialog.textContent).toContain("current faculty workloads");
  expect(dialog.textContent).toContain(spreadsheetUrl);
  expect(dialog.textContent).not.toContain("salary information");
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
  fireEvent.click(screen.getByRole("button", { name: "Update workload sheet" }));
  const dialog = await screen.findByRole("dialog", { name: "Update workload sheet?" });
  const confirm = within(dialog).getByRole("button", { name: "Update workload sheet" });
  fireEvent.click(confirm);
  fireEvent.click(confirm);
  await waitFor(() => expect(sheets.updateGoogleSheet).toHaveBeenCalledTimes(1));
  expect(sheets.updateGoogleSheet).toHaveBeenCalledWith(spreadsheetId, "workloads");
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
  fireEvent.click(screen.getByRole("button", { name: "Update workload sheet" }));
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Update workload sheet" }));
  expect((await screen.findByRole("alert")).textContent).toContain("could not be confirmed");
  await waitFor(() => expect(sheets.getGoogleSheetsStatus).toHaveBeenCalledTimes(2));
  await waitFor(() => expect((screen.getByRole("button", { name: "Update workload sheet" }) as HTMLButtonElement).disabled).toBe(false));
  expect(sheets.updateGoogleSheet).toHaveBeenCalledTimes(1);
});

test("unmounting a pending confirmation never starts a sync", async () => {
  const view = await openCard();
  fireEvent.click(screen.getByRole("button", { name: "Update workload sheet" }));
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
  expect((screen.getByRole("button", { name: "Update workload sheet" }) as HTMLButtonElement).disabled).toBe(true);
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

test.each(["workloads", "overload", "profiles"] as const)("API helpers use only the selected %s destination", async destination => {
  const actual = await vi.importActual<typeof import("../src/api/googleSheets")>("../src/api/googleSheets");
  await actual.getGoogleSheetsStatus(destination);
  await actual.configureGoogleSheets(spreadsheetUrl, syntheticKey, destination);
  await actual.testGoogleSheetsConnection(destination);
  await actual.updateGoogleSheet(spreadsheetId, destination);
  await actual.disconnectGoogleSheets(destination);
  const path = `/maintenance/google-sheets/destinations/${destination}`;
  expect(transport.request.mock.calls).toEqual([
    [path],
    [path, { method: "PUT", body: JSON.stringify({ spreadsheet_url: spreadsheetUrl, service_account_json: syntheticKey }) }],
    [`${path}/test`, { method: "POST" }],
    [`${path}/sync`, { method: "POST", body: JSON.stringify({ spreadsheet_id: spreadsheetId }) }],
    [path, { method: "DELETE" }],
  ]);
});

test("three destination cards keep an existing combined connection without migrating or updating it", async () => {
  sheets.getGoogleSheetsStatus.mockImplementation((destination?: string) => Promise.resolve(destination ? disconnected : connected));
  render(<GoogleSheetsCards />);
  await screen.findByText("Your previous combined connection is kept.");
  for (const [destination, title] of [["workloads", "Faculty Workload"], ["overload", "Overload Projection"], ["profiles", "Faculty Profile"]]) {
    const card = screen.getByRole("region", { name: title });
    await waitFor(() => expect((within(card).getByRole("button", { name: "Connect Google Sheet" }) as HTMLButtonElement).disabled).toBe(false));
    expect(sheets.getGoogleSheetsStatus).toHaveBeenCalledWith(destination);
  }
  expect(screen.getAllByRole("region")).toHaveLength(3);
  expect(sheets.getGoogleSheetsStatus.mock.calls.filter(call => call.length === 0)).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "Update Google Sheet" })).toBeNull();
  expect(sheets.configureGoogleSheets).not.toHaveBeenCalled();
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
  expect(sheets.disconnectGoogleSheets).not.toHaveBeenCalled();
});

test("an unavailable legacy connection does not block any category connection", async () => {
  sheets.getGoogleSheetsStatus.mockImplementation((destination?: string) => destination ? Promise.resolve(connected) : Promise.reject(new Error("Previous status unavailable")));
  render(<GoogleSheetsCards />);
  await screen.findByText(/previous combined connection could not be checked/);
  for (const name of ["Update workload sheet", "Update overload sheet", "Update profile sheet"]) {
    await waitFor(() => expect((screen.getByRole("button", { name }) as HTMLButtonElement).disabled).toBe(false));
  }
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
});

test.each([null, { ...administrator, role: "staff" as const }])("the complete three-sheet area is hidden for non-administrators", user => {
  api.getCurrentUser.mockReturnValue(user);
  const { container } = render(<GoogleSheetsCards />);
  expect(container.textContent).toBe("");
  expect(sheets.getGoogleSheetsStatus).not.toHaveBeenCalled();
});

test.each([
  ["overload", ["Cathedra Overview", "Cathedra Overload Projection", "Cathedra Overload Budgets", "Cathedra Cost Settings"]],
  ["profiles", ["Cathedra Overview", "Cathedra Faculty"]],
] as const)("%s coverage lists only that category's tabs", async (destination, titles) => {
  render(<GoogleSheetsDestinationCard destination={destination} />);
  await waitFor(() => expect((screen.getByRole("button", { name: "Connect Google Sheet" }) as HTMLButtonElement).disabled).toBe(false));
  const coverage = screen.getByText("What is included in this sheet?").closest("details")!;
  fireEvent.click(within(coverage).getByText("What is included in this sheet?"));
  expect(within(coverage).getAllByRole("listitem").map(item => item.textContent)).toEqual(titles);
  expect(within(coverage).queryByText("Cathedra Salary Projection")).toBeNull();
  expect(within(coverage).queryByText("Cathedra Saved Estimates")).toBeNull();
});

test.each([
  ["overload", "Update overload sheet", "Regular Faculty overload projections", "Cathedra Overload Projection"],
  ["profiles", "Update profile sheet", "including recorded salary information", "Cathedra Faculty"],
] as const)("%s sync confirms its contents and writes only to the selected category", async (destination, update, contents, tab) => {
  sheets.getGoogleSheetsStatus.mockResolvedValue(connected);
  render(<GoogleSheetsDestinationCard destination={destination} />);
  await waitFor(() => expect((screen.getByRole("button", { name: update }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: update }));
  const dialog = await screen.findByRole("dialog", { name: `${update}?` });
  expect(dialog.textContent).toContain(contents);
  expect(dialog.textContent).toContain(tab);
  expect(dialog.textContent).toContain(spreadsheetUrl);
  expect(dialog.textContent).toContain("Other tabs will be kept");
  expect(dialog.textContent).not.toContain("Cathedra Salary Projection");
  fireEvent.click(within(dialog).getByRole("button", { name: update }));
  await waitFor(() => expect(sheets.updateGoogleSheet).toHaveBeenCalledWith(spreadsheetId, destination));
  expect(sheets.updateGoogleSheet).toHaveBeenCalledTimes(1);
});

test("a category load error and a different category's pending request leave the workload card usable", async () => {
  const pending = deferred<GoogleSheetsStatus>();
  sheets.getGoogleSheetsStatus.mockImplementation((destination?: string) => {
    if (destination === "overload") return pending.promise;
    if (destination === "profiles") return Promise.reject(new Error("Profile connection unavailable."));
    return Promise.resolve(destination ? connected : disconnected);
  });
  render(<GoogleSheetsCards />);
  const workloads = within(screen.getByRole("region", { name: "Faculty Workload" }));
  const overload = within(screen.getByRole("region", { name: "Overload Projection" }));
  const profiles = within(screen.getByRole("region", { name: "Faculty Profile" }));
  await waitFor(() => expect((workloads.getByRole("button", { name: "Update workload sheet" }) as HTMLButtonElement).disabled).toBe(false));
  expect((overload.getByRole("button", { name: "Update overload sheet" }) as HTMLButtonElement).disabled).toBe(true);
  expect((await profiles.findByRole("alert")).textContent).toContain("Profile connection unavailable");
  expect(workloads.queryByRole("alert")).toBeNull();
  expect(overload.queryByRole("alert")).toBeNull();
  sheets.getGoogleSheetsStatus.mockResolvedValueOnce(connected);
  fireEvent.click(profiles.getByRole("button", { name: "Retry connection status" }));
  await waitFor(() => expect((profiles.getByRole("button", { name: "Update profile sheet" }) as HTMLButtonElement).disabled).toBe(false));
  expect(sheets.getGoogleSheetsStatus).toHaveBeenLastCalledWith("profiles");
  await act(async () => pending.resolve(disconnected));
});

test("selected keys and failed-save cleanup stay inside their own category", async () => {
  const workloadUrl = "https://docs.google.com/spreadsheets/d/synthetic_workload_12345/edit";
  const profileUrl = "https://docs.google.com/spreadsheets/d/synthetic_profile_12345/edit";
  const profileKey = syntheticKey.replace("SYNTHETIC TEST VALUE", "SYNTHETIC PROFILE VALUE");
  render(<GoogleSheetsCards />);
  const workloads = within(screen.getByRole("region", { name: "Faculty Workload" }));
  const profiles = within(screen.getByRole("region", { name: "Faculty Profile" }));
  for (const card of [workloads, profiles]) {
    await waitFor(() => expect((card.getByRole("button", { name: "Connect Google Sheet" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(card.getByRole("button", { name: "Connect Google Sheet" }));
  }
  fireEvent.change(workloads.getByLabelText("Google Sheet link"), { target: { value: workloadUrl } });
  fireEvent.change(profiles.getByLabelText("Google Sheet link"), { target: { value: profileUrl } });
  fireEvent.change(workloads.getByLabelText(/Service account JSON key/), { target: { files: [new File([syntheticKey], "workload.json")] } });
  fireEvent.change(profiles.getByLabelText(/Service account JSON key/), { target: { files: [new File([profileKey], "profile.json")] } });
  await workloads.findByText(serviceEmail, { selector: "strong" });
  await profiles.findByText(serviceEmail, { selector: "strong" });
  sheets.configureGoogleSheets.mockRejectedValueOnce(new Error("Profile settings could not be saved."));
  fireEvent.click(profiles.getByRole("button", { name: "Save connection" }));
  await profiles.findByRole("alert");
  expect(profiles.queryByText(serviceEmail, { selector: "strong" })).toBeNull();
  expect(workloads.getByText(serviceEmail, { selector: "strong" })).toBeTruthy();
  expect(sheets.configureGoogleSheets).toHaveBeenNthCalledWith(1, profileUrl, profileKey, "profiles");
  fireEvent.click(workloads.getByRole("button", { name: "Save connection" }));
  await waitFor(() => expect(sheets.configureGoogleSheets).toHaveBeenNthCalledWith(2, workloadUrl, syntheticKey, "workloads"));
  expect(document.body.textContent).not.toContain("SYNTHETIC TEST VALUE");
  expect(document.body.textContent).not.toContain("SYNTHETIC PROFILE VALUE");
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
});

test("updating workload history leaves profile history and actions independent", async () => {
  const pending = deferred<GoogleSheetsStatus>();
  const profileId = "synthetic_profile_98765";
  const profileStatus = { ...connected, spreadsheet_id: profileId, spreadsheet_url: `https://docs.google.com/spreadsheets/d/${profileId}/edit`, spreadsheet_title: "Profile destination" };
  sheets.getGoogleSheetsStatus.mockImplementation((destination?: string) => Promise.resolve(destination === "profiles" ? profileStatus : destination === "workloads" ? connected : disconnected));
  sheets.testGoogleSheetsConnection.mockResolvedValue(profileStatus);
  sheets.updateGoogleSheet.mockReturnValueOnce(pending.promise);
  render(<GoogleSheetsCards />);
  const workloads = within(screen.getByRole("region", { name: "Faculty Workload" }));
  const profiles = within(screen.getByRole("region", { name: "Faculty Profile" }));
  await waitFor(() => expect((workloads.getByRole("button", { name: "Update workload sheet" }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(workloads.getByRole("button", { name: "Update workload sheet" }));
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Update workload sheet" }));
  await waitFor(() => expect(sheets.updateGoogleSheet).toHaveBeenCalledWith(spreadsheetId, "workloads"));
  expect((profiles.getByRole("button", { name: "Update profile sheet" }) as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(profiles.getByRole("button", { name: "Test connection" }));
  await waitFor(() => expect(sheets.testGoogleSheetsConnection).toHaveBeenCalledWith("profiles"));
  await act(async () => pending.resolve({ ...completed, row_counts: [{ title: "Cathedra Workloads", rows: 8 }] }));
  await workloads.findByText("8 rows");
  expect(profiles.queryByText("8 rows")).toBeNull();
  expect(profiles.getByText("No successful update yet")).toBeTruthy();
});

test("disconnect removes only the selected category connection", async () => {
  sheets.getGoogleSheetsStatus.mockImplementation((destination?: string) => Promise.resolve(destination ? connected : disconnected));
  render(<GoogleSheetsCards />);
  const workloads = within(screen.getByRole("region", { name: "Faculty Workload" }));
  const profiles = within(screen.getByRole("region", { name: "Faculty Profile" }));
  await waitFor(() => expect((profiles.getByRole("button", { name: "Disconnect" }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(profiles.getByRole("button", { name: "Disconnect" }));
  const dialog = await screen.findByRole("dialog");
  expect(dialog.textContent).toContain("saved Faculty Profile connection");
  expect(dialog.textContent).toContain("other category connections will also be kept");
  fireEvent.click(within(dialog).getByRole("button", { name: "Disconnect" }));
  await profiles.findByRole("button", { name: "Connect Google Sheet" });
  expect(sheets.disconnectGoogleSheets).toHaveBeenCalledWith("profiles");
  expect(sheets.disconnectGoogleSheets).toHaveBeenCalledTimes(1);
  expect(workloads.getByRole("link", { name: "Open Google Sheet" })).toBeTruthy();
  expect((workloads.getByRole("button", { name: "Update workload sheet" }) as HTMLButtonElement).disabled).toBe(false);
});

test("removing the previous connection requires confirmation and keeps category connections usable", async () => {
  const pending = deferred<GoogleSheetsStatus>();
  sheets.getGoogleSheetsStatus.mockResolvedValue(connected);
  sheets.disconnectGoogleSheets.mockReturnValueOnce(pending.promise);
  render(<GoogleSheetsCards />);
  const remove = await screen.findByRole("button", { name: "Disconnect previous connection" });
  fireEvent.click(remove);
  let dialog = await screen.findByRole("dialog", { name: "Disconnect previous connection?" });
  expect(dialog.textContent).toContain("Google spreadsheet and all existing tabs will be kept");
  expect(dialog.textContent).toContain("three category connections will also be kept");
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(sheets.disconnectGoogleSheets).not.toHaveBeenCalled();
  fireEvent.click(remove);
  dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Disconnect previous connection" }));
  await waitFor(() => expect(sheets.disconnectGoogleSheets).toHaveBeenCalledTimes(1));
  expect(sheets.disconnectGoogleSheets.mock.calls).toEqual([[]]);
  expect((screen.getByRole("button", { name: "Waiting for previous connection removal…" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Update workload sheet" }) as HTMLButtonElement).disabled).toBe(false);
  await act(async () => pending.resolve({ ...disconnected, message: "Disconnected. Existing Google Sheets tabs remain available." }));
  await screen.findByText(/Previous connection removed/);
  expect(screen.queryByRole("button", { name: "Disconnect previous connection" })).toBeNull();
  expect(screen.getAllByRole("link", { name: "Open Google Sheet" })).toHaveLength(3);
  expect(sheets.configureGoogleSheets).not.toHaveBeenCalled();
  expect(sheets.updateGoogleSheet).not.toHaveBeenCalled();
});

test.each([false, true])("unreadable previous settings allow explicit recovery when configured is %s", async configured => {
  sheets.getGoogleSheetsStatus.mockImplementation((destination?: string) => Promise.resolve(destination ? disconnected : {
    ...disconnected, configured, message: "Saved Google Sheets settings could not be opened. Reconnect with the original service-account JSON key.",
  }));
  sheets.disconnectGoogleSheets.mockRejectedValueOnce(new Error("The previous settings could not be removed."));
  render(<GoogleSheetsCards />);
  const remove = await screen.findByRole("button", { name: "Disconnect previous connection" });
  fireEvent.click(remove);
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Disconnect previous connection" }));
  expect((await screen.findByRole("alert")).textContent).toContain("previous settings could not be removed");
  expect(sheets.disconnectGoogleSheets.mock.calls).toEqual([[]]);
  await waitFor(() => expect((remove as HTMLButtonElement).disabled).toBe(false));
  const workloads = within(screen.getByRole("region", { name: "Faculty Workload" }));
  expect(workloads.queryByRole("alert")).toBeNull();
  expect((workloads.getByRole("button", { name: "Connect Google Sheet" }) as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(remove);
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Disconnect previous connection" }));
  await screen.findByText(/Previous connection removed/);
  expect(sheets.disconnectGoogleSheets.mock.calls).toEqual([[], []]);
  expect(screen.queryByRole("alert")).toBeNull();
});

test("leaving a previous-connection confirmation never removes the saved connection", async () => {
  sheets.getGoogleSheetsStatus.mockResolvedValue(connected);
  const view = render(<GoogleSheetsCards />);
  fireEvent.click(await screen.findByRole("button", { name: "Disconnect previous connection" }));
  await screen.findByRole("dialog");
  view.unmount();
  await act(async () => {});
  expect(sheets.disconnectGoogleSheets).not.toHaveBeenCalled();
});
