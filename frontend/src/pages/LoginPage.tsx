import { FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getAccountStatus, saveSession, setupAdmin, signIn } from "../api";
import PageSkeleton from "../components/PageSkeleton";
import { productName } from "../product";

function readSetupKey() {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const key = fragment.get("setup-key");
  return key && /^[A-Za-z0-9_-]{43}$/.test(key) ? key : null;
}

export default function LoginPage() {
  const navigate = useNavigate();
  const [setupRequired, setSetupRequired] = useState<boolean | null>(null);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [setupKey, setSetupKey] = useState(readSetupKey);
  const errorRef = useRef<HTMLDivElement>(null);
  const submitting = useRef(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (new URLSearchParams(window.location.hash.slice(1)).has("setup-key")) {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
  }, []);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);
  useEffect(() => {
    let active = true;
    setError("");
    void getAccountStatus().then(status => { if (active) setSetupRequired(status.setup_required); })
      .catch(() => { if (active) setError("Cathedra could not reach the local service."); });
    return () => { active = false; };
  }, [retry]);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting.current || setupRequired === null) return;
    setError("");
    setFieldErrors({});
    if (setupRequired && !setupKey) {
      setError("Open Cathedra from its desktop shortcut to finish first-time setup.");
      return;
    }
    const data = new FormData(event.currentTarget);
    const username = String(data.get("username") || "").trim();
    const password = String(data.get("password") || "");
    const fields: Record<string, string> = {};
    if (!username) fields.username = "Enter your username.";
    if (!password) fields.password = "Enter your password.";
    else if (password.length < 10) fields.password = "Use a password with at least 10 characters.";
    if (Object.keys(fields).length) {
      setFieldErrors(fields);
      setError("Check the highlighted sign-in fields.");
      return;
    }
    submitting.current = true;
    setBusy(true);
    try {
      const session = setupRequired && setupKey ? await setupAdmin(username, password, setupKey) : await signIn(username, password);
      setSetupKey(null);
      saveSession(session);
      navigate(session.user.must_change_password ? "/settings/accounts" : "/");
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Unable to sign in.";
      setError(message);
      if (/username|password/i.test(message)) setFieldErrors({ password: message });
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  };
  if (setupRequired === null && !error) return <div className="login-page"><PageSkeleton label="Preparing sign-in" variant="form" /></div>;
  return <div className="login-page"><div className="login-panel"><div className="login-brand"><div className="brand-mark large" aria-hidden="true">C</div><div><h1>{productName}</h1><p>Management Information System</p></div></div><div className="login-copy"><span className="eyebrow">LOCAL OFFICE ACCESS</span><h2>{setupRequired ? "Set up the first administrator" : "Sign in to Cathedra"}</h2><p>{setupRequired ? "Create the first local administrator account for this computer. Keep these details somewhere safe." : "Use your local Cathedra account to access office records."}</p></div><form noValidate onSubmit={(event) => void submit(event)} className="login-form"><label>Username<input name="username" autoComplete="username" placeholder="Enter username" aria-invalid={fieldErrors.username ? true : undefined} aria-describedby={fieldErrors.username ? "login-username-error" : undefined} />{fieldErrors.username && <span className="field-error" id="login-username-error">{fieldErrors.username}</span>}</label><label>Password<input name="password" type="password" autoComplete={setupRequired ? "new-password" : "current-password"} placeholder="At least 10 characters" aria-invalid={fieldErrors.password ? true : undefined} aria-describedby={fieldErrors.password ? "login-password-error" : undefined} />{fieldErrors.password && <span className="field-error" id="login-password-error">{fieldErrors.password}</span>}</label>{error && <div className="form-error" role="alert" tabIndex={-1} ref={errorRef}>{error}{setupRequired === null && <button type="button" className="btn secondary" onClick={() => setRetry(value => value + 1)}>Retry connection</button>}</div>}<button className="btn primary wide" type="submit" disabled={busy || setupRequired === null}>{busy ? "Please wait…" : setupRequired ? "Create Administrator" : "Sign In"}</button></form>{setupRequired && <div className="dev-note"><strong>First-time setup:</strong> this account can add office staff accounts and manage backups.</div>}</div><div className="login-visual"><div className="visual-orb one"/><div className="visual-orb two"/><div className="visual-content"><svg className="campus-illustration" viewBox="0 0 360 170" fill="none" aria-hidden="true"><path d="M20 153H340M48 153V83H312V153M36 83L180 20L324 83H36ZM67 153V98H89V153M112 153V98H134V153M157 153V98H203V153M226 153V98H248V153M271 153V98H293V153M156 62H204M180 41V62" stroke="currentColor" strokeWidth="1.5"/><path d="M30 163H330M61 91H299" stroke="currentColor" strokeWidth="1.5"/></svg><span className="eyebrow light">CATHEDRA</span><h2>A considered space<br/>for faculty records.</h2><p>Your people, your teaching plans, your office. Records and backups stay on this computer.</p><div className="visual-modules"><span>Faculty profiles & workloads</span><span>Reports & backups</span></div></div></div></div>;
}
