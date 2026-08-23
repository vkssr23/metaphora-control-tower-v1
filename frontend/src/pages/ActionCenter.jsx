import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Check, Filter, RefreshCw } from "lucide-react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { useAuth } from "../lib/auth";

const categories=["all","execution","safety","fraud_risk","documents","finance","reconciliation","platform_integrity"];
const severities=["all","critical","high","medium","low"];

export default function ActionCenter(){
  const [data,setData]=useState(null),[error,setError]=useState(""),[category,setCategory]=useState("all"),[severity,setSeverity]=useState("all"),[owner,setOwner]=useState("all"),[busy,setBusy]=useState("");
  const nav=useNavigate();
  const {user}=useAuth();
  const load=useCallback(async()=>{setError("");try{const params={};if(category!=="all")params.category=category;if(severity!=="all")params.severity=severity;if(owner!=="all")params.owner_role=owner;setData((await api.get("/action-center",{params})).data);}catch(e){setError(e.response?.data?.detail||"Action Center is unavailable");}},[category,severity,owner]);
  useEffect(()=>{load();},[load]);
  async function acknowledge(item){setBusy(item.id);setError("");try{await api.post(`/action-center/${item.id}/acknowledge`,{version:item.version});await load();}catch(e){setError(e.response?.data?.detail||"Acknowledgement failed");}finally{setBusy("");}}
  function source(item){if(item.load_id)nav(`/loads/${item.load_id}`);else if(item.category==="finance")nav("/invoices");else if(item.category==="platform_integrity")nav("/settings");}
  return <div><Topbar title="Action Center" subtitle="Deterministic operator work queue · source workflows remain authoritative"/><div className="p-6 space-y-4">
    <div className="terminal-card p-3 flex flex-wrap items-center gap-3"><Filter className="w-4 h-4"/><select data-testid="action-filter-category" value={category} onChange={e=>setCategory(e.target.value)}>{categories.map(x=><option key={x} value={x}>{x.replaceAll("_"," ")}</option>)}</select><select data-testid="action-filter-severity" value={severity} onChange={e=>setSeverity(e.target.value)}>{severities.map(x=><option key={x}>{x}</option>)}</select><select data-testid="action-filter-owner" value={owner} onChange={e=>setOwner(e.target.value)}><option value="all">all owners</option><option value="operations">operations</option><option value="safety">safety</option><option value="finance">finance</option><option value="admin">admin</option></select><button onClick={load} className="ml-auto flex items-center gap-1 text-xs"><RefreshCw className="w-3.5 h-3.5"/> Refresh</button></div>
    {error&&<div className="terminal-card p-4" role="alert" style={{color:"var(--danger)"}}>{error}</div>}
    {!data&&!error&&<div className="terminal-card p-8 text-center" style={{color:"var(--text-3)"}}>Loading current projection…</div>}
    {data?.items.length===0&&<div className="terminal-card p-8 text-center"><Check className="w-6 h-6 mx-auto mb-2" style={{color:"var(--brand)"}}/><div className="font-display font-bold">No matching active actions</div><div className="text-xs mt-1" style={{color:"var(--text-3)"}}>Current as of the latest request-driven projection refresh.</div></div>}
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">{data?.items.map(item=><article key={item.id} className="terminal-card p-4" data-testid={`action-${item.id}`}><div className="flex justify-between gap-3"><div><div className="flex gap-2 mb-1"><span className={`badge risk-${item.severity==="critical"?"Red":item.severity==="high"?"Yellow":"Green"}`}>{item.severity}</span><span className="badge">{item.status}</span></div><h2 className="font-display font-bold">{item.title}</h2></div><AlertTriangle className="w-5 h-5" style={{color:item.severity==="critical"?"var(--danger)":"var(--warn)"}}/></div><p className="text-sm mt-2" style={{color:"var(--text-2)"}}>{item.summary}</p><div className="grid grid-cols-2 gap-2 text-xs font-mono mt-3"><span>Owner: {item.owner_role}</span><span>Age: {formatAge(item.age_seconds)}</span><span>Category: {item.category}</span><span>{item.load_id?`Load: ${item.load_id}`:`Entity: ${item.entity_id}`}</span></div>{item.supporting_reasons?.length>0&&<div className="text-xs mt-3" style={{color:"var(--text-3)"}}>Supporting impacts: {item.supporting_reasons.join(", ")}</div>}<div className="mt-4 pt-3 border-t flex flex-wrap items-center gap-2" style={{borderColor:"var(--border)"}}><button onClick={()=>source(item)} className="text-xs rounded px-3 py-1.5" style={{border:"1px solid var(--border)"}}>{item.recommended_action_label} →</button>{item.status==="open"&&canPlausiblyAcknowledge(user,item)&&<button disabled={busy===item.id} onClick={()=>acknowledge(item)} data-testid={`ack-${item.id}`} className="text-xs rounded px-3 py-1.5 ml-auto" style={{background:"var(--brand)",color:"var(--accent-on)"}}>{busy===item.id?"Acknowledging…":"Acknowledge"}</button>}</div></article>)}</div>
  </div></div>;
}
function formatAge(seconds){if(seconds<60)return `${seconds}s`;if(seconds<3600)return `${Math.floor(seconds/60)}m`;if(seconds<86400)return `${Math.floor(seconds/3600)}h`;return `${Math.floor(seconds/86400)}d`;}
function canPlausiblyAcknowledge(user,item){if(["owner","admin"].includes(user?.role))return true;const roles={operations:["operations","dispatcher"],safety:["safety","compliance"],finance:["finance"]};return (roles[item.owner_role]||[]).includes(user?.role);}
