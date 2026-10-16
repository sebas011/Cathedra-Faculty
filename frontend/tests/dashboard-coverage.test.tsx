import { beforeEach, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import DashboardPage from "../src/pages/DashboardPage";
import { administrator } from "./fixtures";

const api = vi.hoisted(() => ({
  getCurrentUser: vi.fn(), getWorkloadSummary: vi.fn(), getWorkloadReview: vi.fn(),
  getProjectionReadiness: vi.fn(), getActiveProjectionPeriod: vi.fn(),
  getMonthlySalaryProjection: vi.fn(), getSemesterOverloadBudgets: vi.fn(),
}));
vi.mock("../src/api", () => api);

beforeEach(() => {
  vi.resetAllMocks();
  api.getCurrentUser.mockReturnValue(administrator);
  api.getWorkloadSummary.mockResolvedValue({ workloads: 0, assignments: 0, weekly_hours: 0 });
  api.getWorkloadReview.mockResolvedValue({ items: [] });
  api.getProjectionReadiness.mockResolvedValue({ items: [] });
  api.getActiveProjectionPeriod.mockResolvedValue({ academic_year: "2026-2027", term: "First Semester" });
  api.getSemesterOverloadBudgets.mockResolvedValue([{ academic_year: "2026-2027", term: "First Semester", amount: 1000 }]);
});

test.each([false, true])("dashboard distinguishes confirmed zero from missing coverage (provisional=%s)", async (provisional) => {
  api.getMonthlySalaryProjection.mockResolvedValue({
    period: "semester", total_period_salary: 0, combined_period_estimate: 0,
    teaching_cost: { total_term_pay: 0, workloads: 0 }, teaching_details: [],
    filters: { academic_year: "2026-2027", term: "First Semester" },
    overload_coverage: { provisional }, college_totals: [], warnings: [],
  });
  render(<MemoryRouter><DashboardPage /></MemoryRouter>);
  const label = await screen.findByText("Projected overload compensation");
  await waitFor(() => expect(label.closest("article")?.querySelector("strong")?.textContent)
    .toBe(provisional ? "Not available" : "₱0.00"));
  const remaining = screen.getByText(provisional ? "Indicative budget remaining" : "budget remaining");
  expect(remaining.closest("article")?.querySelector("strong")?.textContent)
    .toBe(provisional ? "Not available" : "₱1,000.00");
});
