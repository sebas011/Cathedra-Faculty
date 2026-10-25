import { useActionDialog } from "../hooks/useActionDialog";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { BackupIcon, CalendarIcon, CloseoutIcon, DashboardIcon, DirectoryIcon, ExpenseIcon, HelpIcon, HistoryIcon, LogoutIcon, MenuIcon, ReadinessIcon, ReportsIcon, SettingsIcon, VerificationIcon, WorkloadIcon } from "./Icons";
import { Suspense, useEffect, useRef, useState } from "react";
import { clearSession, exitDesktop, getCurrentUser, getServiceHealth, releaseVersion, signOut } from "../api";
import PageSkeleton from "./PageSkeleton";
import WorkspaceSearch from "./WorkspaceSearch";
import { product, productName } from "../product";

const navigation = [
  { to: "/", label: "Dashboard", icon: DashboardIcon },
  { to: "/calendar", label: "Academic Calendar", icon: CalendarIcon },
  { to: "/faculty-profiles", label: "Faculty Profile", icon: DirectoryIcon },
  { to: "/workload", label: "Faculty Workload", icon: WorkloadIcon },
  { to: "/expenses", label: "Expenses Projection", icon: ExpenseIcon, adminOnly: true },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
  { to: "/reports", label: "Reports", icon: ReportsIcon },
  { to: "/backup-export", label: "Backup & Export", icon: BackupIcon },
  { to: "/system-readiness", label: "System Readiness", icon: ReadinessIcon },
  { to: "/verification", label: "Needs Verification", icon: VerificationIcon },
  { to: "/semester-closeout", label: "Semester Closeout", icon: CloseoutIcon, adminOnly: true },
  { to: "/office-guide", label: "Office Guide", icon: HelpIcon },
  { to: "/activity", label: "Activity History", icon: HistoryIcon, adminOnly: true },
];

const navigationGroups = [
  { label: "Workspace", paths: ["/", "/faculty-profiles", "/workload", "/expenses"] },
  { label: "Review & reporting", paths: ["/reports", "/verification", "/semester-closeout", "/calendar"] },
  { label: "Office tools", paths: ["/settings", "/backup-export", "/system-readiness", "/activity", "/office-guide"] },
];

