import { NavLink, Outlet } from "react-router-dom";
import { getCurrentUser } from "../api";

export default function WorkspaceSection({ section }: { section: "settings" | "reports" }) {
  const admin = getCurrentUser()?.role === "admin";
  const items = section === "settings" ? [
    { to: "/settings", label: "Settings home", end: true },
    ...(admin ? [{ to: "/settings/compensation", label: "Compensation rules" }, { to: "/settings/qualification-rates", label: "Qualification rates" }, { to: "/settings/office-period", label: "Office period" }] : []),
    { to: "/settings/accounts", label: "Accounts & security" },
  ] : [
    { to: "/reports", label: "Overall report", end: true },
    { to: "/reports/workload", label: "Approved workload" },
    ...(admin ? [
      { to: "/reports/historical-allocations", label: "Historical allocations" },
      { to: "/reports/projection", label: "Salary & teaching" },
      { to: "/reports/saved-estimates", label: "Saved estimates" },
    ] : []),
  ];
  return <div className="stack-md workspace-section"><nav className="workspace-tabs no-print" aria-label={`${section} pages`}>
    {items.map(item => <NavLink key={item.to} to={item.to} end={item.end}>{item.label}</NavLink>)}
  </nav><Outlet /></div>;
}
