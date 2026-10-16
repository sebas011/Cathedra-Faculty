import { Link } from "react-router-dom";

export default function RouteErrorPage() {
  return <main className="page" role="alert">
    <section className="hero-card compact">
      <div><span className="eyebrow">CATHEDRA</span><h1>This page could not be opened</h1><p>Your saved records have not been changed by this display error. If you were editing, check your last saved version before trying again.</p></div>
    </section>
    <div className="form-actions"><button className="btn primary" type="button" onClick={() => window.location.reload()}>Reload page</button><Link className="btn secondary" to="/">Go to dashboard</Link></div>
  </main>;
}
