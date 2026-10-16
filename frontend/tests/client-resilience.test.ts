import { afterEach, expect, test, vi } from "vitest";
import { request, saveSession, getCurrentUser } from "../src/api/client";
import { administrator } from "./fixtures";

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

test("malformed successful responses give an actionable message without retrying writes", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("<html>wrong service</html>"));
  await expect(request("/synthetic", { method: "POST", body: "{}" })).rejects.toThrow("Check the record");
  expect(fetcher).toHaveBeenCalledTimes(1);
});

test("hung requests are bounded and preserve credentials", async () => {
  vi.useFakeTimers();
  saveSession({ token: "synthetic-token", user: administrator });
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) =>
    new Promise((_resolve, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))));
  const operation = request("/synthetic", { method: "PUT" });
  const assertion = expect(operation).rejects.toThrow("timed out");
  await vi.advanceTimersByTimeAsync(60_000);
  await assertion;
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(getCurrentUser()?.username).toBe(administrator.username);
  expect(vi.getTimerCount()).toBe(0);
});

test("caller cancellation aborts the underlying request", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) =>
    new Promise((_resolve, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))));
  const controller = new AbortController();
  const operation = request("/synthetic", { signal: controller.signal });
  controller.abort();
  await expect(operation).rejects.toThrow("cancelled");
});

test("invalid non-JSON errors retain session except on 401", async () => {
  saveSession({ token: "synthetic-token", user: administrator });
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("Unavailable", { status: 503 }));
  await expect(request("/synthetic")).rejects.toThrow();
  expect(getCurrentUser()?.username).toBe(administrator.username);
});
