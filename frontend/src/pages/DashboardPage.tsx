import { Link } from "react-router-dom";
import { useEffect, useState } from "react";

import { ArrowIcon, DirectoryIcon, ExpenseIcon, WorkloadIcon } from "../components/Icons";
import PageSkeleton from "../components/PageSkeleton";
import { getActiveProjectionPeriod, getCurrentUser, getMonthlySalaryProjection, getProjectionReadiness, getSemesterOverloadBudgets, getWorkloadReview, getWorkloadSummary } from "../api";
import type { SemesterOverloadBudget } from "../api";
import type { MonthlySalaryProjection, ProjectionReadiness, WorkloadReview, WorkloadSummary } from "../types";
import "./DashboardPage.css";

const hours = (value: number | undefined) => value === undefined ? "—" : `${value.toFixed(1)} h`;
const peso = (value: number) => new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP", maximumFractionDigits: 0 }).format(value);
const pesoCents = (value: number) => new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
type Card = { label: string; value: string | number; note: string; icon: typeof WorkloadIcon; accent?: boolean; workload?: boolean; expense?: boolean };
type AttentionItem = { id: string; area: string; title: string; detail: string; to: string; priority: number };

function CardGrid({ cards }: { cards: Card[] }) {
  return <div className="analytics-grid">{cards.map(({ label, value, note, icon: Icon, accent, workload, expense }) => <article className={`analytics-card ${accent ? "accent" : ""} ${workload ? "workload" : ""} ${expense ? "expense" : ""}`} key={label}><Icon /><span>{label}</span><strong>{value}</strong><small>{note}</small></article>)}</div>;
}

