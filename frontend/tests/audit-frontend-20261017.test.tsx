import { StrictMode } from "react";
import { beforeEach, expect, test, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, MemoryRouter, RouterProvider } from "react-router-dom";
import axe from "axe-core";
import AccountSecurityPage from "../src/pages/AccountSecurityPage";
import LoginPage from "../src/pages/LoginPage";
import WorkloadFormPage from "../src/pages/WorkloadFormPage";
import { useActionDialog } from "../src/hooks/useActionDialog";
import { administrator, faculty } from "./fixtures";

const api = vi.hoisted(() => ({
  getCurrentUser: vi.fn(), getUsers: vi.fn(), setUserActive: vi.fn(), revokeUserSessions: vi.fn(), resetUserPassword: vi.fn(), changePassword: vi.fn(), createUser: vi.fn(), clearSession: vi.fn(),
  getAccountStatus: vi.fn(), setupAdmin: vi.fn(), signIn: vi.fn(), saveSession: vi.fn(),
  getFacultyProfileOptions: vi.fn(), getWorkload: vi.fn(), createWorkload: vi.fn(), updateWorkload: vi.fn(),
}));
vi.mock("../src/api", () => api);
const staff = { ...administrator, id: 2, username: "synthetic-staff", role: "staff" as const };
beforeEach(() => {
  vi.resetAllMocks();
  api.getCurrentUser.mockReturnValue(administrator);
  api.getUsers.mockResolvedValue([staff]);
  api.getAccountStatus.mockResolvedValue({ setup_required: false });
  api.getFacultyProfileOptions.mockResolvedValue([faculty]);
  window.history.replaceState(null, "", "/");
});

function openWorkload() {
  const router = createMemoryRouter([{ path: "*", element: <WorkloadFormPage /> }], { initialEntries: ["/workload/new"] });
  render(<RouterProvider router={router} />);
}
async function fillAssignment(code: string) {
  fireEvent.click(await screen.findByRole("button", { name: "Add Assignment" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Course Code" }), { target: { value: code } });
  fireEvent.change(screen.getByRole("textbox", { name: "Course Title" }), { target: { value: "Synthetic course" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Year & Section" }), { target: { value: "BSAM 1A" } });
  fireEvent.change(screen.getByRole("spinbutton", { name: "Lecture Hours" }), { target: { value: "3" } });
}

test("StrictMode removes the setup fragment once and retains its key across rerenders", async () => {
  const key = "a".repeat(43);
  window.history.replaceState(null, "", `/login#setup-key=${key}`);
  const replace = vi.spyOn(window.history, "replaceState");
  api.getAccountStatus.mockResolvedValue({ setup_required: true });
  api.setupAdmin.mockRejectedValue(new Error("Synthetic failure"));
  render(<StrictMode><MemoryRouter><LoginPage /></MemoryRouter></StrictMode>);
  fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "synthetic-admin" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "synthetic-password" } });
  const button = screen.getByRole("button", { name: "Create Administrator" });
  fireEvent.click(button);
  await screen.findByRole("alert");
  fireEvent.click(button);
  await waitFor(() => expect(api.setupAdmin).toHaveBeenCalledTimes(2));
  expect(api.setupAdmin).toHaveBeenLastCalledWith("synthetic-admin", "synthetic-password", key);
  expect(replace).toHaveBeenCalledTimes(1);
  expect(window.location.hash).toBe("");
  replace.mockRestore();
});

test("disable and revoke require explicit confirmation; Escape and Cancel never write", async () => {
  api.setUserActive.mockResolvedValue({ ...staff, is_active: false });
  render(<MemoryRouter><AccountSecurityPage /></MemoryRouter>);
  const row = (await screen.findByText(staff.username)).closest(".export-row")!;
  const disable = within(row as HTMLElement).getByRole("button", { name: "Disable" });
  disable.focus();
  fireEvent.click(disable);
  const dialog = await screen.findByRole("dialog", { name: "Disable account?" });
  expect(api.setUserActive).not.toHaveBeenCalled();
  fireEvent(dialog, new Event("cancel", { cancelable: true }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(document.activeElement).toBe(disable);
  fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "Sign out sessions" }));
  fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
  expect(api.revokeUserSessions).not.toHaveBeenCalled();
  fireEvent.click(disable);
  fireEvent.click(await screen.findByRole("button", { name: "Disable account" }));
  await waitFor(() => expect(api.setUserActive).toHaveBeenCalledWith(staff.id, false));
});

test("password reset confirmation names the target and does not contain the password", async () => {
  render(<MemoryRouter><AccountSecurityPage /></MemoryRouter>);
  await screen.findByText(staff.username);
  fireEvent.click(screen.getByText("Reset an account password"));
  const form = screen.getByRole("button", { name: "Save Temporary Password" }).closest("form")!;
  fireEvent.change(within(form).getByLabelText("Temporary password"), { target: { value: "private-synthetic-password" } });
  fireEvent.submit(form);
  const dialog = await screen.findByRole("dialog", { name: "Reset account password?" });
  expect(dialog.textContent).toContain(staff.username);
  expect(dialog.textContent).not.toContain("private-synthetic-password");
  expect(api.resetUserPassword).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole("button", { name: "Reset password" }));
  await waitFor(() => expect(api.resetUserPassword).toHaveBeenCalledWith(staff.id, "private-synthetic-password"));
});

test("incorrect current password is associated with the correction field", async () => {
  api.changePassword.mockRejectedValue(new Error("Your current password is incorrect."));
  render(<MemoryRouter><AccountSecurityPage /></MemoryRouter>);
  const current = screen.getByLabelText("Current password");
  fireEvent.change(current, { target: { value: "wrong-synthetic-password" } });
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: "new-synthetic-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Change Password" }));
  await waitFor(() => expect(current.getAttribute("aria-invalid")).toBe("true"));
  const message = document.getElementById(current.getAttribute("aria-describedby")!);
  expect(message?.textContent).toContain("current password is incorrect");
  expect(api.clearSession).not.toHaveBeenCalled();
});

