import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import axe from "axe-core";
import OfficeGuidePage from "../src/pages/OfficeGuidePage";
import TableRegion from "../src/components/TableRegion";

const rules = ["button-name", "link-name", "label", "aria-valid-attr", "aria-valid-attr-value", "aria-required-attr", "aria-roles", "heading-order", "table-duplicate-name", "td-headers-attr"];

test("office guide passes structural accessibility rules", async () => {
  const { container } = render(<MemoryRouter><main><OfficeGuidePage /></main></MemoryRouter>);
  const result = await axe.run(container, { runOnly: { type: "rule", values: rules } });
  expect(result.violations.map(item => `${item.id}: ${item.description}`)).toEqual([]);
});

test("scrollable tables are named, keyboard focusable and structurally accessible", async () => {
  const { container } = render(<main><TableRegion label="Faculty records"><table><caption>Faculty records</caption><thead><tr><th scope="col">Faculty member</th></tr></thead><tbody><tr><td>Demonstration Faculty</td></tr></tbody></table></TableRegion></main>);
  const region = screen.getByRole("region", { name: "Faculty records" });
  expect(region.tabIndex).toBe(0);
  region.focus();
  expect(document.activeElement).toBe(region);
  const result = await axe.run(container, { runOnly: { type: "rule", values: rules } });
  expect(result.violations.map(item => item.id)).toEqual([]);
});
