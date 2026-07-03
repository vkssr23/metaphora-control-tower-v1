import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { Money } from "../components/Badges";
import { useNavigate } from "react-router-dom";
import { toast, Toaster } from "sonner";

const STATUSES = ["Not Ready","Docs Pending","Ready to Invoice","Invoice Created","Invoice Shared","Payment Pending","Paid","Disputed"];

export default function Invoices() {
  const [invs, setInvs] = useState([]);
  const [loads, setLoads] = useState([]);
  const nav = useNavigate();
  const refresh = ()=>api.get("/invoices").then(r=>setInvs(r.data));
  useEffect(()=>{ refresh(); api.get("/loads").then(r=>setLoads(r.data)); },[]);

  const updateStatus = async (id, status) => { await api.put(`/invoices/${id}`, {status}); toast.success("Updated"); refresh(); };

  const loadMap = Object.fromEntries(loads.map(l=>[l.id,l]));
  const total = invs.filter(i=>!["Paid"].includes(i.status)).reduce((s,i)=>s+(i.amount||0),0);
  const paid = invs.filter(i=>i.status==="Paid").reduce((s,i)=>s+(i.amount||0),0);

  return (
    <div>
      <Toaster position="top-right" theme="dark" />
      <Topbar title="Invoices" subtitle={`${invs.length} invoices · pending ${total.toLocaleString('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0})}`} />
      <div className="p-6">
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
