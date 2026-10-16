import { apiErrorMessage } from "../apiErrors";
import type { LocalUser, SessionResult } from "../types";
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
export const getCurrentUser = () => {
  try { return JSON.parse(getSessionToken() || "").user as LocalUser; }
  catch { return null; }
};

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
  let token = "";
  try { token = JSON.parse(getSessionToken() || "{}").token || ""; }
  catch { clearSession(); }
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await timedFetch(`${API}${path}`, { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    if (response.status === 401) clearSession();
    throw new Error(apiErrorMessage(body?.detail, response.status));
  }
  if (response.status === 204) return undefined as T;
  try { return await response.json() as T; }
  catch { throw new Error("The local service returned an unexpected response. Changes have not been confirmed as saved. Check the record before retrying."); }
}
