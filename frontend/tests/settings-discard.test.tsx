import { beforeEach, expect, test, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { ReactElement } from "react";
import FacultyProfilesPage from "../src/pages/FacultyProfilesPage";
import OfficePeriodPage from "../src/pages/OfficePeriodPage";
import QualificationRatesPage from "../src/pages/QualificationRatesPage";
import { administrator } from "./fixtures";

const api = vi.hoisted(() => ({
  getCurrentUser: vi.fn(), getFacultyProfiles: vi.fn(), getSalaryScale: vi.fn(), createFacultyProfile: vi.fn(), deleteFacultyProfile: vi.fn(),
  getActiveProjectionPeriod: vi.fn(), getSemesterOverloadBudgets: vi.fn(), saveActiveProjectionPeriod: vi.fn(), saveSemesterOverloadBudget: vi.fn(), deleteSemesterOverloadBudget: vi.fn(),
  getQualificationDraft: vi.fn(), saveQualificationDraft: vi.fn(),
}));
vi.mock("../src/api", () => api);

function openPage(element: ReactElement) {
  render(<RouterProvider router={createMemoryRouter([{ path: "*", element }], { initialEntries: ["/test"] })} />);
}

beforeEach(() => {
  vi.resetAllMocks();
  api.getCurrentUser.mockReturnValue(administrator);
});

test("directory creation cancellation keeps edits until explicitly discarded", async () => {
  api.getFacultyProfiles.mockResolvedValue({ items: [], total: 0 });
  api.getSalaryScale.mockResolvedValue({ grades: [], rank_mappings: [] });
  openPage(<FacultyProfilesPage />);
  fireEvent.click(screen.getByRole("button", { name: "Add Faculty" }));
  const name = await screen.findByRole("textbox", { name: "Name *" });
  fireEvent.change(name, { target: { value: "Unsaved demonstration faculty" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(await screen.findByRole("button", { name: "Keep editing" }));
  expect((name as HTMLInputElement).value).toBe("Unsaved demonstration faculty");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Save Faculty" })).toBeNull());
  expect(api.createFacultyProfile).not.toHaveBeenCalled();
});

test("budget-period change preserves unsaved amount when cancelled", async () => {
  api.getActiveProjectionPeriod.mockResolvedValue({ academic_year: "2026-2027", term: "First Semester" });
  api.getSemesterOverloadBudgets.mockResolvedValue([]);
  openPage(<OfficePeriodPage />);
  const amount = await screen.findByRole("spinbutton", { name: "Overload budget (₱)" });
  fireEvent.change(amount, { target: { value: "1234" } });
  const semester = within(screen.getByRole("region", { name: "Semester overload budgets" })).getByRole("combobox", { name: "Semester" });
  fireEvent.change(semester, { target: { value: "Second Semester" } });
  fireEvent.click(await screen.findByRole("button", { name: "Keep editing" }));
  expect((amount as HTMLInputElement).value).toBe("1234");
  expect((semester as HTMLSelectElement).value).toBe("First Semester");
  fireEvent.change(semester, { target: { value: "Second Semester" } });
  fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }));
  await waitFor(() => expect((semester as HTMLSelectElement).value).toBe("Second Semester"));
  expect((amount as HTMLInputElement).value).toBe("");
  expect(api.saveSemesterOverloadBudget).not.toHaveBeenCalled();
});

test("qualification reload asks before losing local draft changes", async () => {
  api.getQualificationDraft.mockResolvedValue({ revision: 0, combination_rule: "Unconfirmed", rates: [], status: "Draft — not applied", applies_to: "External Part-time", updated_at: null, updated_by: null });
  openPage(<QualificationRatesPage />);
  const rule = await screen.findByRole("combobox", { name: "Proposed combination rule" });
  fireEvent.change(rule, { target: { value: "Combine additions" } });
  fireEvent.click(screen.getByRole("button", { name: "Reload saved draft" }));
  fireEvent.click(await screen.findByRole("button", { name: "Keep editing" }));
  expect((rule as HTMLSelectElement).value).toBe("Combine additions");
  expect(api.getQualificationDraft).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Reload saved draft" }));
  fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }));
  await waitFor(() => expect((screen.getByRole("combobox", { name: "Proposed combination rule" }) as HTMLSelectElement).value).toBe("Unconfirmed"));
  expect(api.getQualificationDraft).toHaveBeenCalledTimes(2);
  expect(api.saveQualificationDraft).not.toHaveBeenCalled();
});

test("cancelling a qualification editor preserves the existing draft row", async () => {
  api.getQualificationDraft.mockResolvedValue({ revision: 1, combination_rule: "Unconfirmed", rates: [{ category: "Professional credential", qualification: "CPA", hourly_addition: 0, effective_from: "2026-10-01", effective_to: null, reference: "Demonstration" }], status: "Draft — not applied", applies_to: "External Part-time", updated_at: null, updated_by: null });
  openPage(<QualificationRatesPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  const qualification = screen.getByLabelText("Qualification name");
  fireEvent.change(qualification, { target: { value: "Engineer" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancel rate" }));
  fireEvent.click(await screen.findByRole("button", { name: "Keep editing" }));
  expect((qualification as HTMLInputElement).value).toBe("Engineer");
  fireEvent.click(screen.getByRole("button", { name: "Cancel rate" }));
  fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }));
  await waitFor(() => expect(screen.queryByLabelText("Qualification name")).toBeNull());
  expect(screen.getByText("CPA", { exact: true })).toBeTruthy();
  expect(api.saveQualificationDraft).not.toHaveBeenCalled();
});
