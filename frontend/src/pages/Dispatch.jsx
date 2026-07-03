import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { StageBadge, RiskBadge } from "../components/Badges";
import { useNavigate } from "react-router-dom";
import { toast, Toaster } from "sonner";

export default function Dispatch() {
  const [loads, setLoads] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [trucks, setTrucks] = useState([]);
  const nav = useNavigate();

  const refresh = () => api.get("/loads").then(r=>setLoads(r.data));
  useEffect(()=>{
    refresh();
    api.get("/drivers").then(r=>setDrivers(r.data));
    api.get("/trucks").then(r=>setTrucks(r.data));
  },[]);

  const assign = async (id, field, val) => { await api.put(`/loads/${id}`, {[field]: val}); toast.success("Assigned"); refresh(); };

  const unassigned = loads.filter(l => l.stage === "Booked" || !l.driver_id || !l.truck_id);

  return (
    <div>
      <Toaster position="top-right" theme="dark" />
      <Topbar title="Dispatch" subtitle={`${unassigned.length} loads pending assignment`} />
      <div className="p-6 space-y-3">
        {unassigned.map(l => (
          <div key={l.id} className="terminal-card p-4 grid grid-cols-1 md:grid-cols-6 gap-3 items-center" data-testid={`dispatch-${l.id}`}>
            <div>
              <div className="font-mono text-xs text-sky-400 cursor-pointer" onClick={()=>nav(`/loads/${l.id}`)}>{l.id}</div>
              <div className="text-xs">{l.customer}</div>
            </div>
            <div className="text-xs font-mono col-span-2">{l.pickup_city},{l.pickup_state} → {l.delivery_city},{l.delivery_state}</div>
            <select value={l.driver_id||""} onChange={e=>assign(l.id,"driver_id",e.target.value)} className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-xs font-mono">
              <option value="">— Assign driver —</option>
              {drivers.map(d=><option key={d.id} value={d.id}>{d.name} ({d.status})</option>)}
            </select>
            <select value={l.truck_id||""} onChange={e=>assign(l.id,"truck_id",e.target.value)} className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-xs font-mono">
              <option value="">— Assign truck —</option>
              {trucks.map(t=><option key={t.id} value={t.id}>{t.truck_number} ({t.status})</option>)}
            </select>
            <div className="flex gap-1"><StageBadge stage={l.stage} /><RiskBadge risk={l.risk} /></div>
          </div>
        ))}
        {unassigned.length===0 && <div className="text-zinc-500">All loads are assigned. 🎯</div>}
      </div>
    </div>
  );
}
