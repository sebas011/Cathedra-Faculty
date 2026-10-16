export type CalendarCategory = "Academic" | "Exams" | "Break" | "University" | "Holiday";

export type CalendarEvent = {
  title: string;
  start: string;
  end?: string;
  category: CalendarCategory;
};

export const calendarYear = "2026–2027";
export const calendarStart = "2026-08-01";
export const calendarEnd = "2027-07-31";

export const calendarEvents: CalendarEvent[] = [
  { title: "First day of faculty service", start: "2026-08-11", category: "Academic" },
  { title: "First semester begins", start: "2026-08-12", category: "Academic" },
  { title: "Ninoy Aquino Day", start: "2026-08-21", category: "Holiday" },
  { title: "National Heroes Day", start: "2026-08-31", category: "Holiday" },
  { title: "First semester midterm exams", start: "2026-10-13", end: "2026-10-16", category: "Exams" },
  { title: "All Saints’ Day", start: "2026-11-01", category: "Holiday" },
  { title: "All Souls’ Day", start: "2026-11-02", category: "Holiday" },
  { title: "Bonifacio Day", start: "2026-11-30", category: "Holiday" },
  { title: "Immaculate Conception", start: "2026-12-08", category: "Holiday" },
  { title: "First semester endterm exams", start: "2026-12-14", end: "2026-12-17", category: "Exams" },
  { title: "Semestral break", start: "2026-12-18", category: "Break" },
  { title: "Christmas break", start: "2026-12-20", category: "Break" },
  { title: "Christmas Eve", start: "2026-12-24", category: "Holiday" },
  { title: "Christmas Day", start: "2026-12-25", category: "Holiday" },
  { title: "Rizal Day", start: "2026-12-30", category: "Holiday" },
  { title: "Last day of the year", start: "2026-12-31", category: "Holiday" },
  { title: "New Year’s Day", start: "2027-01-01", category: "Holiday" },
  { title: "Faculty reporting", start: "2027-01-04", category: "Academic" },
  { title: "Second semester classes begin", start: "2027-01-13", category: "Academic" },
  { title: "Chinese New Year", start: "2027-02-06", category: "Holiday" },
  { title: "Second semester midterm exams", start: "2027-03-08", end: "2027-03-09", category: "Exams" },
  { title: "Eidul Fitr", start: "2027-03-10", category: "Holiday" },
  { title: "Second semester midterm exams", start: "2027-03-11", end: "2027-03-12", category: "Exams" },
  { title: "Maundy Thursday", start: "2027-03-25", category: "Holiday" },
  { title: "Good Friday", start: "2027-03-26", category: "Holiday" },
  { title: "Black Saturday", start: "2027-03-27", category: "Holiday" },
  { title: "Araw ng Kagitingan", start: "2027-04-09", category: "Holiday" },
  { title: "Second semester endterm exams (graduating)", start: "2027-04-22", end: "2027-04-23", category: "Exams" },
  { title: "Labor Day", start: "2027-05-01", category: "Holiday" },
  { title: "University Week", start: "2027-05-10", end: "2027-05-15", category: "University" },
  { title: "University Day", start: "2027-05-12", category: "University" },
  { title: "Eidul Adha", start: "2027-05-16", category: "Holiday" },
  { title: "Second semester endterm exams (non-graduating)", start: "2027-05-17", end: "2027-05-20", category: "Exams" },
  { title: "Second semester ends", start: "2027-05-20", category: "Academic" },
  { title: "Commencement exercises", start: "2027-05-26", end: "2027-05-28", category: "University" },
  { title: "Independence Day", start: "2027-06-12", category: "Holiday" },
  { title: "Summer classes begin", start: "2027-06-14", category: "Academic" },
  { title: "Summer midterm exam", start: "2027-07-02", category: "Exams" },
  { title: "Summer endterm exam", start: "2027-07-23", category: "Exams" },
  { title: "Summer classes end", start: "2027-07-24", category: "Academic" },
];
