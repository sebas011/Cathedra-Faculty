import { useEffect, useState } from "react";
import { getActiveProjectionPeriod, getCurrentUser, saveActiveProjectionPeriod } from "../api";
import type { ProjectionPeriod } from "../components/ProjectionPeriodControls";

export default function useProjectionScope(preferActive = false) {
  const key = `cathedra.projection.scope.${getCurrentUser()?.id ?? "anonymous"}`;
  const [period, setPeriod] = useState<ProjectionPeriod>("semester");
  const [academicYear, setAcademicYear] = useState("");
  const [term, setTerm] = useState("First Semester");
  const [scopeReady, setScopeReady] = useState(false);
  const [scopeNotice, setScopeNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [activeRevision, setActiveRevision] = useState(0);

  useEffect(() => {
    let active = true;
    void getActiveProjectionPeriod().then(defaults => {
      if (!active) return;
      let saved = null;
      try { saved = JSON.parse(localStorage.getItem(key) || "null"); } catch {}
      if (defaults) {
        setActiveRevision(defaults.revision ?? 0);
        setAcademicYear(defaults.academic_year);
        setTerm(defaults.term);
      } else {
        setScopeNotice("Choose the office academic year and semester, then save them as the active period.");
      }
      if (!preferActive && saved && /^\d{4}-\d{4}$/.test(saved.year) && ["First Semester", "Second Semester", "Summer"].includes(saved.term) && ["semester", "summer", "yearly"].includes(saved.period) && (saved.period === "summer") === (saved.term === "Summer")) {
        setAcademicYear(saved.year);
        setTerm(saved.term);
        setPeriod(saved.period);
      }
    }).catch(error => {
      if (active) setScopeNotice(error instanceof Error ? error.message : "Unable to load the active period.");
    }).finally(() => { if (active) setScopeReady(true); });
    return () => { active = false; };
  }, [key, preferActive]);

  useEffect(() => {
    if (!scopeReady || preferActive) return;
    try { localStorage.setItem(key, JSON.stringify({ period, year: academicYear, term })); } catch {}
  }, [scopeReady, preferActive, key, period, academicYear, term]);

  const saveActive = async () => {
    setSaving(true);
    try {
      const saved = await saveActiveProjectionPeriod({ academic_year: academicYear.trim(), term: term as "First Semester" | "Second Semester", revision: activeRevision });
      setActiveRevision(saved.revision ?? 0);
      setScopeNotice("Office active period saved. Your report selection is remembered separately.");
    } catch (error) {
      setScopeNotice(error instanceof Error ? error.message : "Unable to save the active period.");
    } finally { setSaving(false); }
  };
  const useActive = async () => {
    try {
      const active = await getActiveProjectionPeriod();
      if (!active) { setScopeNotice("No active period has been configured yet."); return; }
      setActiveRevision(active.revision ?? 0);
      setAcademicYear(active.academic_year);
      setTerm(active.term);
      setPeriod("semester");
      setScopeNotice("Showing the office active period.");
    } catch (error) { setScopeNotice(error instanceof Error ? error.message : "Unable to load the active period."); }
  };
  return { period, setPeriod, academicYear, setAcademicYear, term, setTerm, scopeReady, scopeNotice, saving, saveActive, useActive };
}
