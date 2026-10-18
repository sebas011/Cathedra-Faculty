import { useEffect, useState } from "react";
import { downloadActivity, getActivityPage } from "../api";
import { SkeletonTableRows } from "../components/PageSkeleton";
import TableRegion from "../components/TableRegion";
import type { ActivityEvent } from "../types";

const when = (value:string) => new Intl.DateTimeFormat(undefined,{dateStyle:"medium",timeStyle:"short"}).format(new Date(value));
const emptyFilters = {search:"",date_from:"",date_to:""};

export default function ActivityHistory() {
  const [items,setItems]=useState<ActivityEvent[]>([]);
  const [filters,setFilters]=useState(emptyFilters);
  const [draft,setDraft]=useState(emptyFilters);
  const [page,setPage]=useState(1);
  const [total,setTotal]=useState(0);
  const [refresh,setRefresh]=useState(0);
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(true);
  const [exporting,setExporting]=useState(false);
  useEffect(()=>{
    let active=true;
    setLoading(true);setError("");
    void getActivityPage(filters,page).then(result=>{
      if(active){setItems(result.items);setTotal(result.total);}
    }).catch(caught=>{if(active)setError(caught instanceof Error?caught.message:"Unable to load activity history.");})
      .finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[filters,page,refresh]);
  const exportHistory=async()=>{
    setExporting(true);setError("");
    try{await downloadActivity(filters);}catch(caught){setError(caught instanceof Error?caught.message:"Unable to export activity history.");}
    finally{setExporting(false);}
  };
  return <div className="stack-md">
    <section className="hero-card compact"><div><span className="eyebrow">ADMINISTRATION</span><h1>Activity History</h1><p>Review recorded changes to office records and accounts, sign-in activity, and backup, recovery, and export actions.</p></div><button className="btn secondary" onClick={()=>setRefresh(value=>value+1)} disabled={loading}>Refresh</button></section>
    <form className="form-card" onSubmit={event=>{event.preventDefault();setPage(1);setFilters({...draft});}}>
      <div className="form-grid three"><label>Person, area, or action<input value={draft.search} maxLength={200} onChange={event=>setDraft({...draft,search:event.target.value})}/></label><label>From<input type="date" value={draft.date_from} onChange={event=>setDraft({...draft,date_from:event.target.value})}/></label><label>Through<input type="date" value={draft.date_to} min={draft.date_from||undefined} onChange={event=>setDraft({...draft,date_to:event.target.value})}/></label></div>
      <div className="form-actions"><button className="btn primary" disabled={loading}>Apply filters</button><button type="button" className="btn secondary" disabled={loading||exporting} onClick={()=>void exportHistory()}>{exporting?"Exporting…":"Export filtered history"}</button></div>
    </form>
    {error&&<div className="notice error" role="alert">{error}</div>}
    <section className="data-card"><div className="table-meta" role="status">{total} recorded actions · Page {page} of {Math.max(1,Math.ceil(total/50))}</div>
      <TableRegion label="Activity history"><table><thead><tr><th scope="col">When</th><th scope="col">Person</th><th scope="col">Area</th><th scope="col">Action</th><th scope="col">Changed fields</th></tr></thead><tbody>{loading?<SkeletonTableRows columns={5}/>:error?<tr><td colSpan={5} className="empty-table">Unable to load activity history.</td></tr>:items.length===0?<tr><td colSpan={5} className="empty-table">No actions match these filters.</td></tr>:items.map(item=><tr key={item.id}><td>{when(item.created_at)}</td><td>{item.username||"System"}</td><td>{item.area}</td><td><strong>{item.action}</strong></td><td>{item.changed_fields.join(", ")||"—"}</td></tr>)}</tbody></table></TableRegion>
      <div className="form-actions"><button className="btn secondary" disabled={loading||page<=1} onClick={()=>setPage(value=>value-1)}>Previous</button><button className="btn secondary" disabled={loading||page*50>=total} onClick={()=>setPage(value=>value+1)}>Next</button></div>
    </section>
  </div>;
}
