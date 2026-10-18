import { apiErrorMessage } from "../apiErrors";
import type { SessionResult } from "../types";
import { product } from "../product";

export const API = import.meta.env.DEV ? "http://127.0.0.1:8102/api/v1" : "/api/v1";
const sessionKey = `cathedra-${product}-session`;
export const releaseVersion = import.meta.env.VITE_CATHEDRA_VERSION;
export const sessionChangedEvent = "cathedra-session-changed";
export const getSessionToken = () => sessionStorage.getItem(sessionKey);
localStorage.removeItem(sessionKey);

export const saveSession = (result: SessionResult) => {
  sessionStorage.setItem(sessionKey, JSON.stringify(result));
  window.dispatchEvent(new Event(sessionChangedEvent));
};
export const clearSession = () => {
  sessionStorage.removeItem(sessionKey);
  localStorage.removeItem(sessionKey);
  Object.keys(sessionStorage).filter((key) => key.startsWith("cathedra-directory:")).forEach((key) => sessionStorage.removeItem(key));
  window.dispatchEvent(new Event(sessionChangedEvent));
};
export const readSession = (): SessionResult | null => {
  const stored = getSessionToken();
  if (!stored) return null;
  try {
    const value: unknown = JSON.parse(stored);
    if (typeof value !== "object" || value === null || !("token" in value) || typeof value.token !== "string" || !value.token.trim() || !("user" in value)) throw new Error("Invalid session");
    const user = value.user;
    if (typeof user !== "object" || user === null || !("id" in user) || !Number.isSafeInteger(user.id) || !("username" in user) || typeof user.username !== "string" || !user.username || !("role" in user) || !["admin", "staff"].includes(String(user.role)) || !("is_active" in user) || user.is_active !== true || !("must_change_password" in user) || typeof user.must_change_password !== "boolean") throw new Error("Invalid session");
    return value as SessionResult;
  } catch {
    // Reading during a React render must not dispatch a state update. Requests
    // notify the shell if they discover that its stored credentials are invalid.
    sessionStorage.removeItem(sessionKey);
    return null;
  }
};
export const getCurrentUser = () => readSession()?.user ?? null;

async function checkResponse(response: Response, path: string): Promise<void> {
  if (response.ok) return;
  const body = await response.json().catch(() => null);
  const incorrectCurrentPassword = path === "/auth/change-password" && body?.detail === "Your current password is incorrect.";
  if (response.status === 401 && !incorrectCurrentPassword) clearSession();
  throw new Error(apiErrorMessage(body?.detail, response.status));
}

export async function timedFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  const caller = init?.signal;
  caller?.addEventListener("abort", abort, { once: true });
  if (caller?.aborted) controller.abort();
  const timeout = window.setTimeout(abort, 60_000);
  try {
    const response = await fetch(input, { ...init, signal: controller.signal });
    const body = await response.arrayBuffer();
    return new Response(response.status === 204 || response.status === 205 || response.status === 304 ? null : body, {
      status: response.status, statusText: response.statusText, headers: response.headers,
    });
  } catch {
    throw new Error(controller.signal.aborted
      ? "The request was cancelled or timed out. Changes have not been confirmed as saved. Check the record before retrying."
      : "Cathedra could not reach the local service. Changes have not been confirmed as saved. Check the record before retrying.");
  } finally {
    window.clearTimeout(timeout);
    caller?.removeEventListener("abort", abort);
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const stored = getSessionToken();
  const token = readSession()?.token;
  if (stored && !token) clearSession();
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await timedFetch(`${API}${path}`, { ...init, headers });
  await checkResponse(response, path);
  if (response.status === 204) return undefined as T;
  try { return await response.json() as T; }
  catch { throw new Error("The local service returned an unexpected response. Changes have not been confirmed as saved. Check the record before retrying."); }
}

export async function downloadFile(path: string, filename: string): Promise<void> {
  const stored = getSessionToken();
  const token = readSession()?.token;
  if (stored && !token) clearSession();
  const response = await timedFetch(`${API}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  await checkResponse(response, path);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  try {
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
  } finally {
    link.remove();
    URL.revokeObjectURL(url);
  }
}
