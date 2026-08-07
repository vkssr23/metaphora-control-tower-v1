/* eslint-disable react-hooks/exhaustive-deps -- intentional mount-only load */
import React,{useEffect,useState} from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import {useNavigate} from "react-router-dom";

const tone={healthy:"text-emerald-400",watch:"text-amber-400",at_risk:"text-orange-400",critical:"text-red-400"};
export default function InTransit(){
 const [sessions,setSessions]=useState([]);const [errors,setErrors]=useState("");const nav=useNavigate();
 useEffect(()=>{api.get("/execution-sessions").then(r=>setSessions(r.data)).catch(e=>setErrors(e?.response?.data?.detail||"Execution sessions are unavailable"));},[]);
 return <div>
  <Topbar title="In-Transit Execution Control" subtitle={`${sessions.filter(s=>!['completed','cancelled'].includes(s.status)).length} controlled execution sessions`}/>
  <div className="p-6 space-y-4">
   <div className="terminal-card p-4 border-amber-500/30 text-xs text-amber-300">Live GPS, telematics, traffic, weather and ELD data are not connected in this phase. Progress and ETA information shown here may be manually reported or internally calculated.</div>
   {errors&&<div className="terminal-card p-4 text-red-400">{typeof errors==="string"?errors:JSON.stringify(errors)}</div>}
   {sessions.map(s=>{const p=s.planned_snapshot||{},a=s.actual_snapshot||{},eta=s.eta_snapshot||{},det=s.detention_snapshot||{},exceptions=s.open_exception_count||0;return <button key={s.id} onClick={()=>nav(`/loads/${s.load_id}`)} className="terminal-card p-4 w-full text-left hover:border-sky-500/50" data-testid={`execution-${s.id}`}>
    <div className="flex flex-wrap justify-between gap-3 mb-4"><div><div className="font-mono text-xs text-sky-400">{s.id}</div><div className="font-semibold">Load {s.load_id}</div></div><div className="text-right"><div className="uppercase text-xs">{s.status} · {s.execution_state}</div><div className={`text-xs ${tone[s.execution_health]||"text-zinc-400"}`}>{s.execution_health||"unknown"} · {exceptions} open exception{exceptions===1?"":"s"}</div></div></div>
    <div className="grid grid-cols-2 md:grid-cols-6 gap-3 text-xs font-mono">
     <div><span className="text-zinc-500 block">Driver / Truck</span>{p.driver_id||"—"} / {p.truck_id||"—"}</div>
     <div><span className="text-zinc-500 block">Trailer</span>{p.trailer_identifier||"—"}</div>
     <div><span className="text-zinc-500 block">Manual location</span>{a.current_location_text||"Not reported"}</div>
     <div><span className="text-zinc-500 block">ETA</span>{eta.current_eta||"Unknown"} ({eta.status||"unknown"})</div>
     <div><span className="text-zinc-500 block">Stop progress</span>{(s.current_stop_index||0)+1} / {s.total_stops||0}</div>
     <div><span className="text-zinc-500 block">Detention / POD</span>{det.state||"none"} / {s.status==="delivery_confirmed"?"required to complete":"pending"}</div>
    </div>
   </button>})}
   {!sessions.length&&!errors&&<div className="text-zinc-500 text-sm">No execution sessions have started.</div>}
  </div>
 </div>;
}
