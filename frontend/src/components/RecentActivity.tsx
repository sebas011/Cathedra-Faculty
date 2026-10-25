import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getActivityPage } from "../api";
import type { ActivityEvent } from "../types";
import { ArrowIcon, HistoryIcon } from "./Icons";

export default function RecentActivity() {
  const [items, setItems] = useState<ActivityEvent[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setState("loading");
    void getActivityPage({ search: "", date_from: "", date_to: "" }, 1).then(result => {
      if (active) { setItems(result.items.slice(0, 5)); setState("ready"); }
    }).catch(() => { if (active) setState("error"); });
    return () => { active = false; };
  }, [revision]);
  const timestamp = (value: string) => /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  const when = (value: string) => {
    const parsed = new Date(timestamp(value));
    return Number.isNaN(parsed.getTime()) ? "Time unavailable" : new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(parsed);
  };
  return <section className="dashboard-recent" aria-labelledby="recent-activity-heading">
    <div className="dashboard-panel-heading"><div><span className="eyebrow">OFFICE JOURNAL</span><h2 id="recent-activity-heading">Recent activity</h2></div><Link to="/activity" className="dashboard-text-link">View all <ArrowIcon /></Link></div>
    {state === "loading" && <p className="dashboard-feed-empty" role="status">Loading recent activity…</p>}
    {state === "error" && <div className="dashboard-feed-empty" role="alert"><p>Recent activity could not load.</p><button className="btn secondary" type="button" onClick={() => setRevision(value => value + 1)}>Retry activity</button></div>}
    {state === "ready" && !items.length && <div className="dashboard-feed-empty"><HistoryIcon /><strong>Your office journal starts here</strong><p>Saved changes and account activity will appear in this feed.</p></div>}
    {state === "ready" && <ol className="dashboard-feed">{items.map(item => <li key={item.id}><span className="activity-dot" aria-hidden="true" /><div><strong>{item.action}</strong><p>{item.username || "System"} <span aria-hidden="true">·</span> {item.area}</p></div><time dateTime={timestamp(item.created_at)}>{when(item.created_at)}</time></li>)}</ol>}
  </section>;
}
