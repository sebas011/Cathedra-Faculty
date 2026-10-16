import { useSearchParams } from "react-router-dom";

export default function SectionNav({ label, items }: { label: string; items: { value: string; label: string }[] }) {
  const [params, setParams] = useSearchParams();
  const selected = items.some((item) => item.value === params.get("view")) ? params.get("view") : items[0].value;
  return <nav className="section-nav no-print" aria-label={label}>
    {items.map((item) => <button key={item.value} type="button" aria-current={selected === item.value ? "page" : undefined} onClick={() => {
      const next = new URLSearchParams(params);
      next.set("view", item.value);
      setParams(next);
    }}>{item.label}</button>)}
  </nav>;
}
