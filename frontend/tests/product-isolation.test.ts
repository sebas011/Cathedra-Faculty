import { expect, it } from "vitest";
import { product, productName } from "../src/product";
import { API, getCurrentUser, saveSession } from "../src/api/client";

it("uses Faculty-only identity, service address and saved sign-in", () => {
  expect(product).toBe("faculty");
  expect(productName).toBe("Cathedra Faculty");
  expect(API).toContain("8102");
  expect(getCurrentUser()).toBeNull();
  saveSession({ token: "synthetic-faculty", user: { id: 1, username: "test-faculty", role: "admin", is_active: true, must_change_password: false } });
  expect(sessionStorage.getItem("cathedra-faculty-session")).toContain("synthetic-faculty");
  expect(localStorage.getItem("cathedra-faculty-session")).toBeNull();
});
