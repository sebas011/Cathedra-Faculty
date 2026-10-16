export type ProjectionPeriod = "semester" | "summer" | "yearly";

export default function ProjectionPeriodControls({ period, year, term, onPeriod, onYear, onTerm, saveActive, useActive, saving, notice }: {
  saveActive?: () => void;
  useActive: () => void;
  saving: boolean;
  notice: string;
  period: ProjectionPeriod;
  year: string;
  term: string;
  onPeriod: (value: ProjectionPeriod) => void;
  onYear: (value: string) => void;
  onTerm: (value: string) => void;
}) {
  return <>
    <label>Reporting period<select value={period} onChange={event => { const next = event.target.value as ProjectionPeriod; onPeriod(next); if (next === "summer") onTerm("Summer"); else if (term === "Summer") onTerm("First Semester"); }}><option value="semester">Per semester · 4.5 salary months</option><option value="summer">Summer · teaching compensation only</option><option value="yearly">Yearly · 12 salary months</option></select></label>
    <label>Academic year<input value={year} onChange={event => onYear(event.target.value)} placeholder="e.g. 2026-2027" /></label>
    <label>{period === "yearly" ? "Active semester (yearly report still includes all terms)" : "Term"}<select value={term} onChange={event => onTerm(event.target.value)} disabled={period === "summer"}>{period === "summer" ? <option>Summer</option> : <><option>First Semester</option><option>Second Semester</option></>}</select></label>
    <div className="action-group">{saveActive && <button type="button" className="btn secondary" disabled={saving || !year.trim()} onClick={saveActive}>{saving ? "Saving…" : "Save as office active period"}</button>}<button type="button" className="btn secondary" onClick={useActive}>Use office active period</button></div>
    {notice && <p role="status">{notice}</p>}
  </>;
}
