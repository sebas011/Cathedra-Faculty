import TableRegion from "../components/TableRegion";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getVerificationQueue } from "../api";
import PageSkeleton from "../components/PageSkeleton";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import type { VerificationItem, VerificationQueue } from "../types";
import "./VerificationPage.css";

const areas: Array<"All" | VerificationItem["area"]> = ["All", "Faculty Profile", "Faculty Workload"];
const recordAreas: VerificationItem["area"][] = ["Faculty Profile", "Faculty Workload"];
const pageSize = 50;

export default function VerificationPage() {
  const [queue, setQueue] = useState<VerificationQueue | null>(null);
  const [error, setError] = useState("");
  const [area, setArea] = useState<(typeof areas)[number]>("All");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const debouncedSearch = useDebouncedValue(search);

  useEffect(() => {
    let active = true;
    setError("");
    setQueue(null);
    void getVerificationQueue(area, debouncedSearch, page)
      .then((result) => { if (active) { setQueue(result); const lastPage = Math.max(1, Math.ceil(result.matching_total / pageSize)); if (page > lastPage) setPage(lastPage); } })
      .catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "Unable to load records needing verification."); });
    return () => { active = false; };
  }, [area, debouncedSearch, page, revision]);

  const pageCount = Math.max(1, Math.ceil((queue?.matching_total ?? 0) / pageSize));
  const currentPage = Math.min(page, pageCount);

  return <div className="stack-md verification-page">
    <section className="hero-card compact"><div><span className="eyebrow">OFFICE DATA CHECKS</span><h1>Needs Verification</h1></div><button className="btn secondary no-print" type="button" onClick={() => setRevision(value => value + 1)}>Refresh</button></section>
    {error && <div className="notice error" role="alert">{error} <button className="btn secondary" type="button" onClick={() => setRevision(value => value + 1)}>Retry</button></div>}
    {!queue && !error && <PageSkeleton label="Loading verification records" variant="table" />}
    {queue && <>
      <section className="verification-summary" aria-label="Verification counts">
        {recordAreas.map((item) => <button className={`verification-count ${area === item ? "selected" : ""}`} key={item} type="button" onClick={() => { setArea(item); setPage(1); }} aria-pressed={area === item}><span>{item}</span><strong>{queue.counts[item]}</strong></button>)}
      </section>
      <section className="data-card verification-list">
        <div className="verification-toolbar"><div><h2>Records to check</h2><span>{queue.matching_total} matching · {queue.total} total</span></div><div className="verification-filters"><label>Area<select value={area} onChange={(event) => { setArea(event.target.value as (typeof areas)[number]); setPage(1); }}>{areas.map((item) => <option key={item}>{item}</option>)}</select></label><label>Search<input type="search" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Name or issue" /></label></div></div>
        <TableRegion label="Records needing verification"><table><thead><tr><th>Record</th><th>Area</th><th>What needs checking</th><th>Status</th><th>Action</th></tr></thead><tbody>
          {queue.items.length ? queue.items.map((item) => <tr key={item.key}><td><strong>{item.name}</strong></td><td>{item.area}</td><td><ul className="verification-issues">{item.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul></td><td><span className="warning-chip">{item.status}</span></td><td><Link className="btn secondary" to={item.action_path}>Open record</Link></td></tr>) : <tr><td colSpan={5} className="empty-table">No records match this view.</td></tr>}
        </tbody></table></TableRegion>
        {pageCount > 1 && <div className="verification-pages"><button className="btn secondary" type="button" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>Previous</button><span>Page {currentPage} of {pageCount}</span><button className="btn secondary" type="button" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}>Next</button></div>}
      </section>
      <p className="verification-boundary">This list updates when saved records change. An unlinked source row is not zero compensation; figures still need office review before approval.</p>
    </>}
  </div>;
}
