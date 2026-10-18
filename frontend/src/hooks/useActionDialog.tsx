import { useEffect, useRef, useState } from "react";
import ConfirmationDialog from "../components/ConfirmationDialog";

type Action = { description: string; title: string; confirmLabel: string; inputLabel?: string };

/** One pending action per page. Cancellation and unmount never authorize a write. */
export function useActionDialog() {
  const [action, setAction] = useState<Action | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const pending = useRef<((result: string | boolean | null) => void) | null>(null);
  useEffect(() => () => { pending.current?.(null); pending.current = null; }, []);

  const open = (next: Action) => new Promise<string | boolean | null>(resolve => {
    if (pending.current) { resolve(null); return; }
    pending.current = resolve;
    setValue("");
    setError("");
    setAction(next);
  });
  const finish = (confirmed: boolean) => {
    if (confirmed && action?.inputLabel && !value.trim()) {
      setError("Enter a reason before continuing.");
      return;
    }
    const resolve = pending.current;
    pending.current = null;
    setAction(null);
    resolve?.(confirmed ? action?.inputLabel ? value.trim() : true : null);
  };
  const confirmAction = async (description: string, title = "Confirm action", confirmLabel = "Continue") =>
    await open({ description, title, confirmLabel }) === true;
  const requestInput = async (description: string, title: string, confirmLabel: string, inputLabel: string) => {
    const result = await open({ description, title, confirmLabel, inputLabel });
    return typeof result === "string" ? result : null;
  };
  const actionDialog = <ConfirmationDialog open={action !== null} title={action?.title || ""} description={action?.description || ""} confirmLabel={action?.confirmLabel || "Continue"} cancelLabel="Cancel" onConfirm={() => finish(true)} onCancel={() => finish(false)} input={action?.inputLabel ? { label: action.inputLabel, value, onChange: next => { setValue(next); setError(""); }, error } : undefined} />;
  return { confirmAction, requestInput, actionDialog };
}