export default function DashboardPage() {
  const [budgetError, setBudgetError] = useState("");
  const isAdmin = getCurrentUser()?.role === "admin";
  const [workload, setWorkload] = useState<WorkloadSummary | null>(null);
  const [workloadFailed, setWorkloadFailed] = useState(false);
  const [expenses, setExpenses] = useState<MonthlySalaryProjection | null>(null);
  const [overloadBudgets, setOverloadBudgets] = useState<SemesterOverloadBudget[] | null>(null);
  const [overloadBudgetError, setOverloadBudgetError] = useState(false);
  const [review, setReview] = useState<WorkloadReview | null>(null);
  const [readiness, setReadiness] = useState<ProjectionReadiness | null>(null);
  const [attentionLoading, setAttentionLoading] = useState(true);
  const [attentionError, setAttentionError] = useState(false);

  const loadAttention = async () => {
    setAttentionLoading(true);
    setAttentionError(false);
    setReview(null);
    setReadiness(null);
    const results = await Promise.allSettled([getWorkloadReview(), getProjectionReadiness()]);
    if (results[0].status === "fulfilled") setReview(results[0].value);
    if (results[1].status === "fulfilled") setReadiness(results[1].value);
    setAttentionError(results.some((result) => result.status === "rejected"));
    setAttentionLoading(false);
  };

  useEffect(() => {
    void getWorkloadSummary().then(setWorkload).catch(() => setWorkloadFailed(true));
    void loadAttention();
  }, []);

  useEffect(() => {
    let active = true;
    setExpenses(null);
    setBudgetError("");
    setOverloadBudgets(null);
    setOverloadBudgetError(false);
    if (!isAdmin) return;
    void (async () => {
      try {
        const officePeriod = await getActiveProjectionPeriod();
        if (!active) return;
        if (!officePeriod) {
          setBudgetError("Set the office active semester in Settings → Office period to display the current estimate.");
          return;
        }
        const result = await getMonthlySalaryProjection("", "", officePeriod.academic_year, officePeriod.term, "semester");
        if (active) setExpenses(result);
      } catch (error) {
        if (active) setBudgetError(error instanceof Error ? error.message : "Unable to load budget estimates.");
      }
    })();
    void getSemesterOverloadBudgets().then((result) => { if (active) setOverloadBudgets(result); }).catch(() => { if (active) setOverloadBudgetError(true); });
    return () => { active = false; };
  }, [isAdmin]);

  const workloadCards: Card[] = [
    { label: "Workload records", value: workload?.workloads ?? "—", note: "Faculty teaching-load entries", icon: WorkloadIcon, workload: true },
    { label: "Course assignments", value: workload?.assignments ?? "—", note: "Subjects and sections scheduled", icon: WorkloadIcon, workload: true },
    { label: "Total weekly hours", value: hours(workload?.weekly_hours), note: `${hours(workload?.lecture_hours)} lecture · ${hours(workload?.laboratory_hours)} laboratory`, icon: WorkloadIcon, accent: true, workload: true },
  ];
  const budgetCards: Card[] = expenses ? [
    { label: `${expenses.period === "semester" ? "Semester" : "Yearly"} salary estimate`, value: peso(expenses.total_period_salary), note: `Current monthly salaries × ${expenses.salary_months} months`, icon: ExpenseIcon, expense: true },
    { label: "Period teaching cost", value: peso(expenses.teaching_cost.total_term_pay), note: `${expenses.teaching_cost.workloads} workload records included`, icon: ExpenseIcon, expense: true },
    { label: "Combined planning estimate", value: peso(expenses.combined_period_estimate), note: "Salary plus teaching cost for the same period", icon: ExpenseIcon, accent: true, expense: true },
  ] : [];
  const overloadDetails = expenses?.teaching_details.filter((item) => item.category === "Regular Faculty") ?? [];
  const overloadTotal = overloadDetails.reduce((total, item) => total + (item.term_pay ?? 0), 0);
  const activeBudgetTerm = expenses?.filters.term === "1st Semester" ? "First Semester" : expenses?.filters.term === "2nd Semester" ? "Second Semester" : expenses?.filters.term;
  const overloadBudget = overloadBudgets?.find((item) => item.academic_year === expenses?.filters.academic_year && item.term === activeBudgetTerm);
  const overloadDifference = Math.round(((overloadBudget?.amount ?? 0) - overloadTotal) * 100) / 100;
  const overloadCoverage = expenses?.overload_coverage;
  const overloadProvisional = !overloadCoverage || overloadCoverage.provisional;
  const overloadAvailable = overloadDetails.length > 0 || !overloadProvisional;
  const overloadBudgetCards: Card[] = overloadBudget ? [
    { label: "Projected overload compensation", value: overloadAvailable ? pesoCents(overloadTotal) : "Not available", note: "Regular faculty overload for the active semester", icon: ExpenseIcon, expense: true },
    { label: "Semester overload budget", value: pesoCents(overloadBudget.amount), note: "Budget provided for this semester", icon: ExpenseIcon, expense: true },
    { label: `${overloadProvisional ? "Indicative " : ""}${overloadDifference < 0 ? "over budget" : "budget remaining"}`, value: overloadAvailable ? pesoCents(Math.abs(overloadDifference)) : "Not available", note: overloadProvisional ? "Provisional: coverage gaps may change this difference" : "Budget minus projected overload compensation", icon: ExpenseIcon, accent: overloadDifference >= 0 && !overloadProvisional, expense: true },
  ] : [];
  const collegeTotals = expenses?.college_totals.filter((item) => item.combined_estimate > 0) ?? [];
  const largestCollegeEstimate = Math.max(...collegeTotals.map((item) => item.combined_estimate), 1);
  const attentionItems: AttentionItem[] = [
    ...(review?.items.map((item) => ({
      id: `workload-${item.workload_id}`,
      area: "WORKLOAD",
      title: item.flags.join(" · "),
      detail: `${item.faculty_name} · ${item.academic_year} ${item.term}`,
      to: `/workload/${item.workload_id}/edit`,
      priority: 1,
    })) ?? []),
    ...(readiness?.items.filter((item) => item.count > 0).map((item) => ({
      id: `projection-${item.key}`,
      area: "EXPENSES",
      title: item.title,
      detail: `${item.count} ${item.detail}`,
      to: item.action_path,
      priority: 2,
    })) ?? []),
  ].sort((left, right) => left.priority - right.priority || left.area.localeCompare(right.area));

  return <div className="dashboard stack-lg">
    <section className="dashboard-hero"><div><span className="eyebrow">FACULTY ADMINISTRATION</span><h1>Office overview</h1><p>Teaching workloads, semester estimates, and records that need attention.</p></div><div className="dashboard-status"><span />Local office records</div></section>
    <section><div className="dashboard-heading"><span className="eyebrow">WORKLOAD STATISTICS</span><h2>Teaching workload</h2></div>{workload ? <CardGrid cards={workloadCards} /> : workloadFailed ? <div className="notice error">Workload statistics could not load.</div> : <PageSkeleton label="Loading workload statistics" variant="dashboard" />}</section>
    {isAdmin && <section className="data-card dashboard-budget" aria-labelledby="planning-estimate-heading">
      <div className="budget-heading"><div className="dashboard-heading"><span className="eyebrow">EXECUTIVE BUDGET</span><h2 id="planning-estimate-heading">Current planning estimate</h2></div><Link className="btn secondary" to="/expenses">Open expenses report <ArrowIcon /></Link></div>
      {budgetError ? <div className="notice error" role="alert">{budgetError} <Link to="/settings/office-period">Open Office period</Link></div> : expenses ? <>
        <div className="budget-scope"><strong>A.Y. {expenses.filters.academic_year}</strong><span>{expenses.filters.term || "All terms · including summer"}</span><span>{expenses.salary_months} salary months</span></div>
        {expenses.teaching_details.length === 0 && <p className="notice" role="status">No teaching workloads are included for this semester. Check the <Link to="/settings/office-period">office reporting period</Link> and review the projection coverage before using these estimates.</p>}
        <CardGrid cards={budgetCards} />
        <div className="overload-budget-report">
          <div className="dashboard-heading"><span className="eyebrow">OVERLOAD BUDGET REPORT</span><h3>Semester overload against budget</h3></div>
          {overloadBudgetError ? <p className="notice error" role="alert">Unable to load semester overload budgets. Check Settings → Office period.</p> : overloadBudgets === null ? <PageSkeleton label="Loading overload budget" variant="dashboard" /> : overloadBudget ? <>
            <CardGrid cards={overloadBudgetCards} />
            {(overloadProvisional || expenses.warnings.length > 0) && <Link className="budget-review-shortcut" to="/reports/projection?view=checks&active=1">{expenses.warnings.length ? `${expenses.warnings.length} coverage checks` : "Review coverage"} <ArrowIcon /></Link>}
          </> : <p className="notice">No overload budget is recorded for this semester. <Link to="/settings/office-period">Set an amount in Office period settings.</Link></p>}
        </div>
      </> : <PageSkeleton label="Loading budget estimates" variant="dashboard" />}
    </section>}
    {collegeTotals.length > 0 && <section className="dashboard-report"><div className="dashboard-heading"><span className="eyebrow">DEPARTMENT COMPARISON</span><h2>Combined estimate by department</h2></div><div className="college-bars">{collegeTotals.map((item) => <div className="college-bar" key={item.college}><div><strong>{item.college}</strong><span>{peso(item.combined_estimate)}</span></div><div className="college-bar-track"><span style={{ width: `${(item.combined_estimate / largestCollegeEstimate) * 100}%` }} /></div></div>)}</div><Link className="dashboard-report-link" to="/expenses">Open full expenses report <ArrowIcon /></Link></section>}
    <section className="attention-queue"><div className="attention-heading"><div className="dashboard-heading"><span className="eyebrow">OFFICE ATTENTION</span><h2>What needs review</h2></div><Link className="btn secondary" to="/verification">All records to verify</Link></div>{attentionLoading ? <PageSkeleton label="Loading follow-up items" variant="table" /> : attentionError ? <div className="notice error" role="alert">Some follow-up checks could not load. Do not treat this list as complete. <button type="button" className="btn secondary" onClick={() => void loadAttention()}>Retry</button></div> : null}{attentionItems.length > 0 && <div className="attention-list">{attentionItems.slice(0, 8).map((item) => <Link className="attention-item" key={item.id} to={item.to}><span className={`attention-area ${item.area.toLowerCase()}`}>{item.area}</span><div><strong>{item.title}</strong><small>{item.detail}</small></div><ArrowIcon /></Link>)}</div>}{!attentionLoading && !attentionError && attentionItems.length === 0 && <div className="attention-clear"><strong>No alerts from these checks.</strong><span>Open Needs Verification for record-level gaps.</span></div>}{attentionItems.length > 8 && <p className="attention-more">Showing 8 of {attentionItems.length} alerts.</p>}</section>
    <section className="dashboard-actions"><Link to="/workload" className="dashboard-action"><WorkloadIcon /><div><strong>Review faculty workload</strong><span>Review teaching hours and assignments</span></div><ArrowIcon /></Link><Link to="/faculty-profiles" className="dashboard-action"><DirectoryIcon /><div><strong>Maintain faculty profiles</strong><span>Update appointments and salary details</span></div><ArrowIcon /></Link></section>
  </div>;
}
