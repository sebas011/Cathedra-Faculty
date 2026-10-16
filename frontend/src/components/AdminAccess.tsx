import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { getCurrentUser } from "../api";

export default function AdminAccess({ children }: { children: ReactNode }) {
  if (getCurrentUser()?.role === "admin") return children;
  return <section className="form-card stack-md"><h1>Administrator access required</h1><p>An administrator can view expenses and prepare projections. Your faculty records and account settings are still available.</p><Link className="btn secondary" to="/">Return to dashboard</Link></section>;
}
