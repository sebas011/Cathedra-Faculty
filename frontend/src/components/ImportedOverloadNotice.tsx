import type { FacultyWorkload } from "../types";

export default function ImportedOverloadNotice({ record }: { record: FacultyWorkload }) {
  if (record.imported_overload_hours == null) return null;
  return <div className="notice" role="status">
    <strong>Source-file overload: {record.imported_overload_hours} h/week.</strong>{" "}
    Cathedra calculates {record.calculated_overload_hours} h/week from teaching hours and preparations.
    {record.overload_difference && " Difference flagged for review."} Compensation uses the source-file value.
    Editing courses does not replace this imported value. New workloads use the standard calculation.
  </div>;
}
