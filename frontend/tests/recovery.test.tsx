import { beforeEach, describe, expect, test, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { ReactElement } from "react";
import CompensationRulesPage from "../src/pages/CompensationRulesPage";
import FacultyProfileDetailPage from "../src/pages/FacultyProfileDetailPage";
import AccountSecurityPage from "../src/pages/AccountSecurityPage";
import { administrator, faculty, rules } from "./fixtures";
import axe from "axe-core";

const api = vi.hoisted(() => ({
  getCurrentUser: vi.fn(), getWorkloadCostSettings: vi.fn(), updateWorkloadCostSettings: vi.fn(),
  getFacultyProfile: vi.fn(), getFacultyProfileWorkloads: vi.fn(), getSalaryScale: vi.fn(), updateFacultyProfile: vi.fn(),
  getUsers: vi.fn(), changePassword: vi.fn(), clearSession: vi.fn(), createUser: vi.fn(),
  resetUserPassword: vi.fn(), revokeUserSessions: vi.fn(), setUserActive: vi.fn(),
}));
vi.mock("../src/api", () => api);

function openPage(element: ReactElement, path = "/test") {
  const router = createMemoryRouter([{ path: "/:id", element }], { initialEntries: [path] });
  render(<RouterProvider router={router} />);
}

beforeEach(() => {
  vi.resetAllMocks();
  api.getCurrentUser.mockReturnValue(administrator);
  api.getSalaryScale.mockResolvedValue({ grades: [], rank_mappings: [] });
  api.getFacultyProfileWorkloads.mockResolvedValue([]);
});

describe("load recovery", () => {
  test("compensation rules retry a failed load", async () => {
    api.getWorkloadCostSettings.mockRejectedValueOnce(new Error("Rules unavailable")).mockResolvedValue(rules);
    openPage(<CompensationRulesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect((await screen.findByRole("spinbutton", { name: "First semester weeks" }) as HTMLInputElement).value).toBe("18");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("a save failure preserves edited compensation inputs", async () => {
    api.getWorkloadCostSettings.mockResolvedValue(rules);
    api.updateWorkloadCostSettings.mockRejectedValue(new Error("Save unavailable"));
    openPage(<CompensationRulesPage />);
    const input = await screen.findByRole("spinbutton", { name: "First semester weeks" });
    fireEvent.change(input, { target: { value: "19" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Rules" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Save unavailable");
    expect((input as HTMLInputElement).value).toBe("19");
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(api.getWorkloadCostSettings).toHaveBeenCalledTimes(1);
  });

  test("faculty profile can retry without exposing an empty editor", async () => {
    api.getFacultyProfile.mockRejectedValueOnce(new Error("Profile unavailable")).mockResolvedValue(faculty);
    openPage(<FacultyProfileDetailPage />, "/1");
    expect(screen.queryByRole("button", { name: "Edit Profile" })).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: faculty.name })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("history failure is not described as no workload and retries independently", async () => {
    api.getFacultyProfile.mockResolvedValue(faculty);
    api.getFacultyProfileWorkloads.mockRejectedValueOnce(new Error("History unavailable")).mockResolvedValue([]);
    openPage(<FacultyProfileDetailPage />, "/1");
    const retry = await screen.findByRole("button", { name: "Retry workload history" });
    expect(screen.queryByText("No workload or teaching compensation has been recorded yet.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Edit Profile" }));
    const name = screen.getByRole("textbox", { name: "Name" });
    fireEvent.change(name, { target: { value: "Unsaved demonstration name" } });
    fireEvent.click(retry);
    await screen.findByText("No workload or teaching compensation has been recorded yet.");
    expect((name as HTMLInputElement).value).toBe("Unsaved demonstration name");
    expect(api.getFacultyProfile).toHaveBeenCalledTimes(1);
  });

  test("account retry preserves password input and does not submit credentials", async () => {
    api.getUsers.mockRejectedValueOnce(new Error("Accounts unavailable")).mockResolvedValue([administrator]);
    openPage(<AccountSecurityPage />);
    const current = screen.getByLabelText("Current password");
    fireEvent.change(current, { target: { value: "unsaved-test-input" } });
    fireEvent.click(await screen.findByRole("button", { name: "Retry accounts" }));
    await waitFor(() => expect(screen.queryByText("Accounts unavailable")).toBeNull());
    expect((current as HTMLInputElement).value).toBe("unsaved-test-input");
    expect(api.changePassword).not.toHaveBeenCalled();
    expect(api.createUser).not.toHaveBeenCalled();
  });
});

test("failed faculty saves retain the editable profile and unsaved input", async () => {
  api.getFacultyProfile.mockResolvedValue(faculty);
  api.updateFacultyProfile.mockRejectedValue(new Error("Profile save unavailable"));
  openPage(<FacultyProfileDetailPage />, "/1");
  fireEvent.click(await screen.findByRole("button", { name: "Edit Profile" }));
  const name = screen.getByRole("textbox", { name: "Name" });
  fireEvent.change(name, { target: { value: "Unsaved demonstration name" } });
  fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Profile save unavailable");
  expect((name as HTMLInputElement).value).toBe("Unsaved demonstration name");
  expect(screen.getByRole("button", { name: "Save Changes" })).toBeTruthy();
});

test("confirmed rule discard restores the saved values without a mutation", async () => {
  api.getWorkloadCostSettings.mockResolvedValue(rules);
  openPage(<CompensationRulesPage />);
  const input = await screen.findByRole("spinbutton", { name: "First semester weeks" });
  fireEvent.change(input, { target: { value: "19" } });
  fireEvent.click(screen.getByRole("button", { name: "Discard Changes" }));
  fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }));
  await waitFor(() => expect((input as HTMLInputElement).value).toBe("18"));
  expect(api.updateWorkloadCostSettings).not.toHaveBeenCalled();
});

test("cancelled rule discard retains edits without a mutation", async () => {
  api.getWorkloadCostSettings.mockResolvedValue(rules);
  openPage(<CompensationRulesPage />);
  const input = await screen.findByRole("spinbutton", { name: "First semester weeks" });
  fireEvent.change(input, { target: { value: "19" } });
  fireEvent.click(screen.getByRole("button", { name: "Discard Changes" }));
  fireEvent.click(await screen.findByRole("button", { name: "Keep editing" }));
  expect((input as HTMLInputElement).value).toBe("19");
  expect(api.updateWorkloadCostSettings).not.toHaveBeenCalled();
});

test("faculty cancellation asks before discarding profile edits", async () => {
  api.getFacultyProfile.mockResolvedValue(faculty);
  openPage(<FacultyProfileDetailPage />, "/1");
  fireEvent.click(await screen.findByRole("button", { name: "Edit Profile" }));
  const name = screen.getByRole("textbox", { name: "Name" });
  fireEvent.change(name, { target: { value: "Unsaved demonstration name" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(await screen.findByRole("button", { name: "Keep editing" }));
  expect((name as HTMLInputElement).value).toBe("Unsaved demonstration name");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }));
  await screen.findByRole("button", { name: "Edit Profile" });
  expect(api.updateFacultyProfile).not.toHaveBeenCalled();
});

test("faculty workload history offers a named keyboard-scrollable region", async () => {
  api.getFacultyProfile.mockResolvedValue(faculty);
  api.getFacultyProfileWorkloads.mockResolvedValue([{
    id: 1, academic_year: "2026-2027", term: "First Semester", assignments: [],
    compensation_category: "Regular Faculty", highest_qualification: "Bachelor",
    professional_qualification: "None", compensation_hourly_rate: 100,
    estimated_teaching_pay_weekly: 200, estimated_teaching_pay_term: 3600,
    projection_weeks: 18, workflow_status: "Draft", total_weekly_hours: 23,
    overload_weekly_hours: 2,
  }]);
  openPage(<FacultyProfileDetailPage />, "/1");
  const region = await screen.findByRole("region", { name: "Faculty workload history" });
  expect(region.tabIndex).toBe(0);
  region.focus();
  expect(document.activeElement).toBe(region);
  expect(region.querySelectorAll('th[scope="col"]').length).toBe(6);
});

test.each(["rules", "faculty", "accounts"])("%s controls pass structural accessibility checks", async page => {
  api.getWorkloadCostSettings.mockResolvedValue(rules);
  api.getFacultyProfile.mockResolvedValue(faculty);
  api.getUsers.mockResolvedValue([administrator]);
  openPage(<main>{page === "rules" ? <CompensationRulesPage /> : page === "faculty" ? <FacultyProfileDetailPage /> : <AccountSecurityPage />}</main>, "/1");
  if (page === "rules") await screen.findByRole("button", { name: "Save Rules" });
  if (page === "faculty") fireEvent.click(await screen.findByRole("button", { name: "Edit Profile" }));
  if (page === "accounts") await screen.findByText(administrator.username);
  const result = await axe.run(document.body, { runOnly: { type: "rule", values: ["button-name", "link-name", "label", "aria-valid-attr", "aria-valid-attr-value", "aria-required-attr", "aria-roles", "heading-order"] } });
  expect(result.violations.map(item => `${item.id}: ${item.description}`)).toEqual([]);
});
