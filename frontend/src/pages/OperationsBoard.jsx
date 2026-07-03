import React, { useEffect, useMemo, useState } from "react";
import Topbar from "../components/Topbar";
import { StageBadge, RiskBadge, Money, Num } from "../components/Badges";
import api from "../lib/api";
import { useNavigate } from "react-router-dom";
import { Filter } from "lucide-react";

const COLUMNS = [
  "Booked","Assigned","Dispatched","Pickup Started","Arrived Pickup","Loaded",
  "In Transit","Arrived Delivery","Delivered","Docs Pending","Invoice Pending",
  "Payment Pending","Closed","Exception"
];

export default function OperationsBoard() {
  const [loads, setLoads] = useState([]);
  const [trucks, setTrucks] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [filter, setFilter] = useState({ risk: "", customer: "", driver: "" });
  const nav = useNavigate();

  useEffect(() => {
    api.get("/loads").then(r=>setLoads(r.data));
    api.get("/trucks").then(r=>setTrucks(r.data));
    api.get("/drivers").then(r=>setDrivers(r.data));
  }, []);

  const truckMap = useMemo(()=>Object.fromEntries(trucks.map(t=>[t.id,t])), [trucks]);
  const driverMap = useMemo(()=>Object.fromEntries(drivers.map(d=>[d.id,d])), [drivers]);

  const filtered = loads.filter(l => {
    if (filter.risk && l.risk !== filter.risk) return false;
    if (filter.customer && !l.customer.toLowerCase().includes(filter.customer.toLowerCase())) return false;
    if (filter.driver && l.driver_id !== filter.driver) return false;
    return true;
  });

  return (
    <div>
      <Topbar title="Operations Board" subtitle={`${filtered.length} loads · live kanban`} />
      <div className="px-6 py-3 border-b border-zinc-800 flex items-center gap-3 flex-wrap bg-[#0A0A0C]">
        <div className="flex items-center gap-2 text-xs text-zinc-500"><Filter className="w-3.5 h-3.5" /> Filters</div>
        <select data-testid="filter-risk" value={filter.risk} onChange={e=>setFilter({...filter, risk:e.target.value})} className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs font-mono">
          <option value="">All Risk</option><option>Low</option><option>Medium</option><option>High</option><option>Critical</option>
        </select>
        <select data-testid="filter-driver" value={filter.driver} onChange={e=>setFilter({...filter, driver:e.target.value})} className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs font-mono">
          <option value="">All Drivers</option>
          {drivers.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <input data-testid="filter-customer" placeholder="Customer…" value={filter.customer} onChange={e=>setFilter({...filter, customer:e.target.value})} className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs font-mono w-40" />
      </div>
      <div className="overflow-x-auto p-4">
        <div className="flex gap-3 min-w-max pb-4">
          {COLUMNS.map(col => {
            const cards = filtered.filter(l => (col==="Exception" ? l.risk==="Critical" : l.stage===col));
            return (
              <div key={col} className="w-[280px] shrink-0" data-testid={`kanban-col-${col}`}>
                <div className="flex items-center justify-between mb-2 px-1">
                  <div className="font-mono text-[10.5px] uppercase tracking-widest text-zinc-400">{col}</div>
                  <div className="text-[10px] text-zinc-500 font-mono">{cards.length}</div>
                </div>
                <div className="space-y-2 min-h-[80px]">
                  {cards.map(l => (
                    <div
                      key={l.id}
                      onClick={()=>nav(`/loads/${l.id}`)}
                      data-testid={`load-card-${l.id}`}
                      className="terminal-card p-3 cursor-pointer hover:border-sky-500/50 transition-colors"
                    >
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="font-mono text-xs text-sky-400 font-semibold">{l.id}</div>
                        <RiskBadge risk={l.risk} />
                      </div>
                      <div className="text-xs text-zinc-300 mb-1.5 font-medium">{l.customer}</div>
                      <div className="font-mono text-[11px] text-zinc-400 mb-2">
                        {l.pickup_city}, {l.pickup_state} → {l.delivery_city}, {l.delivery_state}
                      </div>
                      <div className="flex items-center justify-between text-[11px] font-mono text-zinc-500">
                        <span><Money v={l.rate} /></span>
                        <span><Num v={l.miles} suffix="mi" /></span>
                        <span className="text-emerald-400">${l.rpm}/mi</span>
                      </div>
                      <div className="mt-2 flex items-center justify-between text-[10px] font-mono text-zinc-500">
                        <span>{driverMap[l.driver_id]?.name?.split(" ")[0] || "—"}</span>
                        <span>{truckMap[l.truck_id]?.truck_number || "—"}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
