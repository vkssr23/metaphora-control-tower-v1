/* eslint-disable react-hooks/exhaustive-deps -- intentional mount-only effects */
import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { Satellite } from "lucide-react";

export default function Telematics() {
  const [trucks, setTrucks] = useState([]);
  const [data, setData] = useState({});

  useEffect(()=>{
    api.get("/trucks").then(async r=>{
      setTrucks(r.data);
      for (const t of r.data) {
        api.post("/samsara/vehicle", { vehicle_id: t.samsara_id }).then(({data:d})=>setData(prev=>({...prev,[t.id]:d})));
      }
    });
  },[]);

  return (
    <div>
      <Topbar title="Samsara / Telematics" subtitle={`${trucks.length} vehicles · mock feed`} />
      <div className="p-6">
        <div className="terminal-card overflow-hidden">
          <div className="overflow-auto">
            <table className="dispatch-table">
              <thead><tr>
                <th>Truck</th><th>Vehicle ID</th><th>Location</th><th>Engine</th>
                <th className="text-right">Speed</th><th className="text-right">Odometer</th>
                <th className="text-right">Fuel</th><th>Duty</th><th className="text-right">HOS Rem</th>
                <th className="text-right">Idle</th><th className="text-right">Harsh</th><th>Sync</th>
              </tr></thead>
              <tbody>
                {trucks.map(t=>{
                  const d = data[t.id];
                  return (
                    <tr key={t.id} data-testid={`telematics-${t.id}`}>
                      <td className="text-sky-400">{t.truck_number}</td>
                      <td>{t.samsara_id}</td>
                      <td>{d?.location || "…"}</td>
                      <td className={d?.engine==="ON"?"text-emerald-400":"text-zinc-500"}>{d?.engine || "-"}</td>
                      <td className="text-right">{d?.speed_mph||0}</td>
                      <td className="text-right">{d?.odometer?.toLocaleString() || "-"}</td>
                      <td className="text-right">{d?.fuel_pct||0}%</td>
                      <td>{d?.duty_status || "-"}</td>
                      <td className="text-right">{d?.hos_remaining_hours || "-"}h</td>
                      <td className="text-right">{d?.idle_minutes||0}m</td>
                      <td className={`text-right ${d?.harsh_events>0?"text-amber-400":""}`}>{d?.harsh_events||0}</td>
                      <td className="text-[10px] text-zinc-500">{d?.last_sync?.slice(11,19)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
