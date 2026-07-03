import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { Money, Num } from "../components/Badges";
import { toast, Toaster } from "sonner";

const STATUSES = ["Available","Assigned","In Transit","At Pickup","At Delivery","Idle","Maintenance","Out of Service"];

export default function Trucks() {
  const [trucks, setTrucks] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const refresh = () => api.get("/trucks").then(r=>setTrucks(r.data));
  useEffect(()=>{ refresh(); api.get("/drivers").then(r=>setDrivers(r.data)); },[]);

  const setStatus = async (id, status) => { await api.put(`/trucks/${id}`, {status}); toast.success("Updated"); refresh(); };

  return (
    <div>
      <Toaster position="top-right" theme="dark" />
      <Topbar title="Trucks" subtitle={`${trucks.length} vehicles`} />
      <div className="p-6">
        <div className="terminal-card overflow-hidden">
          <div className="overflow-auto">
            <table className="dispatch-table">
              <thead><tr>
                <th>Truck #</th><th>Make/Model</th><th>VIN</th><th>Plate</th><th>Location</th><th>Driver</th>
                <th>Samsara</th><th>Status</th><th className="text-right">Wk Rev</th><th className="text-right">Wk Miles</th>
                <th className="text-right">Fuel</th><th className="text-right">Util%</th><th className="text-right">PPM</th>
              </tr></thead>
              <tbody>
                {trucks.map(t=>{
                  const drv = drivers.find(d=>d.assigned_truck_id===t.id);
                  return (
                    <tr key={t.id} data-testid={`truck-row-${t.id}`}>
                      <td className="text-sky-400">{t.truck_number}</td>
                      <td>{t.make} {t.model} {t.year}</td>
                      <td className="text-zinc-500">{t.vin?.slice(0,10)}…</td>
                      <td>{t.plate}</td>
                      <td>{t.current_location}</td>
                      <td>{drv?.name || "—"}</td>
                      <td className="text-zinc-500">{t.samsara_id}</td>
                      <td>
                        <select value={t.status} onChange={e=>setStatus(t.id, e.target.value)} data-testid={`truck-status-${t.id}`} className="bg-zinc-900 border border-zinc-800 rounded px-1.5 py-0.5 text-[11px] font-mono">
                          {STATUSES.map(s=><option key={s}>{s}</option>)}
                        </select>
                      </td>
                      <td className="text-right"><Money v={t.weekly_revenue} /></td>
                      <td className="text-right"><Num v={t.weekly_miles} /></td>
                      <td className="text-right"><Money v={t.fuel_cost} /></td>
                      <td className="text-right">{t.utilization}%</td>
                      <td className="text-right text-emerald-400">${t.profit_per_mile}</td>
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
