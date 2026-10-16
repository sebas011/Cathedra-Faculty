import { useId } from "react";

const casPrograms = [
  { value: "Bachelor of Science in Psychology" },
  { value: "Natural Sciences" },
  { value: "Physical Education and Human Kinetics" },
  { value: "BSAM", label: "Bachelor of Science in Applied Mathematics" },
  { value: "Bachelor of Arts in English Language" },
];

export default function FacultyProgramField({ department, value, onChange, required = false, className }: {
  department: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  className?: string;
}) {
  const listId = useId();
  return <label className={className}>Program{required ? " *" : ""}
    <input required={required} maxLength={160} list={department === "CAS" ? listId : undefined} value={value} onChange={event => onChange(event.target.value)} placeholder="Enter a program or unit" />
    {department === "CAS" && <datalist id={listId}>{casPrograms.map(program => <option key={program.value} value={program.value} label={program.label} />)}</datalist>}
  </label>;
}