export default function AppShell() {
  const { confirmAction, actionDialog } = useActionDialog();
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [mobile, setMobile] = useState(() => window.matchMedia("(max-width: 760px)").matches);
  const [releaseMismatch, setReleaseMismatch] = useState(false);
  const [desktopMode, setDesktopMode] = useState(false);
  const [serviceUnavailable, setServiceUnavailable] = useState(false);
  const [healthRevision, setHealthRevision] = useState(0);
  const sidebar = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const location = useLocation();
  const currentPage = navigation.find(item => item.to !== "/" && (location.pathname === item.to || location.pathname.startsWith(`${item.to}/`)))?.label || "Dashboard";
  const [exitError, setExitError] = useState("");
  const [exiting, setExiting] = useState(false);
  const navigate = useNavigate();
  const user = getCurrentUser();
  useEffect(() => {
    const query = window.matchMedia("(max-width: 760px)");
    const update = () => { setMobile(query.matches); setOpen(false); };
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    let active = true;
    void getServiceHealth()
      .then((health) => { if (active) { setServiceUnavailable(false); setReleaseMismatch(health.release_version !== releaseVersion || (health as typeof health & { product?: string }).product !== product); setDesktopMode(health.desktop_mode === true); } })
      .catch(() => { if (active) { setServiceUnavailable(true); setReleaseMismatch(false); } });
    return () => { active = false; };
  }, [healthRevision]);
  useEffect(() => {
    if (!open) return;
    const focusable = () => Array.from(sidebar.current?.querySelectorAll<HTMLElement>("a[href], button:not(:disabled)") || []).filter(element => element.getClientRects().length > 0);
    focusable()[0]?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setOpen(false); menuButton.current?.focus(); }
      if (event.key !== "Tab") return;
      const elements = focusable();
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);
  useEffect(() => {
    setOpen(false);
    document.getElementById("main-content")?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }, [location.pathname]);
  const logout = async () => {
    try { await signOut(); } catch { /* Clear the local session even if the service is unavailable. */ }
    clearSession();
    navigate("/login");
  };
  const exitApp = async () => {
    if (!await confirmAction("Finish and save any open changes before exiting.", "Exit Cathedra?", "Exit Cathedra")) return;
    setExitError("");
    try {
      await exitDesktop();
      clearSession();
      setExiting(true);
      window.close();
    } catch (caught) { setExitError(caught instanceof Error ? caught.message : "Unable to exit Cathedra."); }
  };
  if (exiting) return <main className="page" role="status"><h1>Cathedra has stopped</h1><p>You can close this window. Reopen Cathedra from its application icon when needed.</p></main>;
  return (
    <div className={`app-layout ${collapsed ? "sidebar-collapsed" : ""}`}>
      {actionDialog}
      <a className="skip-link" href="#main-content">Skip to page content</a>
      <aside ref={sidebar} id="main-sidebar" inert={mobile && !open} aria-hidden={mobile && !open ? true : undefined} className={`sidebar ${open ? "sidebar-open" : ""}`}>
        <div className="brand">
          <button className="sidebar-collapse-toggle" onClick={() => { if (open) { setOpen(false); menuButton.current?.focus(); } else setCollapsed(value => !value); }} aria-label={open ? "Close menu" : collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={open || !collapsed}><MenuIcon /></button>
          <div className="brand-mark" aria-hidden="true">C<span className="brand-mark-dot" /></div>
          <div className="brand-copy"><strong>Cathedra</strong><span>Faculty workspace</span></div>
        </div>
        <nav className="nav-list" aria-label="Main navigation">
          {navigationGroups.map((group) => <div className="nav-group" key={group.label}>
            <div className="nav-caption">{group.label}</div>
            {group.paths.flatMap((path) => navigation.filter((item) => item.to === path && (!item.adminOnly || user?.role === "admin"))).map(({ to, label, icon: NavIcon }) => (
            <NavLink key={to} to={to} title={label} aria-label={label} end={to === "/"} onClick={() => setOpen(false)} className={({isActive}) => `nav-item ${isActive ? "active" : ""}`}>
              <NavIcon className="nav-icon"/><span>{label}</span>
            </NavLink>
          ))}</div>)}
        </nav>
        <div className="sidebar-foot"><span>Cathedra {releaseVersion}</span><small><i aria-hidden="true" />Local office workspace</small></div>
      </aside>
      {open && <button className="sidebar-scrim" aria-label="Close menu" onClick={() => setOpen(false)} />}
      <div className="workspace">
        <header className="topbar">
          <button ref={menuButton} className="mobile-menu" onClick={() => setOpen(true)} aria-label="Open menu" aria-expanded={open} aria-controls="main-sidebar"><MenuIcon /></button>
          <div className="topbar-title"><span>{productName} <span aria-hidden="true">/</span></span><strong>{currentPage}</strong></div>
          <div className="account-box">
            <WorkspaceSearch destinations={navigation.filter(item => !item.adminOnly || user?.role === "admin")} />
            {!location.pathname.startsWith("/reports") && <button className="logout-button no-print" onClick={() => window.print()}><span>Print This Page</span></button>}
            <div className="avatar">{user?.username.slice(0, 1).toUpperCase() || "A"}</div>
            <div className="account-copy"><strong>{user?.username || "Administrator"}</strong><span>{user?.role === "admin" ? "Administrator" : "Staff"}</span></div>
            <button className="logout-button" aria-label="Logout" onClick={() => void logout()}><LogoutIcon /> <span>Logout</span></button>
            {desktopMode && user?.role === "admin" && <button className="logout-button" aria-label="Exit Cathedra" onClick={() => void exitApp()}><span>Exit Cathedra</span></button>}
          </div>
        </header>
        {releaseMismatch && <div className="release-warning" role="alert">This Cathedra window and its local service do not match. Close Cathedra completely, then open the latest desktop version.</div>}
        {serviceUnavailable && <div className="release-warning" role="alert">The local service could not be reached. Check that Cathedra is running. <button className="btn secondary" type="button" onClick={() => setHealthRevision(value => value + 1)}>Retry connection</button></div>}
        {exitError && <div className="release-warning" role="alert">{exitError}</div>}
        <main className="page" id="main-content" tabIndex={-1}><Suspense fallback={<PageSkeleton label="Loading page" variant="table" />}><Outlet /></Suspense></main>
      </div>
    </div>
  );
}
