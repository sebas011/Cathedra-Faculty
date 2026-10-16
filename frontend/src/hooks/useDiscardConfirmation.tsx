import { useEffect, useRef, useState } from "react";
import ConfirmationDialog from "../components/ConfirmationDialog";

export function useDiscardConfirmation() {
  const [description, setDescription] = useState<string | null>(null);
  const pending = useRef<((confirmed: boolean) => void) | null>(null);
  useEffect(() => () => { pending.current?.(false); pending.current = null; }, []);
  const confirmDiscard = (message: string) => new Promise<boolean>(resolve => {
    if (pending.current) { resolve(false); return; }
    pending.current = resolve;
    setDescription(message);
  });
  const finish = (confirmed: boolean) => {
    const resolve = pending.current;
    pending.current = null;
    setDescription(null);
    resolve?.(confirmed);
  };
  const discardDialog = <ConfirmationDialog open={description !== null} title="Discard your changes?" description={description || ""} confirmLabel="Discard changes" cancelLabel="Keep editing" onConfirm={() => finish(true)} onCancel={() => finish(false)} />;
  return { confirmDiscard, discardDialog };
}
