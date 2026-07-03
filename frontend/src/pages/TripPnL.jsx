import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { Money } from "../components/Badges";
import { useNavigate } from "react-router-dom";
import { AlertTriangle } from "lucide-react";

export default function TripPnL() {
  const [loads, setLoads] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [trucks, setTrucks] = useState([]);
  const nav = useNavigate();
  useEffect(()=>{
    api.get("/loads").then(r=>setLoads(r.data));
    api.get("/drivers").then(r=>setDrivers(r.data));
    api.get("/trucks").then(r=>setTrucks(r.data));
  },[]);

  const drvMap = Object.fromEntries(drivers.map(d=>[d.id,d]));
  const trkMap = Object.fromEntries(trucks.map(t=>[t.id,t]));

  const rows = loads.map(l => {
    const expenses = l.fuel_cost + l.tolls + l.lumper + l.driver_pay + l.factoring_fee + l.other_expenses;
    const gross = l.rate - (l.fuel_cost + l.tolls + l.lumper + l.driver_pay);
    const net = l.rate - expenses;
    const ppm = l.miles ? net / l.miles : 0;
    const margin = l.rate ? (net / l.rate) * 100 : 0;
    return { ...l, expenses, gross, net, ppm, margin };
  });

  return (
    <div>
      <Topbar title="Trip P&L" subtitle={`${loads.length} trips`} />
      <div className="p-6">
        <div className="terminal-card overflow-hidden">
          <div className="overflow-auto">
            <table className="dispatch-table">
              <thead><tr>
                <th>Load</th><th>Truck</th><th>Driver</th><th>Lane</th>
                <th className="text-right">Miles</th><th className="text-right">Rev</th><th className="text-right">RPM</th>
                <th className="text-right">Fuel</th><th className="text-right">Tolls</th><th className="text-right">Lump</th>
                <th className="text-right">Driver</th><th className="text-right">Factor</th><th className="text-right">Other</th>
                <th className="text-right">Gross</th><th className="text-right">Net</th><th className="text-right">PPM</th><th className="text-right">Margin</th><th>Alert</th>
              </tr></thead>
              <tbody>
                {rows.map(l=>{
                  const bad = l.net < 0 || l.rpm < 1.5;
                  return (
                    <tr key={l.id} className="cursor-pointer" onClick={()=>nav(`/loads/${l.id}`)} data-testid={`pnl-${l.id}`}>
                      <td className="text-sky-400">{l.id}</td>
                      <td>{trkMap[l.truck_id]?.truck_number || "-"}</td>
                      <td>{drvMap[l.driver_id]?.name?.split(" ")[0] || "-"}</td>
                      <td className="text-[11px]">{l.pickup_city}→{l.delivery_city}</td>
                      <td className="text-right">{l.miles}</td>
                      <td className="text-right"><Money v={l.rate} /></td>
                      <td className="text-right text-emerald-400">${l.rpm}</td>
                      <td className="text-right"><Money v={l.fuel_cost} /></td>
                      <td className="text-right"><Money v={l.tolls} /></td>
                      <td className="text-right"><Money v={l.lumper} /></td>
                      <td className="text-right"><Money v={l.driver_pay} /></td>
                      <td className="text-right"><Money v={l.factoring_fee} /></td>
                      <td className="text-right"><Money v={l.other_expenses} /></td>
                      <td className="text-right"><Money v={l.gross} /></td>
                      <td className={`text-right ${l.net>=0?"text-emerald-400":"text-red-400"}`}><Money v={l.net} /></td>
                      <td className={`text-right ${l.ppm>=0.5?"text-emerald-400":l.ppm>=0?"text-amber-400":"text-red-400"}`}>${l.ppm.toFixed(2)}</td>
                      <td className="text-right">{l.margin.toFixed(0)}%</td>
                      <td>{bad && <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />}</td>
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
