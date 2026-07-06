/* eslint-disable react-hooks/exhaustive-deps -- intentional mount-only effects */
import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { Fuel } from "lucide-react";

export default function FuelPlanner() {
  const [loads, setLoads] = useState([]);
  const [plans, setPlans] = useState({});

  useEffect(()=>{
    api.get("/loads").then(async r=>{
      const active = r.data.filter(l => ["Loaded","In Transit"].includes(l.stage));
      setLoads(active);
      for (const l of active) {
        api.post("/fuel/plan", { load_id: l.id }).then(({data})=>setPlans(p=>({...p,[l.id]:data})));
      }
    });
  },[]);

  return (
    <div>
      <Topbar title="Fuel Stop Planner" subtitle={`${loads.length} in-transit loads`} />
      <div className="p-6 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {loads.map(l => {
          const p = plans[l.id];
          return (
            <div key={l.id} className="terminal-card p-4" data-testid={`fuel-${l.id}`}>
              <div className="flex items-center gap-2 mb-2">
                <Fuel className="w-4 h-4 text-amber-400" />
                <div className="font-mono text-xs text-sky-400">{l.id}</div>
                <div className="text-xs text-zinc-500">{l.pickup_city} → {l.delivery_city}</div>
              </div>
              {p ? (
                <div className="text-[11px] font-mono space-y-1">
                  <div>Fuel level: <span className="text-amber-400">{p.fuel_level_pct}%</span> · {p.miles_remaining} mi remaining</div>
                  <div className="pt-2 border-t border-zinc-800">
                    <div className="text-zinc-500">Recommended Stop</div>
                    <div className="text-zinc-100 text-sm">{p.recommended_stop.name}</div>
                    <div className="text-zinc-500">{p.recommended_stop.address}</div>
                    <div>{p.recommended_stop.distance_miles} mi · ${p.recommended_stop.price_per_gallon}/gal · {p.estimated_gallons} gal est</div>
                    <div>Parking: {p.recommended_stop.parking_available?"✓ available":"✗ full"}</div>
                  </div>
                </div>
              ) : <div className="text-xs text-zinc-500">Loading…</div>}
            </div>
          );
        })}
        {loads.length===0 && <div className="text-zinc-500 text-sm col-span-3">No in-transit loads.</div>}
      </div>
    </div>
  );
}
