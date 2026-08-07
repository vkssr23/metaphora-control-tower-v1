/* eslint-disable react-hooks/exhaustive-deps -- intentional mount-only effects */
import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { Money } from "../components/Badges";
import { useNavigate } from "react-router-dom";
import { toast, Toaster } from "sonner";
import { useAuth } from "../lib/auth";

const STATUSES = ["Not Ready","Docs Pending","Ready to Invoice","Invoice Created","Invoice Shared","Payment Pending","Paid","Disputed"];

export default function Invoices() {
  const [invs, setInvs] = useState([]);
  const [loads, setLoads] = useState([]);
  const [cases, setCases] = useState([]);
  const { user } = useAuth();
  const nav = useNavigate();
  const refresh = ()=>Promise.all([api.get("/invoices"),api.get("/invoice-readiness-cases")]).then(([i,c])=>{setInvs(i.data);setCases(c.data);});
  useEffect(()=>{ refresh().catch(()=>setCases([])); api.get("/loads").then(r=>setLoads(r.data)); },[]);

  const act = async (item, action) => {
    try { await api.post(`/invoice-readiness-cases/${item.id}/${action}`, {version:item.version}); toast.success(action.replaceAll("-"," ")); refresh(); }
    catch (e) { const code=e.response?.status; toast.error(`${code || "Error"}: ${e.response?.data?.detail || "Request failed"}`); }
  };

  const updateStatus = async (id, status) => { await api.put(`/invoices/${id}`, {status}); toast.success("Updated"); refresh(); };

  const loadMap = Object.fromEntries(loads.map(l=>[l.id,l]));
  const total = invs.filter(i=>!["Paid"].includes(i.status)).reduce((s,i)=>s+(i.amount||0),0);
  const paid = invs.filter(i=>i.status==="Paid").reduce((s,i)=>s+(i.amount||0),0);

  return (
    <div>
      <Toaster position="top-right" theme="dark" />
      <Topbar title="Invoices" subtitle={`${invs.length} invoices · pending ${total.toLocaleString('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0})}`} />
      <div className="p-6">
        <div className="terminal-card p-4 mb-4">
          <div className="flex items-center justify-between mb-3"><div><div className="text-sm font-semibold">Delivery evidence & invoice readiness</div><div className="text-[11px] text-zinc-500">Human-controlled finance handoff</div></div><div className="text-xs text-zinc-400">{cases.length} active cases</div></div>
          <div className="space-y-2">
            {cases.length===0 && <div className="text-xs text-zinc-500">No invoice-readiness cases yet. Create one from a delivered load through the API workflow.</div>}
            {cases.map(c=><div key={c.id} className="border border-zinc-800 rounded p-3 text-xs">
              <div className="flex flex-wrap gap-3 items-center"><span className="text-sky-400">{c.load_id}</span><span>{c.status}</span><span className={c.verdict==="ready"?"text-emerald-400":"text-amber-400"}>{c.verdict}</span><span>Billable: {c.billable_total ? <Money v={Number(c.billable_total)}/> : "unresolved"}</span><span>POD: {c.readiness_items?.find(x=>x.type==="pod_present")?.result || "pending"}</span><span>Rate confirmation: {c.readiness_items?.find(x=>x.type==="rate_confirmation_current")?.result || "pending"}</span></div>
              {!!c.findings?.length && <div className="mt-2 text-red-300">Blockers: {c.findings.filter(x=>x.blocking && x.status==="open").map(x=>x.summary).join(", ") || "none"}</div>}
              <div className="mt-2 flex gap-2">
                {["finance","owner","admin"].includes(user?.role) && <button className="btn-secondary" onClick={()=>act(c,"refresh")}>Refresh</button>}
                {["finance","owner","admin"].includes(user?.role) && <button className="btn-secondary" onClick={()=>act(c,"evaluate")}>Evaluate</button>}
                {["owner","admin"].includes(user?.role) && c.status==="ready" && <button className="btn-primary" onClick={()=>act(c,"approve")}>Approve readiness</button>}
                {["owner","admin"].includes(user?.role) && c.status==="approved" && <button className="btn-primary" onClick={()=>act(c,"invoice")}>Create invoice package</button>}
              </div>
            </div>)}
          </div>
          <p className="mt-3 text-[10px] leading-4 text-zinc-500">Invoice readiness is based on current internal delivery, rate and document records. Document authenticity, broker receipt, factoring acceptance, payment status and external accounting submission are not verified unless an authoritative integration explicitly provides that evidence.</p>
        </div>
        <div className="grid grid-cols-3 gap-3 mb-4">
          <div className="terminal-card p-3"><div className="kpi-label">Pending</div><div className="kpi-value text-amber-400"><Money v={total} /></div></div>
          <div className="terminal-card p-3"><div className="kpi-label">Paid</div><div className="kpi-value text-emerald-400"><Money v={paid} /></div></div>
          <div className="terminal-card p-3"><div className="kpi-label">Count</div><div className="kpi-value">{invs.length}</div></div>
        </div>
        <div className="terminal-card overflow-hidden">
          <div className="overflow-auto">
            <table className="dispatch-table">
              <thead><tr>
                <th>Invoice</th><th>Load</th><th>Customer</th><th className="text-right">Amount</th>
                <th>Status</th><th>Due</th><th>Paid</th>
              </tr></thead>
              <tbody>
                {invs.map(i=>(
                  <tr key={i.id} data-testid={`inv-row-${i.id}`}>
                    <td className="text-sky-400">{i.id}</td>
                    <td className="cursor-pointer" onClick={()=>nav(`/loads/${i.load_id}`)}>{i.load_id}</td>
                    <td>{loadMap[i.load_id]?.customer || i.customer}</td>
                    <td className="text-right"><Money v={i.amount} /></td>
                    <td>
                      <select value={i.status} onChange={e=>updateStatus(i.id, e.target.value)} data-testid={`inv-status-${i.id}`} className="bg-zinc-900 border border-zinc-800 rounded px-1.5 py-0.5 text-[11px] font-mono">
                        {STATUSES.map(s=><option key={s}>{s}</option>)}
                      </select>
                    </td>
                    <td className="text-[10px] text-zinc-500">{i.due_date?.slice(0,10)}</td>
                    <td className="text-[10px] text-zinc-500">{i.paid_date?.slice(0,10) || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
