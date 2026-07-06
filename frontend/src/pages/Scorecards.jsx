/* eslint-disable react-hooks/exhaustive-deps -- intentional mount-only effects */
import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { Money, Num } from "../components/Badges";

export function DriverScorecard() {
  const [drivers, setDrivers] = useState([]);
  useEffect(()=>{ api.get("/drivers").then(r=>setDrivers(r.data.sort((a,b)=>b.score-a.score))); },[]);
  return (
    <div>
      <Topbar title="Driver Scorecard" subtitle={`${drivers.length} drivers ranked`} />
      <div className="p-6">
        <div className="terminal-card overflow-hidden">
          <table className="dispatch-table">
            <thead><tr>
              <th>Rank</th><th>Driver</th><th className="text-right">Score</th><th className="text-right">OT Pickup</th><th className="text-right">OT Delivery</th>
              <th className="text-right">Missed Upd</th><th className="text-right">Late Delivery</th><th className="text-right">Safety Issues</th><th className="text-right">Wk Miles</th><th className="text-right">Wk Rev</th><th>Recommendation</th>
            </tr></thead>
            <tbody>
              {drivers.map((d,i)=>{
                const rec = d.score>=90?"⭐ Give bonus":d.score>=75?"Maintain":"⚠ Coach & review";
                return (
                  <tr key={d.id} data-testid={`driver-score-${d.id}`}>
                    <td className="text-sky-400">#{i+1}</td>
                    <td>{d.name}</td>
                    <td className={`text-right font-bold ${d.score>=85?"text-emerald-400":d.score>=70?"text-amber-400":"text-red-400"}`}>{d.score}</td>
                    <td className="text-right">{d.on_time_pickup_pct}%</td>
                    <td className="text-right">{d.on_time_delivery_pct}%</td>
                    <td className="text-right">{d.missed_updates}</td>
                    <td className="text-right">{d.late_deliveries}</td>
                    <td className="text-right">{d.safety_issues}</td>
                    <td className="text-right"><Num v={d.weekly_miles} /></td>
                    <td className="text-right"><Money v={d.weekly_revenue} /></td>
                    <td className="text-[11px]">{rec}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export function TruckScorecard() {
  const [trucks, setTrucks] = useState([]);
  useEffect(()=>{ api.get("/trucks").then(r=>setTrucks(r.data.sort((a,b)=>b.profit_per_mile-a.profit_per_mile))); },[]);
  return (
    <div>
      <Topbar title="Truck Scorecard" subtitle={`${trucks.length} trucks ranked by PPM`} />
      <div className="p-6">
        <div className="terminal-card overflow-hidden">
          <table className="dispatch-table">
            <thead><tr>
              <th>Rank</th><th>Truck</th><th>Make/Model</th><th className="text-right">Util%</th><th className="text-right">Wk Rev</th>
              <th className="text-right">Wk Miles</th><th className="text-right">Fuel</th><th className="text-right">Maint</th><th className="text-right">Idle</th>
              <th className="text-right">PPM</th><th>Verdict</th>
            </tr></thead>
            <tbody>
              {trucks.map((t,i)=>{
                const verdict = t.profit_per_mile>0.6?"🏆 Top performer":t.profit_per_mile>0.4?"Steady":"⚠ Underperforming";
                return (
                  <tr key={t.id} data-testid={`truck-score-${t.id}`}>
                    <td className="text-sky-400">#{i+1}</td>
                    <td>{t.truck_number}</td>
                    <td>{t.make} {t.model}</td>
                    <td className="text-right">{t.utilization}%</td>
                    <td className="text-right"><Money v={t.weekly_revenue} /></td>
                    <td className="text-right"><Num v={t.weekly_miles} /></td>
                    <td className="text-right"><Money v={t.fuel_cost} /></td>
                    <td className="text-right"><Money v={t.maintenance_cost} /></td>
                    <td className="text-right">{t.idle_hours}h</td>
                    <td className={`text-right font-bold ${t.profit_per_mile>=0.5?"text-emerald-400":"text-amber-400"}`}>${t.profit_per_mile}</td>
                    <td className="text-[11px]">{verdict}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
