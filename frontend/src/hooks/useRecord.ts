import { useEffect, useState } from "react";

export function useRecord<Value>(id: string | undefined, load: (id: number) => Promise<Value>, fallback: string) {
  const [record, setRecord] = useState<Value | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setRecord(null);
    setError("");
    if (!id || !/^\d+$/.test(id) || !Number.isSafeInteger(Number(id)) || Number(id) < 1) {
      setError("This record address is invalid. Return to the directory to choose a record.");
      return;
    }
    void load(Number(id)).then(value => { if (active) setRecord(value); })
      .catch(caught => { if (active) setError(caught instanceof Error ? caught.message : fallback); });
    return () => { active = false; };
  }, [id, load, fallback, revision]);
  return { record, error, retry: () => setRevision(value => value + 1) };
}
