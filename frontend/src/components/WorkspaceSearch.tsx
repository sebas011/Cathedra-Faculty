import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowIcon, SearchIcon } from "./Icons";

type Destination = { to: string; label: string };

export default function WorkspaceSearch({ destinations }: { destinations: Destination[] }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const identity = useId();
  const options = destinations.filter(item => item.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault(); setOpen(value => !value);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    if (open) { setQuery(""); dialog.current?.showModal(); input.current?.focus(); }
    else if (dialog.current?.open) dialog.current.close();
  }, [open]);

  return <>
    <button type="button" ref={trigger} className="workspace-search-trigger" aria-label="Jump to a page" aria-haspopup="dialog" aria-controls={`${identity}-dialog`} onClick={() => setOpen(true)}><SearchIcon /><span>Jump to a page</span><kbd>Ctrl K</kbd></button>
    <dialog ref={dialog} id={`${identity}-dialog`} className="workspace-search-dialog" aria-labelledby={`${identity}-heading`} onCancel={event => { event.preventDefault(); setOpen(false); }} onClose={() => { setOpen(false); trigger.current?.focus(); }}>
      <div className="workspace-search-head"><h2 id={`${identity}-heading`}>Find your workspace</h2><button type="button" aria-label="Close page search" onClick={() => setOpen(false)}>Esc</button></div>
      <label htmlFor={`${identity}-query`}>Search pages</label>
      <div className="workspace-search-field"><SearchIcon /><input ref={input} id={`${identity}-query`} value={query} onChange={event => setQuery(event.target.value)} placeholder="Profiles, workloads, reports…" autoComplete="off" /></div>
      <p className="workspace-search-hint">Navigate with Tab, then press Enter to open a page.</p>
      <nav aria-label="Matching workspace pages" className="workspace-search-results">{options.map(item => <Link key={item.to} to={item.to} onClick={() => setOpen(false)}><span>{item.label}</span><ArrowIcon /></Link>)}</nav>
      {!options.length && <p className="workspace-search-empty" role="status">No pages match “{query}”. Try a different name.</p>}
    </dialog>
  </>;
}
