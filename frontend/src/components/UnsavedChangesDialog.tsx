import type { Blocker } from "react-router-dom";
import ConfirmationDialog from "./ConfirmationDialog";

export default function UnsavedChangesDialog({ blocker }: { blocker: Blocker }) {
  return <ConfirmationDialog open={blocker.state === "blocked"} title="Keep your changes?" description="Your edits have not been saved. Stay here to finish, or leave and discard them." cancelLabel="Stay and keep editing" confirmLabel="Leave without saving" onCancel={() => blocker.reset?.()} onConfirm={() => blocker.proceed?.()} />;
}
