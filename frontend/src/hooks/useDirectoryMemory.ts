import { useEffect, useRef, useState, type SetStateAction } from "react";
import { getCurrentUser } from "../api";

const prefix = "cathedra-directory:";
const keyFor = (name: string) => `${prefix}${getCurrentUser()?.id ?? "guest"}:${name}`;

function read<T extends string | number>(key: string, fallback: T): T {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(key) || "null");
    if (typeof value === typeof fallback && (typeof value === "string" || (typeof value === "number" && Number.isSafeInteger(value) && value >= 0))) return value as T;
  } catch {}
  return fallback;
}

function write(key: string, value: string | number) {
  try { sessionStorage.setItem(key, JSON.stringify(value)); } catch {}
}

export function useDirectoryValue<T extends string | number>(name: string, fallback: T) {
  const key = keyFor(name);
  const [value, setValue] = useState<T>(() => read(key, fallback));
  const update = (next: SetStateAction<T>) => setValue((current) => {
    const result = typeof next === "function" ? next(current) : next;
    write(key, result);
    return result;
  });
  return [value, update] as const;
}

export function useDirectoryScroll(name: string, ready: boolean) {
  const key = keyFor(`${name}:scroll`);
  const restored = useRef(false);
  useEffect(() => {
    if (!ready || restored.current) return;
    const frame = requestAnimationFrame(() => {
      window.scrollTo({ top: read(key, 0), behavior: "instant" });
      restored.current = true;
    });
    return () => cancelAnimationFrame(frame);
  }, [key, ready]);
  useEffect(() => {
    const remember = () => { if (restored.current) write(key, Math.round(window.scrollY)); };
    window.addEventListener("scroll", remember, { passive: true });
    return () => window.removeEventListener("scroll", remember);
  }, [key]);
}
