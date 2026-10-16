import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

class TestStorage implements Storage {
  [key: string]: unknown;
  get length() { return Object.keys(this).length; }
  clear() { Object.keys(this).forEach(key => this.removeItem(key)); }
  getItem(key: string) { return Object.hasOwn(this, key) ? String(this[key]) : null; }
  key(index: number) { return Object.keys(this)[index] ?? null; }
  removeItem(key: string) { delete this[key]; }
  setItem(key: string, value: string) { Object.defineProperty(this, key, { configurable: true, enumerable: true, writable: true, value: String(value) }); }
}

vi.stubGlobal("localStorage", new TestStorage());
vi.stubGlobal("sessionStorage", new TestStorage());


afterEach(() => {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
});
Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.setAttribute("open", ""); } });
Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.removeAttribute("open"); } });
Object.defineProperty(window, "scrollTo", { configurable: true, value() {} });
