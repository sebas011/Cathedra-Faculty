import { Link } from "react-router-dom";
import { getCurrentUser } from "../api";

export default function SettingsPage() {
  const admin = getCurrentUser()?.role === "admin";
  return <div className="stack-md">
    <section className="hero-card compact"><div><span className="eyebrow">SETTINGS</span><h1>Office settings</h1><p>Manage defaults here. Record entry and printable reports stay in their own workspaces.</p></div></section>
    <div className="workspace-card-grid">
      {admin && <section className="data-card workspace-card"><h2>Qualification rate drafts</h2><p>Prepare CPA, Engineer, academic degrees, and other qualification additions with effective dates and a proposed combination rule. Drafts do not change pay.</p><Link className="btn primary" to="/settings/qualification-rates">Prepare qualification rates</Link></section>}
      {admin && <><section className="data-card workspace-card"><h2>Compensation & teaching rules</h2><p>Manage existing qualification additions, hourly-rate inputs, and semester or summer teaching weeks.</p><p>CPA and Other are recorded without rate additions until an approved rule is defined. Academic degrees and professional credentials remain separate.</p><Link className="btn primary" to="/settings/compensation">Manage compensation rules</Link></section>
      <section className="data-card workspace-card"><h2>Office period & overload budgets</h2><p>Set the active reporting semester and save a separate overload budget for each semester.</p><Link className="btn primary" to="/settings/office-period">Manage period and budgets</Link></section></>}
      <section className="data-card workspace-card"><h2>Accounts & security</h2><p>Change your password. Administrators can also manage office accounts.</p><Link className="btn secondary" to="/settings/accounts">Open account settings</Link></section>
      <section className="data-card workspace-card"><h2>Backup & system health</h2><p>Backups, restore, and readiness checks stay in dedicated pages, separate from everyday settings.</p><div className="action-group"><Link className="btn secondary" to="/backup-export">Backup & Export</Link><Link className="btn secondary" to="/system-readiness">System Readiness</Link></div></section>
    </div>
  </div>;
}
