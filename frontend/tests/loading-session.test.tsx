import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { useRecord } from "../src/hooks/useRecord";
import { getCurrentUser, request, saveSession, sessionChangedEvent } from "../src/api/client";
import { administrator } from "./fixtures";

test("a late record response cannot replace the newly selected profile", async () => {
  let finishFirst!: (value: string) => void;
  const first = new Promise<string>(resolve => { finishFirst = resolve; });
  const load = vi.fn().mockReturnValueOnce(first).mockResolvedValue("Second profile");
  const { result, rerender } = renderHook(({ id }) => useRecord(id, load, "Unavailable"), { initialProps: { id: "1" } });
  rerender({ id: "2" });
  await waitFor(() => expect(result.current.record).toBe("Second profile"));
  await act(async () => { finishFirst("Stale first profile"); await first; });
  expect(result.current.record).toBe("Second profile");
});

test("record retry clears the failed state and loads the requested record", async () => {
  const load = vi.fn().mockRejectedValueOnce(new Error("Unavailable")).mockResolvedValue("Recovered");
  const { result } = renderHook(() => useRecord("1", load, "Unavailable"));
  await waitFor(() => expect(result.current.error).toBe("Unavailable"));
  act(() => result.current.retry());
  await waitFor(() => expect(result.current.record).toBe("Recovered"));
  expect(result.current.error).toBe("");
});

test.each(["0", "-1", "invalid", "9007199254740992"])("invalid record ID %s never reaches the API", async id => {
  const load = vi.fn();
  const { result } = renderHook(() => useRecord(id, load, "Unavailable"));
  await waitFor(() => expect(result.current.error).toContain("invalid"));
  expect(load).not.toHaveBeenCalled();
});

test("expired sessions clear credentials and remembered directories", async () => {
  saveSession({ token: "synthetic-token", user: administrator });
  sessionStorage.setItem("cathedra-directory:faculty", "synthetic-filter");
  const changed = vi.fn();
  window.addEventListener(sessionChangedEvent, changed);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Session expired" }), { status: 401 }));
  try {
    await expect(request("/synthetic")).rejects.toThrow("Session expired");
    expect(getCurrentUser()).toBeNull();
    expect(sessionStorage.getItem("cathedra-directory:faculty")).toBeNull();
    expect(changed).toHaveBeenCalledTimes(1);
  } finally { window.removeEventListener(sessionChangedEvent, changed); }
});

test("temporary service failure preserves the signed-in session", async () => {
  saveSession({ token: "synthetic-token", user: administrator });
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Offline"));
  await expect(request("/synthetic")).rejects.toThrow("retry");
  expect(getCurrentUser()?.username).toBe(administrator.username);
});

test("malformed stored credentials recover without a render exception", async () => {
  sessionStorage.setItem("cathedra-faculty-session", "invalid-json");
  expect(getCurrentUser()).toBeNull();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
  await expect(request("/synthetic")).resolves.toBeUndefined();
  expect(sessionStorage.getItem("cathedra-faculty-session")).toBeNull();
});
