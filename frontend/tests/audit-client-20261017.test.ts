import { afterEach, expect, test, vi } from "vitest";
import { downloadFile, getCurrentUser, readSession, request, saveSession } from "../src/api/client";
import { downloadDatabaseBackup, downloadExport } from "../src/api";
import { downloadMonthlySalaryProjection } from "../src/api/expenses";
import { downloadWorkloadReview } from "../src/api/workloads";
import { administrator } from "./fixtures";

afterEach(() => vi.restoreAllMocks());

test.each(["broken-json", "null", "[]", '{"token":4,"user":{}}', JSON.stringify({ token: "token", user: { ...administrator, username: null } })])("invalid stored session %s is discarded without a render error", stored => {
  sessionStorage.setItem("cathedra-faculty-session", stored);
  expect(readSession()).toBeNull();
  expect(getCurrentUser()).toBeNull();
  expect(sessionStorage.getItem("cathedra-faculty-session")).toBeNull();
});

test.each([400, 401])("a bad current password (%s) keeps the session for correction", async status => {
  saveSession({ token: "synthetic-token", user: administrator });
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Your current password is incorrect." }), { status }));
  await expect(request("/auth/change-password", { method: "POST" })).rejects.toThrow("current password is incorrect");
  expect(getCurrentUser()?.id).toBe(administrator.id);
});

test("an expired session on the password endpoint still signs out", async () => {
  saveSession({ token: "synthetic-token", user: administrator });
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Session expired" }), { status: 401 }));
  await expect(request("/auth/change-password", { method: "POST" })).rejects.toThrow("Session expired");
  expect(getCurrentUser()).toBeNull();
});

test.each([
  () => downloadDatabaseBackup("synthetic.db"),
  () => downloadExport("faculty-profiles", "synthetic.csv"),
  () => downloadMonthlySalaryProjection(),
  () => downloadWorkloadReview(),
])("downloads recover from corrupt sessions and expired credentials", async download => {
  sessionStorage.setItem("cathedra-faculty-session", "broken-json");
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Sign in again" }), { status: 401 }));
  await expect(download()).rejects.toThrow("Sign in again");
  expect(sessionStorage.getItem("cathedra-faculty-session")).toBeNull();
  expect(fetcher.mock.calls[0][1]?.headers).toEqual({});
});

test("successful downloads release their object URL and temporary link", async () => {
  saveSession({ token: "synthetic-token", user: administrator });
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("synthetic,data"));
  const create = vi.fn().mockReturnValue("blob:synthetic");
  const revoke = vi.fn();
  const originalURL = globalThis.URL;
  vi.stubGlobal("URL", class extends URL { static createObjectURL = create; static revokeObjectURL = revoke; });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  try {
    await downloadFile("/synthetic.csv", "synthetic.csv");
    expect(click).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith("blob:synthetic");
    expect(document.querySelector("a[download]")).toBeNull();
  } finally { vi.stubGlobal("URL", originalURL); }
});
