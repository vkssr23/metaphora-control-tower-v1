import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { Money, Num } from "../components/Badges";
import { toast, Toaster } from "sonner";

const STATUSES = ["Available","Assigned","Driving","Off Duty","Home Time","Missing Update","Inactive"];

export default function Drivers() {
  const [drivers, setDrivers] = useState([]);
  const refresh = () => api.get("/drivers").then(r=>setDrivers(r.data));
  useEffect(()=>{ refresh(); },[]);

  const setStatus = async (id, status) => { await api.put(`/drivers/${id}`, {status}); toast.success("Updated"); refresh(); };

  return (
    <div>
      <Toaster position="top-right" theme="dark" />
      <Topbar title="Drivers" subtitle={`${drivers.length} drivers`} />
      <div className="p-6">
        <div className="terminal-card overflow-hidden">
          <div className="overflow-auto">
            <table className="dispatch-table">
              <thead><tr>
                <th>Name</th><th>CDL</th><th>Phone</th><th>Pay Type</th><th>CPM</th><th>Location</th><th>Status</th>
                <th className="text-right">Wk Miles</th><th className="text-right">Wk Rev</th>
                <th className="text-right">OT Pickup</th><th className="text-right">OT Delivery</th>
                <th className="text-right">Missed</th><th className="text-right">Score</th>
              </tr></thead>
              <tbody>
                {drivers.map(d=>(
                  <tr key={d.id} data-testid={`driver-row-${d.id}`}>
                    <td className="text-zinc-100">{d.name}</td>
                    <td className="text-zinc-500">{d.cdl_number}</td>
                    <td>{d.phone}</td>
                    <td>{d.pay_type}</td>
                    <td className="text-right">${d.cents_per_mile}</td>
                    <td>{d.current_location}</td>
                    <td>
                      <select value={d.status} onChange={e=>setStatus(d.id, e.target.value)} data-testid={`driver-status-${d.id}`} className="bg-zinc-900 border border-zinc-800 rounded px-1.5 py-0.5 text-[11px] font-mono">
                        {STATUSES.map(s=><option key={s}>{s}</option>)}
                      </select>
                    </td>
                    <td className="text-right"><Num v={d.weekly_miles} /></td>
                    <td className="text-right"><Money v={d.weekly_revenue} /></td>
                    <td className="text-right">{d.on_time_pickup_pct}%</td>
                    <td className="text-right">{d.on_time_delivery_pct}%</td>
                    <td className={`text-right ${d.missed_updates>0?"text-amber-400":""}`}>{d.missed_updates}</td>
                    <td className={`text-right font-semibold ${d.score>=85?"text-emerald-400":d.score>=70?"text-amber-400":"text-red-400"}`}>{d.score}</td>
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
