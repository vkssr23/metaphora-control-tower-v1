/* eslint-disable react-hooks/exhaustive-deps -- intentional mount-only effects */
import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { Money, Num } from "../components/Badges";
import { useNavigate } from "react-router-dom";

export default function InTransit() {
  const [loads, setLoads] = useState([]);
  const [now, setNow] = useState(Date.now());
  const [samsara, setSamsara] = useState({});
  const nav = useNavigate();

  useEffect(()=>{
    api.get("/loads").then(async r=>{
      const inTransit = r.data.filter(l => ["Loaded","In Transit","Arrived Delivery"].includes(l.stage));
      setLoads(inTransit);
      const map = {};
      for (const l of inTransit) {
        if (l.truck_id) {
          try {
            const { data } = await api.post("/samsara/vehicle", { truck_id: l.truck_id });
            map[l.id] = data;
          } catch {
            map[l.id] = null;
          }
        }
      }
      setSamsara(map);
    });
    const t = setInterval(()=>setNow(Date.now()), 1000);
    return ()=>clearInterval(t);
  },[]);

  const format = (ms) => {
    const s = Math.floor(ms/1000); const h = Math.floor(s/3600); const m = Math.floor((s%3600)/60); const sec = s%60;
    return `${h}h ${m}m ${sec}s`;
  };

  return (
    <div>
      <Topbar title="In-Transit Control" subtitle={`${loads.length} active trips · live timers`} />
      <div className="p-6 space-y-3">
        {loads.map(l => {
          const started = new Date(l.updated_at).getTime();
          const s = samsara[l.id];
          return (
            <div key={l.id} className="terminal-card p-4 grid grid-cols-1 md:grid-cols-6 gap-3 items-center hover:border-sky-500/50 cursor-pointer" onClick={()=>nav(`/loads/${l.id}`)} data-testid={`transit-${l.id}`}>
              <div>
                <div className="font-mono text-xs text-sky-400 font-semibold">{l.id}</div>
                <div className="text-xs">{l.customer}</div>
              </div>
              <div className="text-xs font-mono">
                <div className="text-zinc-500">Lane</div>
                <div>{l.pickup_city} → {l.delivery_city}</div>
              </div>
              <div className="text-xs font-mono">
                <div className="text-zinc-500">Current Location</div>
                <div>{s?.location || l.pickup_city}</div>
              </div>
              <div className="text-xs font-mono">
                <div className="text-zinc-500">Speed / Engine</div>
                <div>{s ? `${s.speed_mph || 0} mph · ${s.engine || "?"}` : "Unavailable"}</div>
              </div>
              <div className="text-xs font-mono">
                <div className="text-zinc-500">Drive Time</div>
                <div className="text-emerald-400">{format(now-started)}</div>
              </div>
              <div className="text-xs font-mono">
                <div className="text-zinc-500">Idle · HOS</div>
                <div>{s ? `${s.idle_minutes || 0}min · ${s.hos_remaining_hours || "?"}h` : "Unavailable"}</div>
              </div>
            </div>
          );
        })}
        {loads.length===0 && <div className="text-zinc-500 text-sm">No active in-transit loads.</div>}
      </div>
    </div>
  );
}
