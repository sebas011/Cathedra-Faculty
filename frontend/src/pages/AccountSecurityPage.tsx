import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { changePassword, clearSession, createUser, getCurrentUser, getUsers, resetUserPassword, revokeUserSessions, setUserActive } from "../api";
import PageSkeleton from "../components/PageSkeleton";
import type { LocalUser } from "../types";
import { useActionDialog } from "../hooks/useActionDialog";

export default function AccountSecurityPage() {
  const { confirmAction, actionDialog } = useActionDialog();
  const navigate = useNavigate();
  const currentUser = getCurrentUser();
  const admin = currentUser?.role === "admin" && !currentUser.must_change_password;
  const [users, setUsers] = useState<LocalUser[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(admin);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [loadRevision, setLoadRevision] = useState(0);
  const [fieldError, setFieldError] = useState<{ action: string; field: string; message: string } | null>(null);

  const fieldAttributes = (action: string, field: string) => fieldError?.action === action && fieldError.field === field
    ? { "aria-invalid": true as const, "aria-describedby": "account-field-error" } : {};

  useEffect(() => {
    if (!admin) return;
    let active = true;
    setLoadError(""); setAccountsLoading(true);
    void getUsers().then(value => { if (active) setUsers(value); })
      .catch(caught => { if (active) setLoadError(caught instanceof Error ? caught.message : "Unable to load accounts."); })
      .finally(() => { if (active) setAccountsLoading(false); });
    return () => { active = false; };
  }, [admin, loadRevision]);

  const submit = async (event: FormEvent<HTMLFormElement>, action: "change" | "reset" | "create") => {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const values = new FormData(form);
    if (action === "reset") {
      const user = users.find(item => item.id === Number(values.get("user")));
      if (!user || !await confirmAction(`Reset ${user.username}'s password? Their current password will stop working and their sessions will be signed out. Give them the temporary password securely.`, "Reset account password?", "Reset password")) return;
    }
    setError("");
    setFieldError(null);
    setNotice("");
    setBusy(true);
    try {
      const password = String(values.get("password") || "");
      if (action === "change") {
        await changePassword(String(values.get("current") || ""), password);
        clearSession(); navigate("/login", { replace: true });
        return;
      } else if (action === "reset") {
        const userId = Number(values.get("user"));
        await resetUserPassword(userId, password);
        if (userId === getCurrentUser()?.id) { clearSession(); navigate("/login", { replace: true }); return; }
        setNotice("Temporary password saved. Give it to the person securely.");
      } else {
        const created = await createUser(String(values.get("username") || "").trim(), password, values.get("role") === "admin" ? "admin" : "staff");
        setUsers((current) => [...current, created].sort((left, right) => left.username.localeCompare(right.username)));
        setNotice(`${created.username} can now sign in.`);
      }
      form.reset();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Unable to update the account.";
      setError(message);
      if (action === "change" && /current password/i.test(message)) setFieldError({ action, field: "current", message });
      else if (/password/i.test(message)) setFieldError({ action, field: "password", message });
      else if (action === "create" && /username/i.test(message)) setFieldError({ action, field: "username", message });
    } finally {
      setBusy(false);
    }
  };

  const updateAccount = async (user: LocalUser, action: "status" | "sessions") => {
    if (busy || accountsLoading || loadError) return;
    if (action === "sessions" && !await confirmAction(`Sign out every session for ${user.username}? They will need to sign in again.`, "Sign out account sessions?", "Sign out sessions")) return;
    if (action === "status" && user.is_active && !await confirmAction(`Disable ${user.username}? They will lose access and all their sessions will be signed out. An administrator can reactivate the account.`, "Disable account?", "Disable account")) return;
    setBusy(true); setError(""); setNotice("");
    try {
      if (action === "status") {
        const saved = await setUserActive(user.id, !user.is_active);
        setUsers((current) => current.map((item) => item.id === saved.id ? saved : item));
        setNotice(`${saved.username} is now ${saved.is_active ? "active" : "disabled"}.`);
        if (saved.id === currentUser?.id && !saved.is_active) { clearSession(); navigate("/login", { replace: true }); }
      } else {
        await revokeUserSessions(user.id);
        setNotice(`${user.username} must sign in again.`);
        if (user.id === currentUser?.id) { clearSession(); navigate("/login", { replace: true }); }
      }
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to update the account."); }
    finally { setBusy(false); }
  };

  return <div className="stack-md">
    {actionDialog}
    <section className="hero-card compact"><div><span className="eyebrow">ACCOUNT SECURITY</span><h1>Accounts & Access</h1><p>Manage your password and local office accounts in one place.</p></div></section>
    {error && <div id="account-field-error" className="notice error" role="alert">{error}</div>}
    {loadError && <div className="notice error" role="alert">{loadError} <button className="btn secondary" type="button" onClick={() => setLoadRevision(value => value + 1)}>Retry accounts</button></div>}
    {currentUser?.must_change_password && <div className="notice" role="status">Change your temporary password before accessing office records.</div>}
    {notice && <div className="notice success" role="status">{notice}</div>}
    <section className="maintenance-card">
      <div><span className="eyebrow">YOUR PASSWORD</span><h2>Change your sign-in password</h2><p>Use at least 10 characters. Cathedra never displays stored passwords.</p></div>
      <form className="account-form" onSubmit={(event) => void submit(event, "change")}>
        <label>Current password<input name="current" type="password" autoComplete="current-password" required {...fieldAttributes("change", "current")} /></label>
        <label>New password<input name="password" type="password" autoComplete="new-password" required minLength={10} {...fieldAttributes("change", "password")} /></label>
        <div><button className="btn primary" disabled={busy}>Change Password</button></div>
      </form>
    </section>
    {admin && <>
      <section className="maintenance-card">
        <div><span className="eyebrow">LOCAL ACCOUNTS</span><h2>People who can use this computer</h2><p>Administrators manage accounts and restores. Staff work with records and exports.</p></div>
        {accountsLoading ? <PageSkeleton label="Loading office accounts" variant="table" /> : <div className="export-list">{users.map((user) => <div className="export-row" key={user.id}><strong>{user.username}</strong><span>{user.role === "admin" ? "Administrator" : "Staff"} · {user.is_active ? "Active" : "Disabled"}{user.must_change_password && " · Password change required"}</span><div className="action-group"><button className="btn secondary" type="button" disabled={busy || accountsLoading || !!loadError} onClick={() => void updateAccount(user, "status")}>{user.is_active ? "Disable" : "Reactivate"}</button><button className="btn secondary" type="button" disabled={busy || accountsLoading || !!loadError} onClick={() => void updateAccount(user, "sessions")}>Sign out sessions</button></div></div>)}</div>}
        <details className="disclosure"><summary>Add an office account</summary>
          <form className="account-form" onSubmit={(event) => void submit(event, "create")}>
            <label>Username<input name="username" autoComplete="off" required minLength={3} {...fieldAttributes("create", "username")} /></label>
            <label>Temporary password<input name="password" type="password" autoComplete="new-password" required minLength={10} {...fieldAttributes("create", "password")} /></label>
            <label>Access level<select name="role" defaultValue="staff"><option value="staff">Staff</option><option value="admin">Administrator</option></select></label>
            <div><button className="btn primary" disabled={busy}>Add User</button></div>
          </form>
        </details>
      </section>
      <section className="maintenance-card">
        <details className="disclosure"><summary>Reset an account password</summary>
          <p>The person should sign in and change the temporary password immediately.</p>
          <form className="account-form" onSubmit={(event) => void submit(event, "reset")}>
            <label>Account<select name="user" required>{users.map((user) => <option key={user.id} value={user.id}>{user.username} · {user.role}</option>)}</select></label>
            <label>Temporary password<input name="password" type="password" autoComplete="new-password" required minLength={10} {...fieldAttributes("reset", "password")} /></label>
            <div><button className="btn primary" disabled={busy || accountsLoading || !!loadError || !users.length}>Save Temporary Password</button></div>
          </form>
        </details>
      </section>
    </>}
  </div>;
}
