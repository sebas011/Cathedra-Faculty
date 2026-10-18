import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import axe from "axe-core";
import LoginPage from "../src/pages/LoginPage";
import FacultyProfilesPage from "../src/pages/FacultyProfilesPage";
import AdminAccess from "../src/components/AdminAccess";
import { administrator, faculty } from "./fixtures";

const api = vi.hoisted(() => ({ getAccountStatus: vi.fn(), setupAdmin: vi.fn(), signIn: vi.fn(), saveSession: vi.fn(), getCurrentUser: vi.fn(), getFacultyProfiles: vi.fn(), getSalaryScale: vi.fn(), createFacultyProfile: vi.fn(), deleteFacultyProfile: vi.fn() }));
vi.mock("../src/api", () => api);

beforeEach(() => {
  vi.resetAllMocks();
  window.history.replaceState(null, "", "/login");
  api.getCurrentUser.mockReturnValue(administrator);
});

function openPage(element: React.ReactElement) {
  render(<RouterProvider router={createMemoryRouter([{ path: "*", element }])} />);
}

test("first setup takes its private fragment out of the URL and never persists it", async () => {
  const key = "a".repeat(43);
  window.history.replaceState(null, "", `/login#setup-key=${key}`);
  api.getAccountStatus.mockResolvedValue({ setup_required: true });
  let finish!: () => void;
  api.setupAdmin.mockReturnValue(new Promise(resolve => { finish = () => resolve({ token: "session", user: administrator }); }));
  openPage(<LoginPage />);
  await screen.findByRole("button", { name: "Create Administrator" });
  expect(window.location.hash).toBe("");
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "owner-admin" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "owner-password-123" } });
  const form = screen.getByLabelText("Username").closest("form")!;
  fireEvent.submit(form);
  fireEvent.submit(form);
  expect(api.setupAdmin).toHaveBeenCalledTimes(1);
  expect(api.setupAdmin).toHaveBeenCalledWith("owner-admin", "owner-password-123", key);
  await act(async () => { finish(); });
  expect(api.saveSession).toHaveBeenCalledTimes(1);
});

test("an ordinary first-setup URL cannot submit a new administrator", async () => {
  api.getAccountStatus.mockResolvedValue({ setup_required: true });
  openPage(<LoginPage />);
  await screen.findByRole("button", { name: "Create Administrator" });
  fireEvent.submit(screen.getByLabelText("Username").closest("form")!);
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Open Cathedra from its desktop shortcut to finish first-time setup.");
  expect(api.setupAdmin).not.toHaveBeenCalled();
});

test("staff expense entry explains access and does not mount the expense form", () => {
  api.getCurrentUser.mockReturnValue({ ...administrator, role: "staff" });
  const mounted = vi.fn();
  function ExpenseForm() { mounted(); return <p>Projection filters</p>; }
  openPage(<AdminAccess><ExpenseForm /></AdminAccess>);
  expect(screen.getByRole("heading", { name: "Administrator access required" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "Return to dashboard" }).getAttribute("href")).toBe("/");
  expect(mounted).not.toHaveBeenCalled();
});

test("administrator expense entry mounts its normal content", () => {
  openPage(<AdminAccess><p>Projection filters</p></AdminAccess>);
  expect(screen.getByText("Projection filters")).toBeTruthy();
});

test("repeated faculty submits send one request while saving and permit retry after failure", async () => {
  api.getFacultyProfiles.mockResolvedValue({ items: [], total: 0, summary: {} });
  api.getSalaryScale.mockResolvedValue({ grades: [], rank_mappings: [] });
  let reject!: (error: Error) => void;
  api.createFacultyProfile.mockReturnValueOnce(new Promise((_resolve, rejectRequest) => { reject = rejectRequest; })).mockResolvedValue(faculty);
  openPage(<FacultyProfilesPage />);
  await screen.findByText("No faculty profiles found.");
  fireEvent.click(screen.getByRole("button", { name: "Add Faculty" }));
  fireEvent.change(await screen.findByLabelText("Name *"), { target: { value: "New Faculty" } });
  fireEvent.change(screen.getByLabelText("Rank / position *"), { target: { value: "Instructor I" } });
  fireEvent.change(screen.getByLabelText("Program *"), { target: { value: "BSAM" } });
  const form = screen.getByLabelText("Name *").closest("form")!;
  fireEvent.submit(form);
  fireEvent.submit(form);
  expect(api.createFacultyProfile).toHaveBeenCalledTimes(1);
  expect((screen.getByRole("button", { name: "Saving…" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(true);
  await act(async () => { reject(new Error("Temporary failure")); });
  await screen.findByText("Temporary failure");
  fireEvent.submit(form);
  await waitFor(() => expect(api.createFacultyProfile).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.queryByRole("heading", { name: "New faculty profile" })).toBeNull());
});

test("faculty whitespace validation identifies each correction field accessibly", async () => {
  api.getFacultyProfiles.mockResolvedValue({ items: [], total: 0, summary: {} });
  api.getSalaryScale.mockResolvedValue({ grades: [], rank_mappings: [] });
  openPage(<FacultyProfilesPage />);
  await screen.findByText("No faculty profiles found.");
  fireEvent.click(screen.getByRole("button", { name: "Add Faculty" }));
  const fields = [await screen.findByLabelText("Name *"), screen.getByLabelText("Rank / position *"), screen.getByLabelText("Program *")];
  fields.forEach(field => fireEvent.change(field, { target: { value: "   " } }));
  const form = fields[0].closest("form")!;
  fireEvent.submit(form);
  expect(api.createFacultyProfile).not.toHaveBeenCalled();
  fields.forEach(field => {
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(field.getAttribute("aria-describedby")!)?.textContent).toContain("enter a value");
  });
  const result = await axe.run(form, { rules: { "color-contrast": { enabled: false } } });
  expect(result.violations.map(item => item.id)).toEqual([]);
});
