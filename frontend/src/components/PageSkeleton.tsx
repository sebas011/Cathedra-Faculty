type SkeletonVariant = "detail" | "table" | "form" | "dashboard";

export default function PageSkeleton({ label, variant = "detail" }: { label: string; variant?: SkeletonVariant }) {
  return <div className={`page-skeleton page-skeleton-${variant}`} role="status" aria-label={label} aria-busy="true">
    <span className="sr-only">{label}</span>
    <div className="skeleton-heading"><span className="skeleton-bar short" /><span className="skeleton-bar title" /><span className="skeleton-bar medium" /></div>
    {variant === "dashboard" && <div className="skeleton-metrics">{Array.from({ length: 4 }, (_, index) => <span className="skeleton-metric" key={index}><span className="skeleton-bar medium" /><span className="skeleton-bar title" /></span>)}</div>}
    <div className="skeleton-content">{Array.from({ length: variant === "form" ? 4 : 5 }, (_, index) => <span className={`skeleton-bar ${index % 3 === 0 ? "medium" : "full"}`} key={index} />)}</div>
  </div>;
}

export function SkeletonTableRows({ columns, rows = 5 }: { columns: number; rows?: number }) {
  return <>{Array.from({ length: rows }, (_, row) => <tr className="skeleton-table-row" key={row}>{Array.from({ length: columns }, (_, column) => <td key={column}><span className={`skeleton-bar ${column === 0 ? "medium" : "full"}`} /></td>)}</tr>)}</>;
}
