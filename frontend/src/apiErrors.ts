const fieldNames: Record<string, string> = {
  assignments: "Teaching assignment", faculty_profile_id: "Faculty member", year_section: "Year and section",
  highest_qualification: "Highest academic degree", professional_qualification: "Professional credential",
  professional_qualification_other: "Other professional credential", academic_year: "Academic year",
  lecture_hours: "Lecture hours per week", laboratory_hours: "Laboratory hours per week",
  salary_grade: "Salary grade", salary_step: "Salary step", employment_status: "Employment status",
};

export function apiErrorMessage(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((issue: unknown) => {
      if (!issue || typeof issue !== "object") return [];
      const entry = issue as { loc?: unknown; msg?: unknown; type?: string };
      if (typeof entry.msg !== "string") return [];
      const parts = Array.isArray(entry.loc) ? entry.loc.filter((part) => part !== "body" && part !== "query" && part !== "path") : [];
      const field = parts.map((part) => {
        if (typeof part === "number") return String(part + 1);
        if (typeof part !== "string") return "";
        return fieldNames[part] || part.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
      }).filter(Boolean).join(" · ");
      const friendly: Record<string, string> = {
        missing: "This field is required.",
        int_parsing: "Enter a whole number.",
        float_parsing: "Enter a valid number.",
        date_from_datetime_parsing: "Enter a valid date.",
        date_parsing: "Enter a valid date.",
      };
      const message = friendly[entry.type || ""] || entry.msg.replace(/^Value error, /, "");
      return [field ? `${field}: ${message}` : message];
    });
    if (messages.length) return [...new Set(messages)].join("; ");
  }
  if (status === 401) return "Your session has expired. Please sign in again.";
  if (status === 403) return "You do not have permission to perform this action.";
  if (status === 422) return "Some details could not be accepted. Check required fields, dates, and numbers, then try again.";
  return "The request could not be completed. Please try again. If it continues, check System Readiness.";
}
