import { useMemo, useState } from "react";

import { calendarEnd, calendarEvents, calendarStart, calendarYear } from "../academicCalendar";
import type { CalendarCategory, CalendarEvent } from "../academicCalendar";
import "./AcademicCalendarPage.css";

const weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const categories: Array<CalendarCategory | "All"> = ["All", "Academic", "Exams", "Break", "University", "Holiday"];
const displayDate = (value: string, options: Intl.DateTimeFormatOptions) =>
  new Intl.DateTimeFormat("en-PH", { ...options, timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`));
const isoDate = (year: number, month: number, day: number) =>
  `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
const eventsOn = (date: string, events: CalendarEvent[]) => events.filter((event) => event.start <= date && (event.end ?? event.start) >= date);
const dateLabel = (event: CalendarEvent) => event.end
  ? `${displayDate(event.start, { month: "short", day: "numeric" })}–${displayDate(event.end, { month: "short", day: "numeric", year: "numeric" })}`
  : displayDate(event.start, { month: "short", day: "numeric", year: "numeric" });

export default function AcademicCalendarPage() {
  const today = new Date();
  const todayIso = isoDate(today.getFullYear(), today.getMonth(), today.getDate());
  const initialDate = todayIso >= calendarStart && todayIso <= calendarEnd ? todayIso : calendarStart;
  const [selectedDate, setSelectedDate] = useState(initialDate);
  const [category, setCategory] = useState<(typeof categories)[number]>("All");
  const selectedMonth = Number(selectedDate.slice(5, 7)) - 1;
  const selectedYear = Number(selectedDate.slice(0, 4));
  const monthStart = isoDate(selectedYear, selectedMonth, 1);
  const firstWeekday = new Date(`${monthStart}T00:00:00Z`).getUTCDay();
  const daysInMonth = new Date(Date.UTC(selectedYear, selectedMonth + 1, 0)).getUTCDate();
  const monthCells = Array.from({ length: Math.ceil((firstWeekday + daysInMonth) / 7) * 7 }, (_, index) => {
    const date = new Date(Date.UTC(selectedYear, selectedMonth, index - firstWeekday + 1));
    return isoDate(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
  });
  const shownEvents = useMemo(() => calendarEvents.filter((event) => category === "All" || event.category === category), [category]);
  const selectedEvents = eventsOn(selectedDate, shownEvents);
  const monthEvents = shownEvents.filter((event) => event.start <= isoDate(selectedYear, selectedMonth, daysInMonth) && (event.end ?? event.start) >= monthStart);
  const canPrevious = monthStart > calendarStart;
  const canNext = monthStart.slice(0, 7) < calendarEnd.slice(0, 7);
  const moveMonth = (offset: number) => {
    const next = new Date(Date.UTC(selectedYear, selectedMonth + offset, 1));
    setSelectedDate(isoDate(next.getUTCFullYear(), next.getUTCMonth(), 1));
  };

  return <div className="stack-md academic-calendar-page">
    {todayIso > calendarEnd && <div className="notice" role="status">This published calendar covers {calendarYear}. Obtain the approved calendar for the new academic year before relying on these dates.</div>}
    <section className="hero-card compact"><div><span className="eyebrow">ACADEMIC YEAR {calendarYear}</span><h1>Academic Calendar</h1></div><span className="calendar-source-tag">CHMSU calendar · Revised sheet</span></section>
    <section className="calendar-overview" aria-label="Academic periods">
      <div><span>First semester begins</span><strong>Aug 12, 2026</strong></div>
      <div><span>Second semester classes begin</span><strong>Jan 13, 2027</strong></div>
      <div><span>Second semester ends</span><strong>May 20, 2027</strong></div>
      <div><span>Summer classes</span><strong>Jun 14 – Jul 24, 2027</strong></div>
    </section>
    <section className="calendar-workspace" aria-label="Academic calendar and events">
      <div className="data-card calendar-panel">
        <div className="calendar-toolbar"><div><span className="eyebrow">MONTH VIEW</span><h2>{displayDate(monthStart, { month: "long", year: "numeric" })}</h2></div><div className="calendar-controls"><button className="btn secondary" type="button" disabled={!canPrevious} onClick={() => moveMonth(-1)} aria-label="Previous month">‹</button><button className="btn secondary" type="button" disabled={!canNext} onClick={() => moveMonth(1)} aria-label="Next month">›</button></div></div>
        <div className="calendar-filters"><label>Show events<select value={category} onChange={(event) => setCategory(event.target.value as (typeof categories)[number])}>{categories.map((value) => <option key={value}>{value}</option>)}</select></label>{todayIso >= calendarStart && todayIso <= calendarEnd && <button className="btn secondary" type="button" onClick={() => setSelectedDate(todayIso)}>Today</button>}</div>
        <div className="calendar-grid" role="group" aria-label={displayDate(monthStart, { month: "long", year: "numeric" })}>
          {weekdays.map((day) => <div className="calendar-weekday" key={day}>{day}</div>)}
          {monthCells.map((date) => {
            const events = eventsOn(date, shownEvents);
            const inYear = date >= calendarStart && date <= calendarEnd;
            return <button key={date} type="button" className={`calendar-day ${date.slice(0, 7) !== monthStart.slice(0, 7) ? "outside" : ""} ${date === todayIso ? "today" : ""} ${date === selectedDate ? "selected" : ""}`} disabled={!inYear} onClick={() => setSelectedDate(date)} aria-pressed={date === selectedDate} aria-label={`${displayDate(date, { weekday: "long", month: "long", day: "numeric", year: "numeric" })}, ${events.length} events`}><span className="calendar-day-number">{Number(date.slice(-2))}</span><span className="calendar-day-events">{events.slice(0, 2).map((event) => <span key={`${event.title}-${event.start}`} className={`calendar-event-marker category-${event.category.toLowerCase()}`}>{event.title}</span>)}{events.length > 2 && <small>+{events.length - 2} more</small>}</span></button>;
          })}
        </div>
      </div>
      <aside className="data-card calendar-agenda" aria-label="Calendar agenda"><div className="calendar-agenda-header"><span className="eyebrow">SELECTED DATE</span><h2>{displayDate(selectedDate, { weekday: "long", month: "long", day: "numeric", year: "numeric" })}</h2></div><div className="calendar-agenda-section"><h3>On this day</h3>{selectedEvents.length ? <ul>{selectedEvents.map((event) => <li key={`${event.title}-${event.start}`}><span className={`calendar-event-category category-${event.category.toLowerCase()}`}>{event.category}</span><strong>{event.title}</strong><small>{dateLabel(event)}</small></li>)}</ul> : <p>No {category === "All" ? "listed" : category.toLowerCase()} events on this date.</p>}</div><div className="calendar-agenda-section"><h3>In this month</h3>{monthEvents.length ? <ul>{monthEvents.map((event) => <li key={`${event.title}-${event.start}`}><span className={`calendar-event-category category-${event.category.toLowerCase()}`}>{event.category}</span><strong>{event.title}</strong><small>{dateLabel(event)}</small></li>)}</ul> : <p>No listed events in this category.</p>}</div></aside>
    </section>
    <p className="calendar-note">Dates are transcribed from the supplied CHMSU A.Y. 2026–2027 workbook. Holidays and calendar changes remain subject to university approval or official declaration. This page does not change saved workloads, grants, reporting periods, or compensation calculations.</p>
  </div>;
}
