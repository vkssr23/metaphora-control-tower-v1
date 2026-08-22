import React,{useEffect,useState} from "react";
import api from "../lib/api";
import {toast} from "sonner";

export default function ExecutionEligibility({loadId}){
  const [item,setItem]=useState(null); const [busy,setBusy]=useState(false);
  const load=()=>api.get("/execution-eligibility-cases",{params:{load_id:loadId,limit:1}}).then(r=>setItem(r.data[0]||null)).catch(()=>{});
  // The loader intentionally follows only the load identity.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(()=>{load();},[loadId]);
  const act=async(path,body={})=>{setBusy(true);try{await api.post(`/execution-eligibility-cases/${item.id}/${path}`,body);await load();toast.success("Eligibility updated");}catch(e){const s=e?.response?.status;toast.error(`${s||""} ${typeof e?.response?.data?.detail==="string"?e.response.data.detail:"Eligibility request failed"}`.trim());}finally{setBusy(false)}};
  const create=async()=>{setBusy(true);try{const r=await api.post(`/loads/${loadId}/execution-eligibility-case`,{});setItem(r.data);}catch(e){toast.error(`${e?.response?.status||""} Unable to create eligibility case`.trim());}finally{setBusy(false)}};
  return <div className="terminal-card p-4" data-testid="execution-eligibility">
    <div className="flex items-center justify-between"><div className="kpi-label">Execution Eligibility</div>{!item&&<button disabled={busy} onClick={create} className="text-xs text-sky-400">Create case</button>}</div>
    <div className="mt-2 text-[11px] text-amber-400">Driver, compliance, and HOS statuses shown here are internal administrative/planning checks until connected to authoritative external systems. Truck equipment compatibility is corroborated by NHTSA's public vPIC vehicle registry.</div>
    {item&&<><div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-3 text-xs font-mono"><div>ID: {item.id}</div><div>Version: {item.version}</div><div>Status: {item.status}</div><div>Verdict: {item.verdict}</div></div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3 text-xs"><div><div className="text-zinc-500">Assigned configuration</div><div>Driver: {item.driver_snapshot?.name||"not evaluated"}</div><div>Truck: {item.truck_snapshot?.truck_number||"not evaluated"}</div><div>Trailer: {item.trailer_snapshot?.identifier||"not declared"}</div>
        {!!item.vehicle_verification_snapshot?.vin&&<div className="mt-2 text-zinc-400">NHTSA decode: {item.vehicle_verification_snapshot.make} {item.vehicle_verification_snapshot.model} ({item.vehicle_verification_snapshot.model_year}), {item.vehicle_verification_snapshot.body_class||"body class unknown"} — {item.vehicle_verification_snapshot.risk_level}</div>}</div><div><div className="text-zinc-500">Pickup authorization impact</div><div>{item.status==="eligible"?"Eligibility checkpoints synchronized; passport still controls authorization.":"Pickup authorization must not rely on this case as eligible."}</div></div></div>
      <div className="mt-3 flex flex-wrap gap-2">{item.status==="draft"&&<button disabled={busy} onClick={()=>act("submit")} className="text-xs border border-zinc-700 px-2 py-1 rounded">Submit</button>}<button disabled={busy||item.status==="eligible"} onClick={()=>act("evaluate")} className="text-xs border border-zinc-700 px-2 py-1 rounded">Evaluate</button>{["review_pending","review_required"].includes(item.status)&&<button disabled={busy} onClick={()=>act("eligible")} className="text-xs border border-emerald-700 text-emerald-400 px-2 py-1 rounded">Mark eligible</button>}{item.status==="eligible"&&<button disabled={busy} onClick={()=>act("revoke",{reason:"Administrative eligibility revoked by user"})} className="text-xs border border-red-800 text-red-400 px-2 py-1 rounded">Revoke</button>}</div>
      {!!item.warning_reasons?.length&&<div className="mt-3 text-xs text-amber-400">Warnings: {item.warning_reasons.join(", ")}</div>}{!!item.blocking_reasons?.length&&<div className="mt-2 text-xs text-red-400">Blocking: {item.blocking_reasons.join(", ")}</div>}
      {!!item.checks?.length&&<div className="grid grid-cols-1 md:grid-cols-2 gap-1 mt-3">{item.checks.map(c=><div key={c.type} className="text-[11px] font-mono flex justify-between border-b border-zinc-900"><span>{c.type}</span><span>{c.result}</span></div>)}</div>}</>}
  </div>
}
