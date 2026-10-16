import { Link } from "react-router-dom";
export default function PlaceholderPage({ title, description }: { title: string; description: string }) {
  return <div className="empty-page"><div className="placeholder-card"><span className="eyebrow">PLANNED MODULE</span><h1>{title}</h1><p>{description}</p><Link to="/" className="btn secondary">Back to Dashboard</Link></div></div>;
}
