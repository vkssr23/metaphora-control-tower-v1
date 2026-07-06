/* eslint-disable react-hooks/exhaustive-deps -- intentional mount-only effects */
import React, { useEffect, useState, useMemo } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { Money, Num } from "../components/Badges";
import { BarChart3 } from "lucide-react";

export default function Reports() {
  const [stats, setStats] = useState(null);
  const [loads, setLoads] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [trucks, setTrucks] = useState([]);
  const [invs, setInvs] = useState([]);

  useEffect(()=>{
    api.get("/dashboard/stats").then(r=>setStats(r.data));
    api.get("/loads").then(r=>setLoads(r.data));
    api.get("/drivers").then(r=>setDrivers(r.data));
    api.get("/trucks").then(r=>setTrucks(r.data));
    api.get("/invoices").then(r=>setInvs(r.data));
  },[]);

  const highRisk = useMemo(() => loads.filter(l=>l.risk==="High"||l.risk==="Critical").slice(0,5), [loads]);
  const missingPod = useMemo(() => loads.filter(l=>l.stage==="Delivered" && l.pod_status==="Pending").slice(0,5), [loads]);
  const lossLoads = useMemo(() => loads.map(l=>({...l, net: l.rate - (l.fuel_cost+l.tolls+l.lumper+l.driver_pay+l.factoring_fee+l.other_expenses)})).filter(l=>l.net<0), [loads]);
  const topDrivers = useMemo(() => [...drivers].sort((a,b)=>b.score-a.score).slice(0,5), [drivers]);
  const topTrucks  = useMemo(() => [...trucks].sort((a,b)=>b.profit_per_mile-a.profit_per_mile).slice(0,5), [trucks]);
  const delayed    = useMemo(() => loads.filter(l=>l.risk==="Critical").slice(0,10), [loads]);

  if (!stats) return <div className="p-6 text-zinc-500">Loading…</div>;

  const Section = ({title, children}) => (
    <div className="terminal-card p-4">
      <div className="kpi-label mb-2 flex items-center gap-1.5"><BarChart3 className="w-3.5 h-3.5" />{title}</div>
      {children}
    </div>
  );

  return (
    <div>
      <Topbar title="Reports" subtitle="Daily owner report + operational breakdowns" />
      <div className="p-6 grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Section title="Daily Owner Report">
          <div className="grid grid-cols-2 gap-2 text-xs font-mono">
            <div><div className="text-zinc-500">Revenue</div><div className="text-lg font-bold"><Money v={stats.total_revenue} /></div></div>
            <div><div className="text-zinc-500">Profit</div><div className="text-lg font-bold text-emerald-400"><Money v={stats.gross_profit} /></div></div>
            <div><div className="text-zinc-500">Active loads</div><div>{stats.active_loads}</div></div>
            <div><div className="text-zinc-500">In transit</div><div>{stats.loads_transit}</div></div>
            <div><div className="text-zinc-500">Delivered</div><div>{stats.loads_delivered}</div></div>
            <div><div className="text-zinc-500">Pending BOL/POD</div><div className="text-amber-400">{stats.bol_pending}</div></div>
            <div><div className="text-zinc-500">Pending invoice</div><div className="text-amber-400"><Money v={stats.pending_invoice_amount} /></div></div>
            <div><div className="text-zinc-500">Cash expected</div><div className="text-emerald-400"><Money v={stats.cash_expected_week} /></div></div>
            <div><div className="text-zinc-500">Idle trucks</div><div>{stats.idle_trucks}</div></div>
            <div><div className="text-zinc-500">Missing updates</div><div className="text-amber-400">{stats.drivers_missing_updates}</div></div>
            <div><div className="text-zinc-500">High-risk loads</div><div className="text-red-400">{stats.at_risk_loads}</div></div>
          </div>
          <div className="mt-3 pt-3 border-t border-zinc-800 text-xs">
            <div className="text-zinc-500 font-mono">Top issue today</div>
            <div>{stats.at_risk_loads>0 ? `${stats.at_risk_loads} loads at risk — review Operations Board` : "All loads on track"}</div>
            <div className="text-zinc-500 font-mono mt-2">Recommended action</div>
            <div>{stats.bol_pending>0 ? `Chase POD on ${stats.bol_pending} delivered loads` : "Focus on invoice collection"}</div>
          </div>
        </Section>

        <Section title="High-Risk Loads">
          <div className="space-y-1.5 text-xs font-mono">
            {highRisk.length===0 && <div className="text-zinc-500">None</div>}
            {highRisk.map(l=>(
              <div key={l.id} className="flex items-center justify-between">
                <span><span className="text-sky-400">{l.id}</span> · {l.pickup_city}→{l.delivery_city}</span>
                <span className="text-red-400">{l.risk}</span>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Missing POD (Delivered)">
          <div className="space-y-1.5 text-xs font-mono">
            {missingPod.length===0 && <div className="text-zinc-500">All PODs collected</div>}
            {missingPod.map(l=>(<div key={l.id}><span className="text-sky-400">{l.id}</span> · {l.customer}</div>))}
          </div>
        </Section>

        <Section title="Loss-Making Loads">
          <div className="space-y-1.5 text-xs font-mono">
            {lossLoads.length===0 && <div className="text-zinc-500">No losses</div>}
            {lossLoads.map(l=>(
              <div key={l.id} className="flex items-center justify-between">
                <span><span className="text-sky-400">{l.id}</span> · {l.customer}</span>
                <span className="text-red-400"><Money v={l.net} /></span>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Top Drivers (Score)">
          <div className="space-y-1 text-xs font-mono">
            {topDrivers.map(d=>(
              <div key={d.id} className="flex justify-between"><span>{d.name}</span><span className="text-emerald-400">{d.score}</span></div>
            ))}
          </div>
        </Section>

        <Section title="Top Trucks (PPM)">
          <div className="space-y-1 text-xs font-mono">
            {topTrucks.map(t=>(
              <div key={t.id} className="flex justify-between"><span>{t.truck_number}</span><span className="text-emerald-400">${t.profit_per_mile}/mi</span></div>
            ))}
          </div>
        </Section>

        <Section title="Invoice Aging">
          <div className="space-y-1 text-xs font-mono">
            {invs.map(i=>(
              <div key={i.id} className="flex justify-between"><span>{i.id} · {i.customer}</span><span><Money v={i.amount} /> · {i.status}</span></div>
            ))}
            {invs.length===0 && <div className="text-zinc-500">No invoices</div>}
          </div>
        </Section>

        <Section title="Delayed Loads">
          <div className="space-y-1 text-xs font-mono">
            {delayed.map(l=>(
              <div key={l.id} className="flex justify-between"><span>{l.id} · {l.customer}</span><span className="text-red-400">Critical</span></div>
            ))}
          </div>
        </Section>
      </div>
    </div>
  );
}
