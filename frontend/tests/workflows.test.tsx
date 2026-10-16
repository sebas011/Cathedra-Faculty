import { beforeEach, expect, test, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { ReactElement } from "react";
import SavedProjectionsPage from "../src/pages/SavedProjectionsPage";
import ApprovedWorkloadSummaryPage from "../src/pages/ApprovedWorkloadSummaryPage";
import WorkloadFormPage from "../src/pages/WorkloadFormPage";
import WorkloadDetailPage from "../src/pages/WorkloadDetailPage";
import { approvedSummary, savedEstimates, faculty } from "./fixtures";

const api = vi.hoisted(() => ({
  getSavedProjection: vi.fn(), getSavedProjections: vi.fn(), getApprovedWorkloadSummary: vi.fn(),
  getFacultyProfileOptions: vi.fn(), getWorkload: vi.fn(), updateWorkload: vi.fn(), createWorkload: vi.fn(),
}));
vi.mock("../src/api", () => api);

function openPage(element: ReactElement, path = "/reports") {
  const router = createMemoryRouter([{ path: "*", element }], { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

beforeEach(() => { vi.resetAllMocks(); });

function openWorkloadDetails(overrides: Record<string, unknown> = {}) {
  api.getWorkload.mockResolvedValue({
    id: 1, faculty_name: "Demonstration Faculty", academic_year: "2026-2027",
    term: "First Semester", college: "CAS", department: "BSAM", workflow_status: "Draft",
    preparation_count: 1, total_weekly_hours: 24, regular_weekly_hours: 21,
    overload_weekly_hours: 3, compensation_category: "Regular Faculty",
    compensation_hourly_rate: 318.15, estimated_teaching_pay_weekly: 954.45,
    estimated_teaching_pay_term: 17180.17, projection_weeks: 18,
    reviewed_by: null, approved_by: null, assignments: [], ...overrides,
  });
  const router = createMemoryRouter([{ path: "/workload/:id", element: <WorkloadDetailPage /> }], { initialEntries: ["/workload/1"] });
  render(<RouterProvider router={router} />);
}

test("an unavailable teaching term estimate remains distinct from zero pay", async () => {
  openWorkloadDetails({ estimated_teaching_pay_term: null, projection_weeks: 0 });
  await screen.findByRole("heading", { name: "Rate and teaching estimate" });
  expect(screen.getByRole("status").textContent).toContain("does not mean zero teaching pay");
  expect(screen.getAllByText("Not configured").length).toBe(2);
  expect(screen.getByText(/954\.45/)).toBeTruthy();
});

test("approved workload details distinguish estimates and link to frozen approved figures", async () => {
  openWorkloadDetails({ workflow_status: "Approved", reviewed_by: "reviewer", approved_by: "approver" });
  await screen.findByRole("heading", { name: "Review and approval" });
  expect(screen.getByRole("link", { name: "View approved figures" }).getAttribute("href")).toBe("/workload/1/approval-record");
  expect(screen.queryByRole("link", { name: "Edit Workload" })).toBeNull();
  expect(screen.getByText(/Approved figures are recorded separately/)).toBeTruthy();
});

test("exactly 50 saved estimates do not offer an empty next page", async () => {
  api.getSavedProjections.mockResolvedValue(savedEstimates(50));
  openPage(<SavedProjectionsPage />);
  await screen.findAllByRole("link", { name: "View saved report" });
  expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
  expect(api.getSavedProjections).toHaveBeenCalledWith(0, 51);
  expect(screen.getByText("Closeout", { exact: true })).toBeTruthy();
});

test("51 estimates show 50 rows followed by one final row", async () => {
  const records = savedEstimates(51);
  api.getSavedProjections.mockImplementation((offset: number, limit: number) => Promise.resolve(records.slice(offset, offset + limit)));
  openPage(<SavedProjectionsPage />);
  expect((await screen.findAllByRole("link", { name: "View saved report" })).length).toBe(50);
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() => expect(screen.getAllByRole("link", { name: "View saved report" }).length).toBe(1));
  expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
  expect(api.getSavedProjections).toHaveBeenLastCalledWith(50, 51);
});

test("unapplied report filters disable printing until the matching report loads", async () => {
  api.getApprovedWorkloadSummary.mockResolvedValue(approvedSummary);
  const print = vi.spyOn(window, "print").mockImplementation(() => {});
  openPage(<ApprovedWorkloadSummaryPage />);
  const button = screen.getByRole("button", { name: "Print Summary" }) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.change(screen.getByRole("textbox", { name: "Academic year" }), { target: { value: "2026-2027" } });
  expect(button.disabled).toBe(true);
  fireEvent.click(button);
  expect(print).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Apply Filters" }));
  await waitFor(() => expect(button.disabled).toBe(false));
  expect(api.getApprovedWorkloadSummary).toHaveBeenLastCalledWith("2026-2027", "", "");
});

test("assignment cancellation preserves input until discard is confirmed", async () => {
  api.getFacultyProfileOptions.mockResolvedValue([faculty]);
  openPage(<WorkloadFormPage />, "/workload/new");
  fireEvent.click(await screen.findByRole("button", { name: "Add Assignment" }));
  const course = screen.getByRole("textbox", { name: "Course Code" });
  fireEvent.change(course, { target: { value: "DEMO101" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(await screen.findByRole("button", { name: "Keep editing" }));
  expect((course as HTMLInputElement).value).toBe("DEMO101");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }));
  await screen.findByRole("button", { name: "Add Assignment" });
  expect(api.createWorkload).not.toHaveBeenCalled();
});