function InputExample({ done }: { done: (value: string | null) => void }) {
  const { requestInput, actionDialog } = useActionDialog();
  return <main><h1>Synthetic workload</h1><button onClick={() => void requestInput("The reason is retained in workload history.", "Reopen workload?", "Reopen workload", "Reason for reopening").then(done)}>Reopen</button>{actionDialog}</main>;
}
test("reason dialog rejects whitespace, has a labelled field, and passes axe structural checks", async () => {
  const done = vi.fn();
  render(<InputExample done={done} />);
  fireEvent.click(screen.getByRole("button", { name: "Reopen" }));
  const dialog = await screen.findByRole("dialog", { name: "Reopen workload?" });
  const input = within(dialog).getByRole("textbox", { name: "Reason for reopening" });
  expect(document.activeElement).toBe(input);
  fireEvent.change(input, { target: { value: "   " } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Reopen workload" }));
  expect(done).not.toHaveBeenCalled();
  expect(input.getAttribute("aria-invalid")).toBe("true");
  const result = await axe.run(dialog, { rules: { "color-contrast": { enabled: false } } });
  expect(result.violations.map(item => item.id)).toEqual([]);
  fireEvent.change(input, { target: { value: " Correct a course section " } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Reopen workload" }));
  await waitFor(() => expect(done).toHaveBeenCalledWith("Correct a course section"));
});

test("blank hours are invalid rather than silently becoming zero", async () => {
  openWorkload();
  await fillAssignment("SYN101");
  const hours = screen.getByRole("spinbutton", { name: "Laboratory Hours" });
  fireEvent.change(hours, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Save Assignment" }));
  expect(hours.getAttribute("aria-invalid")).toBe("true");
  expect(document.getElementById(hours.getAttribute("aria-describedby")!)?.textContent).toContain("Use 0");
  expect(api.createWorkload).not.toHaveBeenCalled();
  fireEvent.change(hours, { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: "Save Assignment" }));
  await screen.findByRole("button", { name: "Add Assignment" });
  expect(screen.getByText("SYN101")).toBeTruthy();
});

test("future academic years are validated without a known-calendar restriction; row identity survives deletion", async () => {
  openWorkload();
  await fillAssignment("SYN101");
  fireEvent.click(screen.getByRole("button", { name: "Save Assignment" }));
  await fillAssignment("SYN102");
  fireEvent.click(screen.getByRole("button", { name: "Save Assignment" }));
  const retainedRow = screen.getByText("SYN102").closest("tr");
  fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);
  expect(screen.getByText("SYN102").closest("tr")).toBe(retainedRow);
  fireEvent.change(screen.getByRole("combobox", { name: "Faculty Member" }), { target: { value: String(faculty.id) } });
  fireEvent.change(screen.getByRole("textbox", { name: "Academic Year" }), { target: { value: "2030-2032" } });
  fireEvent.click(screen.getByRole("button", { name: "Save Workload" }));
  expect(api.createWorkload).not.toHaveBeenCalled();
  const year = screen.getByDisplayValue("2030-2032");
  expect(year.getAttribute("aria-invalid")).toBe("true");
  fireEvent.change(year, { target: { value: "2030-2031" } });
  fireEvent.click(screen.getByRole("button", { name: "Save Workload" }));
  await waitFor(() => expect(api.createWorkload).toHaveBeenCalledTimes(1));
  const payload = api.createWorkload.mock.calls[0][0];
  expect(payload.academic_year).toBe("2030-2031");
  expect(payload.assignments).toEqual([{ course_code: "SYN102", course_title: "Synthetic course", year_section: "BSAM 1A", lecture_hours: 3, laboratory_hours: 0 }]);
});
