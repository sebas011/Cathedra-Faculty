import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import axe from "axe-core";
import { useDiscardConfirmation } from "../src/hooks/useDiscardConfirmation";

function Example({ completed }: { completed: (confirmed: boolean) => void }) {
  const { confirmDiscard, discardDialog } = useDiscardConfirmation();
  return <main><h1>Edit demonstration record</h1><button onClick={() => void confirmDiscard("Only unsaved edits will be removed.").then(completed)}>Cancel editor</button>{discardDialog}</main>;
}

test("discard dialog defaults to keeping edits and restores trigger focus", async () => {
  const completed = vi.fn();
  render(<Example completed={completed} />);
  const trigger = screen.getByRole("button", { name: "Cancel editor" });
  trigger.focus();
  fireEvent.click(trigger);
  const keep = await screen.findByRole("button", { name: "Keep editing" });
  expect(document.activeElement).toBe(keep);
  fireEvent.click(keep);
  await waitFor(() => expect(completed).toHaveBeenCalledWith(false));
  expect(document.activeElement).toBe(trigger);
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("Escape cancellation does not approve a discard", async () => {
  const completed = vi.fn();
  render(<Example completed={completed} />);
  fireEvent.click(screen.getByRole("button", { name: "Cancel editor" }));
  fireEvent(await screen.findByRole("dialog"), new Event("cancel", { cancelable: true }));
  await waitFor(() => expect(completed).toHaveBeenCalledWith(false));
});

test("explicit discard resolves once with approval", async () => {
  const completed = vi.fn();
  render(<Example completed={completed} />);
  fireEvent.click(screen.getByRole("button", { name: "Cancel editor" }));
  fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }));
  await waitFor(() => expect(completed).toHaveBeenCalledWith(true));
  expect(completed).toHaveBeenCalledTimes(1);
});

test("unmounting cancels a pending confirmation", async () => {
  const completed = vi.fn();
  const { unmount } = render(<Example completed={completed} />);
  fireEvent.click(screen.getByRole("button", { name: "Cancel editor" }));
  await screen.findByRole("dialog");
  unmount();
  await waitFor(() => expect(completed).toHaveBeenCalledWith(false));
});

test("discard dialog has valid labelled modal structure", async () => {
  render(<Example completed={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Cancel editor" }));
  const dialog = await screen.findByRole("dialog", { name: "Discard your changes?" });
  expect(dialog.getAttribute("aria-describedby")).toBeTruthy();
  const result = await axe.run(dialog, { runOnly: { type: "rule", values: ["aria-dialog-name", "button-name", "aria-valid-attr-value", "aria-roles"] } });
  expect(result.violations.map(item => item.id)).toEqual([]);
});
