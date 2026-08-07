import React,{useEffect,useState} from "react";
import api from "../lib/api";
import {toast} from "sonner";

export default function SecurePickupRelease({loadId}){
  const [item,setItem]=useState(null),[busy,setBusy]=useState(false);
  const load=()=>api.get("/pickup-release-cases",{params:{load_id:loadId,limit:1}}).then(r=>setItem(r.data[0]||null)).catch(()=>{});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(()=>{load()},[loadId]);
  const act=async(path,body={})=>{setBusy(true);try{await api.post(`/pickup-release-cases/${item.id}/${path}`,body);await load();toast.success("Pickup release updated")}catch(e){const s=e?.response?.status,d=e?.response?.data?.detail;toast.error(`${s||""} ${typeof d==="string"?d:"Pickup release request failed"}`.trim())}finally{setBusy(false)}};
  const create=async()=>{setBusy(true);try{setItem((await api.post(`/loads/${loadId}/pickup-release-case`,{})).data)}catch(e){toast.error(`${e?.response?.status||""} Unable to create pickup release case`.trim())}finally{setBusy(false)}};
  return <div className="terminal-card p-4" data-testid="secure-pickup-release">
    <div className="flex items-center justify-between"><div className="kpi-label">Secure Pickup Release</div>{!item&&<button disabled={busy} onClick={create} className="text-xs text-sky-400">Create case</button>}</div>
    <div className="mt-2 text-[11px] text-amber-400">Pickup release is based on current internal records and human review. Identity, facility, contact, telematics, and custody are not externally verified unless a connected authoritative source explicitly provides that evidence.</div>
    {item&&<><div className="grid grid-cols-2 md:grid-cols-5 gap-2 mt-3 text-xs font-mono"><div>ID: {item.id}</div><div>Version: {item.version}</div><div>Status: {item.status}</div><div>Verdict: {item.verdict}</div><div>Custody: {item.custody_state}</div></div>
      <div className="mt-3 text-xs">Driver: {item.assignment_snapshot?.driver_id||"missing"} · Truck: {item.assignment_snapshot?.truck_id||"missing"} · Trailer: {item.assignment_snapshot?.trailer_identifier||"missing"}</div>
      <div className="mt-3 flex flex-wrap gap-2">{item.status==="draft"&&<button disabled={busy} onClick={()=>act("submit")} className="text-xs border px-2 py-1 rounded">Submit</button>}{!["released","pickup_confirmed","exception"].includes(item.status)&&<button disabled={busy} onClick={()=>act("evaluate")} className="text-xs border px-2 py-1 rounded">Evaluate</button>}{["review_pending","review_required"].includes(item.status)&&<button disabled={busy} onClick={()=>act("release-ready")} className="text-xs border border-emerald-700 px-2 py-1 rounded">Mark release ready</button>}{item.status==="release_ready"&&<button disabled={busy} onClick={()=>act("release")} className="text-xs border border-emerald-500 text-emerald-400 px-2 py-1 rounded">Human release</button>}{item.status==="released"&&<><button disabled={busy} onClick={()=>act("confirm-pickup",{source:"manual"})} className="text-xs border px-2 py-1 rounded">Confirm pickup</button><button disabled={busy} onClick={()=>act("revoke",{reason:"Pickup authorization revoked by owner review"})} className="text-xs border border-red-700 text-red-400 px-2 py-1 rounded">Revoke</button><button disabled={busy} onClick={()=>act("exception",{exception_type:"other",reason:"Pickup exception opened for human review"})} className="text-xs border border-amber-700 px-2 py-1 rounded">Open exception</button></>}</div>
      {!!item.blocking_reasons?.length&&<div className="mt-2 text-xs text-red-400">Blockers: {item.blocking_reasons.join(", ")}</div>}{!!item.warning_reasons?.length&&<div className="mt-2 text-xs text-amber-400">Warnings: {item.warning_reasons.join(", ")}</div>}
      {!!item.checklist_items?.length&&<div className="grid md:grid-cols-2 mt-3 gap-1">{item.checklist_items.map(x=><div key={x.type} className="text-[11px] font-mono flex justify-between border-b border-zinc-900"><span>{x.type}</span><span>{x.result}</span></div>)}</div>}
      {!!item.custody_events?.length&&<div className="mt-3"><div className="text-xs text-zinc-500">Custody event timeline</div>{item.custody_events.map(x=><div key={x.id} className="text-[11px] font-mono">{x.occurred_at?.slice(0,16)} · {x.type}</div>)}</div>}</>}
  </div>
}
