import { useEffect, useId, useRef } from "react";

type Props = {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  input?: { label: string; value: string; onChange: (value: string) => void; error?: string; maxLength?: number };
};

export default function ConfirmationDialog({ open, title, description, confirmLabel, cancelLabel, onConfirm, onCancel, input }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const inputElement = useRef<HTMLTextAreaElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const identity = useId();
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) {
      opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      element.showModal();
      if (inputElement.current) inputElement.current.focus();
      else cancelButton.current?.focus();
    } else if (!open && element.open) {
      element.close();
      if (opener.current?.isConnected && !opener.current.matches(":disabled")) opener.current.focus();
      else document.getElementById("main-content")?.focus();
      opener.current = null;
    }
  }, [open]);
  useEffect(() => {
    const element = dialog.current;
    return () => { if (element?.open) element.close(); };
  }, []);
  return <dialog ref={dialog} className="unsaved-dialog" aria-labelledby={`${identity}-title`} aria-describedby={`${identity}-description`} onCancel={event => { event.preventDefault(); onCancel(); }}>
    <h2 id={`${identity}-title`}>{title}</h2>
    <p id={`${identity}-description`}>{description}</p>
    {input && <label htmlFor={`${identity}-input`}>{input.label}<textarea ref={inputElement} id={`${identity}-input`} value={input.value} maxLength={input.maxLength ?? 2000} onChange={event => input.onChange(event.target.value)} aria-invalid={input.error ? true : undefined} aria-describedby={input.error ? `${identity}-error` : undefined} />{input.error && <span id={`${identity}-error`} className="field-error" role="alert">{input.error}</span>}</label>}
    <div className="action-group"><button ref={cancelButton} type="button" className="btn primary" onClick={onCancel}>{cancelLabel}</button><button type="button" className="btn secondary danger" onClick={onConfirm}>{confirmLabel}</button></div>
  </dialog>;
}
