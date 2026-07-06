/* eslint-disable react-hooks/exhaustive-deps -- intentional mount-only effects */
import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { RiskBadge } from "../components/Badges";
import { CloudRain, Route as RouteIcon } from "lucide-react";

export default function WeatherRoad() {
  const [loads, setLoads] = useState([]);
  const [wx, setWx] = useState({});
  const [rd, setRd] = useState({});

  useEffect(()=>{
    api.get("/loads").then(async r=>{
      const active = r.data.filter(l => !["Closed","Booked"].includes(l.stage));
      setLoads(active);
      for (const l of active.slice(0,20)) {
        api.post("/weather/check", { pickup: l.pickup_city, delivery: l.delivery_city }).then(({data})=>setWx(prev=>({...prev,[l.id]:data})));
        api.post("/roads/check", { load_id: l.id }).then(({data})=>setRd(prev=>({...prev,[l.id]:data})));
      }
    });
  },[]);

  return (
    <div>
      <Topbar title="Weather & Road Risk" subtitle={`${loads.length} active lanes`} />
      <div className="p-6 grid grid-cols-1 lg:grid-cols-2 gap-4">
        {loads.map(l => (
          <div key={l.id} className="terminal-card p-4" data-testid={`wxroad-${l.id}`}>
            <div className="flex items-center justify-between mb-2">
              <div className="font-mono text-xs text-sky-400">{l.id}</div>
              <div className="text-xs text-zinc-500">{l.pickup_city} → {l.delivery_city}</div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="border-l-2 border-sky-500/40 pl-2">
                <div className="kpi-label flex items-center gap-1"><CloudRain className="w-3 h-3" /> Weather</div>
                {wx[l.id] ? (
                  <div className="text-[11px] font-mono mt-1 space-y-0.5">
                    <div>Route <RiskBadge risk={wx[l.id].route.overall_risk} /></div>
                    <div>Rain <RiskBadge risk={wx[l.id].pickup.rain} /></div>
                    <div>Wind <RiskBadge risk={wx[l.id].pickup.wind} /></div>
                    <div className="text-zinc-500 pt-1">ETA +{wx[l.id].route.eta_impact_minutes}min</div>
                  </div>
                ) : <div className="text-xs text-zinc-500">Loading…</div>}
              </div>
              <div className="border-l-2 border-amber-500/40 pl-2">
                <div className="kpi-label flex items-center gap-1"><RouteIcon className="w-3 h-3" /> Roads</div>
                {rd[l.id] ? (
                  <div className="text-[11px] font-mono mt-1 space-y-0.5">
                    <div>Traffic: {rd[l.id].traffic_delay_min}min</div>
                    <div>Accident <RiskBadge risk={rd[l.id].accident_risk} /></div>
                    {rd[l.id].closure_alert && <div className="text-amber-400 text-[10px]">{rd[l.id].closure_alert}</div>}
                    {rd[l.id].reroute_suggestion && <div className="text-sky-400 text-[10px]">↳ {rd[l.id].reroute_suggestion}</div>}
                  </div>
                ) : <div className="text-xs text-zinc-500">Loading…</div>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
