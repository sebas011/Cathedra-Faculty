import { beforeEach, expect, test, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import RecentActivity from "../src/components/RecentActivity";
import WorkspaceSearch from "../src/components/WorkspaceSearch";

const api = vi.hoisted(() => ({ getActivityPage: vi.fn() }));
vi.mock("../src/api", () => api);
beforeEach(() => vi.resetAllMocks());

function Location() { return <output aria-label="Current path">{useLocation().pathname}</output>; }

test("page navigation opens by keyboard, filters destinations, and follows the selected route", () => {
  render(<MemoryRouter><WorkspaceSearch destinations={[{ to: "/faculty-profiles", label: "Faculty profiles" }, { to: "/workload", label: "Workload" }]} /><Location /></MemoryRouter>);
  fireEvent.keyDown(document, { key: "k", ctrlKey: true });
  const dialog = screen.getByRole("dialog", { name: "Find your workspace" });
  const input = within(dialog).getByLabelText("Search pages");
  expect(document.activeElement).toBe(input);
  fireEvent.change(input, { target: { value: "faculty" } });
  expect(within(dialog).queryByRole("link", { name: "Workload" })).toBeNull();
  fireEvent.click(within(dialog).getByRole("link", { name: "Faculty profiles" }));
  expect(screen.getByLabelText("Current path").textContent).toBe("/faculty-profiles");
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("page navigation exposes empty results and closes on Escape", () => {
  render(<MemoryRouter><WorkspaceSearch destinations={[{ to: "/workload", label: "Workload" }]} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "Jump to a page" }));
  fireEvent.change(screen.getByLabelText("Search pages"), { target: { value: "unmatched" } });
  expect(screen.getByRole("status").textContent).toContain("No pages match");
  fireEvent(screen.getByRole("dialog"), new Event("cancel", { bubbles: false, cancelable: true }));
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("activity fetch failures can be retried and UTC timestamps stay unambiguous", async () => {
  api.getActivityPage.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ items: [{ id: 1, action: "Workload saved", username: "Demo admin", area: "Workload", created_at: "2026-10-24T08:30:00" }] });
  render(<MemoryRouter><RecentActivity /></MemoryRouter>);
  expect(screen.getByRole("status").textContent).toContain("Loading");
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Retry activity" }));
  await screen.findByText("Workload saved");
  expect(document.querySelector("time")?.dateTime).toBe("2026-10-24T08:30:00Z");
  expect(api.getActivityPage).toHaveBeenCalledTimes(2);
});

test("activity feed distinguishes no saved events and limits the summary to five", async () => {
  api.getActivityPage.mockResolvedValueOnce({ items: [] });
  const view = render(<MemoryRouter><RecentActivity /></MemoryRouter>);
  await screen.findByText("Your office journal starts here");
  view.unmount();
  api.getActivityPage.mockResolvedValueOnce({ items: Array.from({ length: 7 }, (_, id) => ({ id, action: `Event ${id}`, username: null, area: "Office", created_at: "2026-10-24T08:30:00Z" })) });
  render(<MemoryRouter><RecentActivity /></MemoryRouter>);
  await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(5));
  expect(screen.queryByText("Event 5")).toBeNull();
});
