import React, { useEffect, useState, useMemo } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { ShieldCheck, ShieldAlert, ShieldX, Filter } from "lucide-react";
import { useNavigate } from "react-router-dom";

export default function Compliance() {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState("all"); // all|red|yellow|green
  const [type, setType] = useState("all"); // all|Driver|Truck
  const nav = useNavigate();

  useEffect(() => { api.get("/compliance").then(r=>setData(r.data)); }, []);

  const filtered = useMemo(()=>{
    if (!data) return [];
    return data.items.filter(i => {
      if (type !== "all" && i.entity_type !== type) return false;
      if (filter === "red") return i.status === "Red";
      if (filter === "yellow") return i.status === "Yellow";
      if (filter === "green") return i.status === "Green";
      return true;
    });
  }, [data, filter, type]);

  if (!data) return <div className="p-6" style={{color:"var(--text-3)"}}>Loading compliance…</div>;

  return (
    <div>
      <Topbar title="Safety & Compliance" subtitle={`${data.summary.total} entities · ${data.summary.dispatch_blocked} dispatch blocked`} />
      <div className="p-6 space-y-4">
        {/* SUMMARY */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Kpi label="Compliant" value={data.summary.green} icon={ShieldCheck} tone="brand" onClick={()=>setFilter("green")} testId="comp-kpi-green" />
          <Kpi label="Warning" value={data.summary.yellow} icon={ShieldAlert} tone="warn" onClick={()=>setFilter("yellow")} testId="comp-kpi-yellow" />
          <Kpi label="Blocker" value={data.summary.red} icon={ShieldX} tone="danger" onClick={()=>setFilter("red")} testId="comp-kpi-red" />
          <Kpi label="Dispatch Blocked" value={data.summary.dispatch_blocked} icon={ShieldX} tone="danger" testId="comp-kpi-blocked" />
        </div>

        {/* FILTERS */}
        <div className="terminal-card p-3 flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-1.5 text-xs" style={{color:"var(--text-3)"}}><Filter className="w-3.5 h-3.5" /> Filters</div>
          <select value={filter} onChange={e=>setFilter(e.target.value)} className="text-xs font-mono rounded px-2 py-1" style={{background:"var(--surface-2)", border:"1px solid var(--border)"}} data-testid="comp-filter-status">
            <option value="all">All Status</option><option value="red">Red / Blocker</option><option value="yellow">Warning</option><option value="green">Compliant</option>
          </select>
          <select value={type} onChange={e=>setType(e.target.value)} className="text-xs font-mono rounded px-2 py-1" style={{background:"var(--surface-2)", border:"1px solid var(--border)"}} data-testid="comp-filter-type">
            <option value="all">All Types</option><option value="Driver">Drivers</option><option value="Truck">Trucks</option>
          </select>
          <div className="text-xs ml-auto" style={{color:"var(--text-3)"}}>{filtered.length} shown</div>
        </div>

        {/* LIST */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {filtered.map(item => (
            <div key={`${item.entity_type}-${item.entity_id}`} className="terminal-card p-4" data-testid={`comp-${item.entity_id}`}>
              <div className="flex items-center justify-between mb-2">
                <div>
                  <div className="text-xs font-mono uppercase" style={{color:"var(--text-3)"}}>{item.entity_type}</div>
                  <div className="font-display font-bold">{item.entity_name}</div>
                </div>
                <span className={`badge risk-${item.status}`}>{item.status}</span>
              </div>

              {item.blockers.length>0 && (
                <div className="mb-2">
                  <div className="text-[10px] font-mono uppercase mb-1" style={{color:"var(--danger)"}}>Blockers</div>
                  {item.blockers.map((b,i)=>(<div key={i} className="text-xs" style={{color:"var(--danger)"}}>• {b}</div>))}
                </div>
              )}
              {item.warnings.length>0 && (
                <div className="mb-2">
                  <div className="text-[10px] font-mono uppercase mb-1" style={{color:"var(--warn)"}}>Warnings</div>
                  {item.warnings.map((w,i)=>(<div key={i} className="text-xs" style={{color:"var(--warn)"}}>• {w}</div>))}
                </div>
              )}
              {item.blockers.length===0 && item.warnings.length===0 && (
                <div className="text-xs" style={{color:"var(--brand)"}}>✓ All checks pass</div>
              )}

              <div className="grid grid-cols-2 gap-2 mt-3 pt-3 border-t text-[11px] font-mono" style={{borderColor:"var(--border)", color:"var(--text-2)"}}>
                {item.entity_type === "Driver" ? (<>
                  <div>CDL: {item.details.cdl_days !== null ? `${item.details.cdl_days}d` : "—"}</div>
                  <div>Medical: {item.details.medical_days !== null ? `${item.details.medical_days}d` : "—"}</div>
                  <div>MVR: {item.details.mvr_status || "—"}</div>
                  <div>DACH: {item.details.clearinghouse_status || "—"}</div>
                </>) : (<>
                  <div>Insurance: {item.details.insurance_days !== null ? `${item.details.insurance_days}d` : "—"}</div>
                  <div>Registration: {item.details.registration_days !== null ? `${item.details.registration_days}d` : "—"}</div>
                  <div>Inspection: {item.details.inspection_days !== null ? `${item.details.inspection_days}d` : "—"}</div>
                  <div>Maint: {item.details.maintenance_status || "—"}</div>
                </>)}
              </div>

              <div className="mt-3 pt-3 border-t flex items-center justify-between text-xs" style={{borderColor:"var(--border)"}}>
                <span style={{color:"var(--text-3)"}}>Dispatch allowed:</span>
                <span className={`badge ${item.dispatch_allowed?"risk-Green":"risk-Red"}`}>{item.dispatch_allowed?"YES":"NO"}</span>
              </div>
              <button onClick={()=>nav(item.entity_type==="Driver"?"/drivers":"/trucks")} className="mt-2 w-full text-xs rounded px-2 py-1.5" style={{border:"1px solid var(--border)"}}>Open {item.entity_type} record →</button>
            </div>
          ))}
          {filtered.length===0 && <div className="terminal-card p-6 text-center col-span-2" style={{color:"var(--text-3)"}}>No matching entities</div>}
        </div>
      </div>
    </div>
  );
}

function Kpi({ label, value, icon: Icon, tone, onClick, testId }) {
  const c = tone==="brand"?"var(--brand)":tone==="warn"?"var(--warn)":tone==="danger"?"var(--danger)":"var(--text)";
  return (
    <div onClick={onClick} data-testid={testId} className={`terminal-card p-3 ${onClick?"cursor-pointer":""}`}>
      <div className="flex items-center justify-between mb-1">
        <div className="kpi-label">{label}</div>
        <Icon className="w-3.5 h-3.5" style={{color: c}} />
      </div>
      <div className="kpi-value" style={{color: c}}>{value}</div>
    </div>
  );
}
