import { Link } from "react-router-dom";
import type { MonthlySalaryProjection } from "../types";

const peso = (value: number) => new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP" }).format(value);

export default function TeachingCostBreakdown({ data }: { data: MonthlySalaryProjection }) {
  return <section className="data-card">
    <h2>Teaching cost breakdown</h2>
    <details><summary>Teaching calculations ({data.teaching_details.length} workloads)</summary>
      {data.teaching_details.length === 0 ? <p>No teaching records in this scope; zero is not confirmation of no teaching expense.</p> : <div className="table-scroll"><table><thead><tr><th>Faculty / term</th><th>Category</th><th>Hourly rate</th><th>Paid hours/week</th><th>Teaching college / period cost</th><th>Weeks</th><th>Teaching estimate</th></tr></thead><tbody>{data.teaching_details.map(item => <tr key={item.workload_id}><td><Link to={`/workload/${item.workload_id}`}>{item.faculty_name}</Link><br />{item.term}<small><br />Home: {item.home_college}</small></td><td>{item.category}{item.category === "Regular Faculty" && <small><br />{peso(item.monthly_salary)} × 12 × 0.000781</small>}</td><td>{peso(item.hourly_rate)}</td><td>{item.paid_hours}{item.imported_overload_hours != null && <small><br />Whole workload: {item.imported_overload_hours} h imported; {item.calculated_overload_hours} h calculated</small>}</td><td>{item.allocations?.map(allocation => <div key={allocation.college}><strong>{allocation.college}</strong>: {allocation.paid_hours} h/week · {allocation.term_pay === null || (allocation.paid_hours > 0 && item.hourly_rate <= 0) ? "Incomplete" : peso(allocation.term_pay)}</div>)}<small>{item.allocation_basis}</small></td><td>{item.weeks || "Not configured"}</td><td>{item.term_pay === null || (item.paid_hours > 0 && item.hourly_rate <= 0) ? "Incomplete" : peso(item.term_pay)}</td></tr>)}</tbody></table></div>}
    </details>
  </section>;
}
