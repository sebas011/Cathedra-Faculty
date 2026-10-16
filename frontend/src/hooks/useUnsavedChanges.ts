import { useEffect, useRef } from "react";
import { useBlocker } from "react-router-dom";

export function useUnsavedChanges(value: unknown) {
  const serialized = JSON.stringify(value);
  const baseline = useRef(serialized);
  const bypass = useRef(false);
  const dirty = serialized !== baseline.current;
  const blocker = useBlocker(() => dirty && !bypass.current);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (!dirty || bypass.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  return {
    blocker,
    dirty,
    resetBaseline: (next: unknown) => { baseline.current = JSON.stringify(next); },
    allowLeave: () => { bypass.current = true; },
  };
}
