import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { StageBadge, RiskBadge, Money, Num } from "../components/Badges";
import { useNavigate } from "react-router-dom";
import { Plus, X } from "lucide-react";
import { toast, Toaster } from "sonner";

export default function Loads() {
  const [loads, setLoads] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [trucks, setTrucks] = useState([]);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ customer:"", broker:"", pickup_address:"", pickup_city:"", pickup_state:"", delivery_address:"", delivery_city:"", delivery_state:"", miles: "", rate: "" });
  const nav = useNavigate();

  const load = () => api.get("/loads").then(r=>setLoads(r.data.sort((a,b)=>b.created_at.localeCompare(a.created_at))));
  useEffect(() => { load(); api.get("/drivers").then(r=>setDrivers(r.data)); api.get("/trucks").then(r=>setTrucks(r.data)); }, []);

  const create = async () => {
    if (!form.customer || !form.pickup_address || !form.delivery_address) { toast.error("Customer, pickup and delivery required"); return; }
    // Auto-calc route
    const { data: rt } = await api.post("/routing/calc", { pickup: `${form.pickup_city}, ${form.pickup_state}`, delivery: `${form.delivery_city}, ${form.delivery_state}` });
    const payload = { ...form, miles: Number(form.miles) || rt.miles, rate: Number(form.rate) || 0, est_drive_hours: rt.drive_hours };
    await api.post("/loads", payload);
    toast.success("Load created");
    setCreating(false); setForm({ customer:"", broker:"", pickup_address:"", pickup_city:"", pickup_state:"", delivery_address:"", delivery_city:"", delivery_state:"", miles:"", rate:"" });
    load();
  };

  const truckMap = Object.fromEntries(trucks.map(t=>[t.id,t]));
  const driverMap = Object.fromEntries(drivers.map(d=>[d.id,d]));

  return (
    <div>
      <Toaster position="top-right" theme="dark" />
      <Topbar title="Loads" subtitle={`${loads.length} total`}
        actions={<button data-testid="loads-create-btn" onClick={()=>setCreating(true)} className="bg-sky-500 hover:bg-sky-600 text-white rounded px-3 py-1.5 text-sm flex items-center gap-1.5"><Plus className="w-3.5 h-3.5" /> New Load</button>}
      />
      <div className="p-6">
        <div className="terminal-card overflow-hidden">
          <div className="max-h-[calc(100vh-200px)] overflow-auto">
            <table className="dispatch-table">
              <thead>
                <tr>
                  <th>Load ID</th><th>Customer</th><th>Broker</th><th>Lane</th>
                  <th className="text-right">Miles</th><th className="text-right">Rate</th><th className="text-right">RPM</th>
                  <th>Driver</th><th>Truck</th><th>Stage</th><th>Risk</th><th>BOL/POD</th><th>Invoice</th>
                </tr>
              </thead>
              <tbody>
                {loads.map(l => (
                  <tr key={l.id} className="cursor-pointer" onClick={()=>nav(`/loads/${l.id}`)} data-testid={`load-row-${l.id}`}>
                    <td className="text-sky-400">{l.id}</td>
                    <td>{l.customer}</td>
                    <td className="text-zinc-500">{l.broker}</td>
                    <td>{l.pickup_city},{l.pickup_state} → {l.delivery_city},{l.delivery_state}</td>
                    <td className="text-right"><Num v={l.miles} /></td>
                    <td className="text-right"><Money v={l.rate} /></td>
                    <td className="text-right text-emerald-400">${l.rpm}</td>
                    <td>{driverMap[l.driver_id]?.name || "—"}</td>
                    <td>{truckMap[l.truck_id]?.truck_number || "—"}</td>
                    <td><StageBadge stage={l.stage} /></td>
                    <td><RiskBadge risk={l.risk} /></td>
                    <td className="text-[11px]">{l.bol_status}/{l.pod_status}</td>
                    <td className="text-[11px] text-zinc-400">{l.invoice_status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {creating && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={()=>setCreating(false)}>
          <div className="terminal-card p-6 max-w-2xl w-full" onClick={e=>e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-display font-bold text-lg">New Load</h3>
              <button onClick={()=>setCreating(false)}><X className="w-4 h-4" /></button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {[
                ["customer","Customer"],["broker","Broker / Platform"],
                ["pickup_address","Pickup Address"],["pickup_city","Pickup City"],["pickup_state","Pickup State"],
                ["delivery_address","Delivery Address"],["delivery_city","Delivery City"],["delivery_state","Delivery State"],
                ["miles","Miles (auto if blank)"],["rate","Rate ($)"]
              ].map(([k,l])=>(
                <div key={k}>
                  <div className="text-[10px] font-mono uppercase text-zinc-500 tracking-widest mb-1">{l}</div>
                  <input data-testid={`newload-${k}`} value={form[k]} onChange={e=>setForm({...form,[k]:e.target.value})} className="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm outline-none focus:border-sky-500" />
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={()=>setCreating(false)} className="px-3 py-1.5 text-sm text-zinc-400">Cancel</button>
              <button data-testid="newload-submit" onClick={create} className="bg-sky-500 hover:bg-sky-600 text-white rounded px-4 py-1.5 text-sm">Create Load</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
