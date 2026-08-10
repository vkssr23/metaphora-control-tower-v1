import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { StageBadge, RiskBadge, Money, Num } from "../components/Badges";
import LoadPassport from "../components/LoadPassport";
import RateConfirmationIntelligence from "../components/RateConfirmationIntelligence";
import PartyVerification from "../components/PartyVerification";
import ExecutionEligibility from "../components/ExecutionEligibility";
import SecurePickupRelease from "../components/SecurePickupRelease";
import { toast, Toaster } from "sonner";
import {
  ChevronLeft, MapPin, Truck as TruckIcon, User, DollarSign, Calendar, AlertTriangle,
  CheckCircle2, Circle, Clock, CloudRain, Route as RouteIcon, Fuel, Satellite,
  FileText, Receipt, Send, ExternalLink, Copy, Play
} from "lucide-react";

const STAGES = [
  "Booked","Assigned","Dispatched","Pickup Started","Arrived Pickup","Loaded",
  "In Transit","Arrived Delivery","Delivered","Docs Pending","Invoice Pending",
  "Payment Pending","Closed"
];

const QUICK_ACTIONS = [
  { s:"Assigned", label:"Assign Driver & Truck" },
  { s:"Dispatched", label:"Dispatch Driver" },
  { s:"Pickup Started", label:"Start Pickup" },
  { s:"Arrived Pickup", label:"Mark Arrived Pickup" },
  { s:"Loaded", label:"Mark Loaded / BOL Received" },
  { s:"In Transit", label:"Start Transit" },
  { s:"Arrived Delivery", label:"Mark Arrived Delivery" },
  { s:"Delivered", label:"Mark Delivered" },
  { s:"Docs Pending", label:"POD/BOL Uploaded" },
  { s:"Invoice Pending", label:"Create Invoice" },
  { s:"Payment Pending", label:"Submit to Factoring" },
  { s:"Closed", label:"Mark Payment Received & Close" },
  { s:"Exception", label:"Mark Exception" },
];

export default function LoadExecution() {
  const { id } = useParams();
  const nav = useNavigate();
  const [load, setLoad] = useState(null);
  const [drivers, setDrivers] = useState([]);
  const [trucks, setTrucks] = useState([]);
  const [activity, setActivity] = useState([]);
  const [weather, setWeather] = useState(null);
  const [roads, setRoads] = useState(null);
  const [fuel, setFuel] = useState(null);
  const [samsara, setSamsara] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [alertMsg, setAlertMsg] = useState("");
  const samsaraRequest = useRef(0);

  const refresh = () => Promise.all([
    api.get(`/loads/${id}`).then(r=>setLoad(r.data)),
    api.get(`/activity`, { params:{ load_id:id }}).then(r=>setActivity(r.data)),
    api.get(`/documents`, { params:{ load_id:id }}).then(r=>setDocuments(r.data)),
  ]);

  useEffect(() => {
    refresh();
    api.get("/drivers").then(r=>setDrivers(r.data));
    api.get("/trucks").then(r=>setTrucks(r.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const driver = load ? drivers.find(d => d.id === load.driver_id) : null;
  const truck  = load ? trucks.find(t => t.id === load.truck_id) : null;
  const stageIndex = load ? STAGES.indexOf(load.stage) : -1;
  const truckId = truck?.id;

  const fetchSamsara = useCallback(async () => {
    const requestId = ++samsaraRequest.current;
    if (!truckId) {
      setSamsara(null);
      return;
    }
    try {
      const { data } = await api.post("/samsara/vehicle", { truck_id: truckId });
      if (requestId === samsaraRequest.current) setSamsara(data);
    } catch {
      if (requestId === samsaraRequest.current) setSamsara(null);
    }
  }, [truckId]);

  useEffect(() => {
    fetchSamsara();
    return () => { samsaraRequest.current += 1; };
  }, [fetchSamsara]);

  if (!load) return <div className="p-6 text-zinc-500">Loading…</div>;

  const changeStage = async (stage) => {
    try {
      await api.post(`/loads/${id}/stage`, { stage, notes: "" });
      toast.success(`Stage → ${stage}`);
      refresh();
    } catch (error) {
      toast.error(error?.response?.status === 409 ? error.response.data.detail : "Stage update failed");
    }
  };

  const assignDriverTruck = async (driver_id, truck_id) => {
    await api.put(`/loads/${id}`, { driver_id, truck_id });
    if (load.stage === "Booked") {
      try {
        await api.post(`/loads/${id}/stage`, { stage: "Assigned", notes: "Assigned driver and truck" });
      } catch (error) {
        toast.error(error?.response?.status === 409 ? `Assignments saved; ${error.response.data.detail}` : "Assignments saved; stage update failed");
        refresh();
        return;
      }
    }
    toast.success("Assigned");
    refresh();
  };

  const checkWeather = async () => {
    const { data } = await api.post("/weather/check", { pickup: load.pickup_city, delivery: load.delivery_city });
    setWeather(data);
    toast.success("Weather refreshed");
  };
  const checkRoads = async () => {
    const { data } = await api.post("/roads/check", { load_id: id });
    setRoads(data);
    toast.success("Road conditions refreshed");
  };
  const planFuel = async () => {
    const { data } = await api.post("/fuel/plan", { load_id: id });
    setFuel(data);
    toast.success("Fuel stop planned");
  };
  const generateAlert = async (type, msg) => {
    const { data } = await api.post("/alerts/generate", { load_id: id, alert_type: type, message: msg || `Auto-generated ${type} alert.` });
    setAlertMsg(data.message);
    toast.success("Driver alert generated");
    refresh();
  };

  const uploadDoc = async (doc_type) => {
    const filename = prompt(`Filename for ${doc_type}:`, `${doc_type}_${id}.pdf`);
    if (!filename) return;
    await api.post("/documents", { load_id: id, doc_type, filename, url: `mock://${filename}` });
    toast.success("Document logged");
    refresh();
  };

  const gmapsLink = `https://www.google.com/maps/dir/${encodeURIComponent(load.pickup_address)}/${encodeURIComponent(load.delivery_address)}`;
  const estProfit = load.rate - (load.fuel_cost + load.tolls + load.lumper + load.driver_pay + load.factoring_fee + load.other_expenses);

  return (
    <div>
      <Toaster position="top-right" theme="dark" />
      <Topbar title={`Load ${load.id}`} subtitle={load.customer} actions={
        <button onClick={()=>nav(-1)} className="text-xs text-zinc-400 hover:text-white flex items-center gap-1" data-testid="back-btn">
          <ChevronLeft className="w-4 h-4" /> Back
        </button>
      } />

      <div className="p-6 space-y-6">
        {/* TOP */}
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
          <div className="terminal-card p-4 lg:col-span-2">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <StageBadge stage={load.stage} />
                <RiskBadge risk={load.risk} />
              </div>
              <div className="text-xs text-zinc-500 font-mono">{load.broker} · {load.rate_con_number}</div>
            </div>
            <div className="flex items-center gap-3 mb-3">
              <MapPin className="w-4 h-4 text-sky-400" />
              <div className="font-mono text-sm">
                <span className="text-zinc-100">{load.pickup_city}, {load.pickup_state}</span>
                <span className="text-zinc-600 mx-2">→</span>
                <span className="text-zinc-100">{load.delivery_city}, {load.delivery_state}</span>
              </div>
              <a href={gmapsLink} target="_blank" rel="noreferrer" className="ml-auto text-xs text-sky-400 hover:underline flex items-center gap-1" data-testid="gmaps-link"><ExternalLink className="w-3 h-3" /> Google Maps</a>
            </div>
            <div className="grid grid-cols-3 gap-3 text-sm">
              <div><div className="kpi-label">Pickup Appt</div><div className="font-mono text-xs mt-0.5">{load.pickup_appt?.slice(0,16).replace("T"," ")}</div></div>
              <div><div className="kpi-label">Delivery Appt</div><div className="font-mono text-xs mt-0.5">{load.delivery_appt?.slice(0,16).replace("T"," ")}</div></div>
              <div><div className="kpi-label">ETA</div><div className="font-mono text-xs mt-0.5">{load.eta?.slice(0,16).replace("T"," ")}</div></div>
            </div>
          </div>

          <div className="terminal-card p-4">
            <div className="kpi-label mb-1">Financials</div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div><div className="text-[10px] text-zinc-500 font-mono">RATE</div><div className="kpi-value text-lg"><Money v={load.rate} /></div></div>
              <div><div className="text-[10px] text-zinc-500 font-mono">MILES</div><div className="kpi-value text-lg"><Num v={load.miles} /></div></div>
              <div><div className="text-[10px] text-zinc-500 font-mono">RPM</div><div className="kpi-value text-lg text-emerald-400">${load.rpm}</div></div>
              <div><div className="text-[10px] text-zinc-500 font-mono">EST PROFIT</div><div className={`kpi-value text-lg ${estProfit>=0?"text-emerald-400":"text-red-400"}`}><Money v={estProfit} /></div></div>
            </div>
          </div>

          <div className="terminal-card p-4">
            <div className="kpi-label mb-2">Assignment</div>
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm">
                <User className="w-3.5 h-3.5 text-zinc-500" />
                <select data-testid="assign-driver" value={load.driver_id||""} onChange={e=>assignDriverTruck(e.target.value, load.truck_id)} className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs font-mono flex-1">
                  <option value="">— Driver —</option>
                  {drivers.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <TruckIcon className="w-3.5 h-3.5 text-zinc-500" />
                <select data-testid="assign-truck" value={load.truck_id||""} onChange={e=>assignDriverTruck(load.driver_id, e.target.value)} className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs font-mono flex-1">
                  <option value="">— Truck —</option>
                  {trucks.map(t=><option key={t.id} value={t.id}>{t.truck_number}</option>)}
                </select>
              </div>
              <div className="pt-2 text-[11px] font-mono text-zinc-500">
                {driver ? `${driver.name} · ${driver.phone}` : "Unassigned driver"}<br/>
                {truck ? `${truck.truck_number} · ${truck.current_location}` : "Unassigned truck"}
              </div>
            </div>
          </div>
        </div>

        <LoadPassport loadId={id} />
        <RateConfirmationIntelligence loadId={id} documents={documents} />
        <PartyVerification loadId={id} />
        <ExecutionEligibility loadId={id} />
        <SecurePickupRelease loadId={id} />

        {/* TIMELINE */}
        <div className="terminal-card p-4">
          <div className="kpi-label mb-3">Execution Timeline</div>
          <div className="flex items-center gap-1 overflow-x-auto pb-2">
            {STAGES.map((s, i) => {
              const done = i < stageIndex;
              const active = i === stageIndex;
              return (
                <React.Fragment key={s}>
                  <div className="flex flex-col items-center min-w-[70px]" data-testid={`timeline-${s}`}>
                    {done ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : active ? <Circle className="w-4 h-4 text-sky-400 fill-sky-400/20" /> : <Circle className="w-4 h-4 text-zinc-700" />}
                    <div className={`text-[9.5px] font-mono uppercase tracking-wider mt-1 text-center leading-tight ${active?"text-sky-400":done?"text-emerald-500":"text-zinc-600"}`}>{s}</div>
                  </div>
                  {i < STAGES.length - 1 && <div className={`h-0.5 flex-1 min-w-[10px] ${done?"bg-emerald-500":"bg-zinc-800"}`}></div>}
                </React.Fragment>
              );
            })}
          </div>
        </div>

        {/* QUICK ACTIONS */}
        <div className="terminal-card p-4">
          <div className="kpi-label mb-2">Quick Actions</div>
          <div className="flex flex-wrap gap-1.5">
            {QUICK_ACTIONS.map(a => (
              <button
                key={a.s}
                data-testid={`action-${a.s.toLowerCase().replace(/ /g,'-')}`}
                onClick={()=>changeStage(a.s)}
                className="text-xs bg-zinc-900 hover:bg-sky-500/20 hover:border-sky-500 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 transition-colors flex items-center gap-1"
              >
                <Play className="w-3 h-3" /> {a.label}
              </button>
            ))}
          </div>
        </div>

        {/* RISK PANELS */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <RiskPanel title="Weather Risk" icon={CloudRain} data={weather} onCheck={checkWeather} testKey="weather"
            render={(w)=>(
              <div className="text-xs font-mono space-y-1">
                <div>Pickup: {w.pickup.temp_f}°F · rain <RiskBadge risk={w.pickup.rain} /></div>
                <div>Delivery: {w.delivery.temp_f}°F · storm {w.delivery.storm_alert?"YES":"no"}</div>
                <div className="pt-1">Route: <RiskBadge risk={w.route.overall_risk} /></div>
                <div className="text-zinc-500 pt-1">{w.route.advisory}</div>
                <button onClick={()=>generateAlert("weather", w.route.advisory)} className="mt-2 text-[11px] text-sky-400 hover:underline" data-testid="alert-weather-btn">Generate Driver Alert →</button>
              </div>
            )} />
          <RiskPanel title="Road Conditions" icon={RouteIcon} data={roads} onCheck={checkRoads} testKey="roads"
            render={(r)=>(
              <div className="text-xs font-mono space-y-1">
                <div>Traffic: {r.traffic_delay_min} min delay</div>
                <div>Accident: <RiskBadge risk={r.accident_risk} /></div>
                {r.closure_alert && <div className="text-amber-400">{r.closure_alert}</div>}
                {r.reroute_suggestion && <div className="text-sky-400">Reroute: {r.reroute_suggestion}</div>}
                <button onClick={()=>generateAlert("road", r.closure_alert || "Traffic advisory")} className="mt-2 text-[11px] text-sky-400 hover:underline" data-testid="alert-road-btn">Generate Driver Alert →</button>
              </div>
            )} />
          <RiskPanel title="Fuel Stop" icon={Fuel} data={fuel} onCheck={planFuel} testKey="fuel"
            render={(f)=>(
              <div className="text-xs font-mono space-y-1">
                <div>Fuel: {f.fuel_level_pct}% · {f.miles_remaining} mi remaining</div>
                <div className="text-zinc-100">{f.recommended_stop.name}</div>
                <div className="text-zinc-500">{f.recommended_stop.address}</div>
                <div>{f.recommended_stop.distance_miles} mi away · ${f.recommended_stop.price_per_gallon}/gal</div>
                <button onClick={()=>generateAlert("fuel", `Fuel at ${f.recommended_stop.name} — ${f.recommended_stop.address}`)} className="mt-2 text-[11px] text-sky-400 hover:underline" data-testid="alert-fuel-btn">Send Fuel Instruction →</button>
              </div>
            )} />
        </div>

        {/* SAMSARA + ROUTE MAP + DOCS */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          <div className="terminal-card p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="kpi-label flex items-center gap-1.5"><Satellite className="w-3.5 h-3.5" /> Samsara / Telematics</div>
              <button onClick={fetchSamsara} disabled={!truck} className="text-[10px] font-mono text-sky-400 hover:underline disabled:text-zinc-600" data-testid="samsara-refresh">Refresh</button>
            </div>
            {samsara ? (
              <div className="text-xs font-mono space-y-1">
                <div>Location: <span className="text-zinc-100">{samsara.location}</span></div>
                <div>Engine: {samsara.engine} · Speed {samsara.speed_mph} mph</div>
                <div>Odometer: {samsara.odometer.toLocaleString()} mi · Fuel {samsara.fuel_pct}%</div>
                <div>Duty: {samsara.duty_status} · HOS: {samsara.hos_remaining_hours}h left</div>
                <div>Idle: {samsara.idle_minutes} min · Harsh events: {samsara.harsh_events}</div>
                <div className="text-zinc-500 text-[10px] pt-1">Last sync: {samsara.last_sync?.slice(11,19)}</div>
              </div>
            ) : <div className="text-xs text-zinc-500">{truck ? "Telematics unavailable" : "Assign a truck to see live telematics"}</div>}
          </div>

          <div className="terminal-card p-4 lg:col-span-2">
            <div className="kpi-label mb-2">Route Map</div>
            <div className="relative h-56 rounded overflow-hidden border border-zinc-800 bg-cover bg-center" style={{backgroundImage:"url(https://images.unsplash.com/photo-1516738901171-8eb4fc13bd20?w=1200&q=60)"}}>
              <div className="absolute inset-0 bg-[#09090B]/70"></div>
              <div className="absolute inset-0 p-4 flex items-center justify-between">
                <div className="text-center">
                  <MapPin className="w-6 h-6 text-emerald-400 mx-auto" />
                  <div className="text-xs font-mono mt-1 text-zinc-100">{load.pickup_city}</div>
                  <div className="text-[10px] text-zinc-500 font-mono">Pickup</div>
                </div>
                <div className="flex-1 mx-6 border-t border-dashed border-sky-500/60 relative">
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 text-[11px] font-mono text-sky-400 bg-[#0C0C0F] px-2">
                    {load.miles} mi · {load.est_drive_hours}h
                  </div>
                </div>
                <div className="text-center">
                  <MapPin className="w-6 h-6 text-red-400 mx-auto" />
                  <div className="text-xs font-mono mt-1 text-zinc-100">{load.delivery_city}</div>
                  <div className="text-[10px] text-zinc-500 font-mono">Delivery</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* DOCUMENTS + INVOICE + ACTIVITY */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          <div className="terminal-card p-4">
            <div className="kpi-label mb-2 flex items-center gap-1.5"><FileText className="w-3.5 h-3.5" /> Documents Checklist</div>
            <div className="space-y-1.5">
              {[
                ["rate_con","Rate Confirmation"],
                ["bol","BOL Received"],
                ["lumper","Lumper Receipt"],
                ["pod","POD Received"],
                ["scale","Scale Ticket"],
                ["invoice","Invoice"],
              ].map(([k,l])=>{
                const has = documents.find(d=>d.doc_type===k);
                return (
                  <div key={k} className="flex items-center justify-between text-xs font-mono">
                    <div className="flex items-center gap-2">
                      {has ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> : <Circle className="w-3.5 h-3.5 text-zinc-600" />}
                      <span className={has?"text-zinc-100":"text-zinc-500"}>{l}</span>
                    </div>
                    <button data-testid={`doc-upload-${k}`} onClick={()=>uploadDoc(k)} className="text-[10px] text-sky-400 hover:underline">{has?"Re-upload":"Upload"}</button>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="terminal-card p-4">
            <div className="kpi-label mb-2 flex items-center gap-1.5"><Receipt className="w-3.5 h-3.5" /> Invoice & Payment</div>
            <div className="text-xs font-mono space-y-1.5">
              <div className="flex justify-between"><span className="text-zinc-500">BOL Status</span><span>{load.bol_status}</span></div>
              <div className="flex justify-between"><span className="text-zinc-500">POD Status</span><span>{load.pod_status}</span></div>
              <div className="flex justify-between"><span className="text-zinc-500">Invoice Status</span><span className="text-amber-400">{load.invoice_status}</span></div>
              <div className="flex justify-between"><span className="text-zinc-500">Payment</span><span>{load.payment_status}</span></div>
              <div className="flex justify-between pt-2 border-t border-zinc-800"><span className="text-zinc-500">Amount</span><Money v={load.rate} className="text-emerald-400" /></div>
            </div>
          </div>

          <div className="terminal-card p-4">
            <div className="kpi-label mb-2 flex items-center gap-1.5"><Clock className="w-3.5 h-3.5" /> Activity Log</div>
            <div className="space-y-2 max-h-56 overflow-y-auto text-xs font-mono">
              {activity.length===0 && <div className="text-zinc-500">No activity yet</div>}
              {activity.map(a=>(
                <div key={a.id} className="border-l-2 border-zinc-800 pl-2 py-0.5">
                  <div className="text-zinc-100">{a.action} {a.new_status && <span className="text-sky-400">→ {a.new_status}</span>}</div>
                  <div className="text-[10px] text-zinc-500">{a.updated_by} · {a.timestamp?.slice(0,16).replace("T"," ")}</div>
                  {a.notes && <div className="text-zinc-400 text-[11px]">{a.notes}</div>}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Driver Alert Preview */}
        {alertMsg && (
          <div className="terminal-card p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="kpi-label flex items-center gap-1.5"><Send className="w-3.5 h-3.5" /> Driver Alert Draft</div>
              <div className="flex gap-1.5">
                <button onClick={()=>{navigator.clipboard.writeText(alertMsg); toast.success("Copied");}} data-testid="alert-copy-btn" className="text-[10px] font-mono bg-zinc-800 px-2 py-1 rounded hover:bg-zinc-700 flex items-center gap-1"><Copy className="w-3 h-3" /> Copy</button>
                <button data-testid="alert-whatsapp" className="text-[10px] font-mono bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 px-2 py-1 rounded">WhatsApp</button>
                <button data-testid="alert-telegram" className="text-[10px] font-mono bg-sky-500/20 text-sky-400 border border-sky-500/40 px-2 py-1 rounded">Telegram</button>
                <button data-testid="alert-sms" className="text-[10px] font-mono bg-zinc-800 border border-zinc-700 px-2 py-1 rounded">SMS</button>
              </div>
            </div>
            <pre className="text-[11px] font-mono text-zinc-300 whitespace-pre-wrap bg-zinc-950/50 border border-zinc-800 rounded p-3">{alertMsg}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

function RiskPanel({ title, icon: Icon, data, onCheck, render, testKey }) {
  return (
    <div className="terminal-card p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="kpi-label flex items-center gap-1.5"><Icon className="w-3.5 h-3.5" /> {title}</div>
        <button onClick={onCheck} data-testid={`check-${testKey}`} className="text-[10px] font-mono text-sky-400 hover:underline">Check</button>
      </div>
      {data ? render(data) : <div className="text-xs text-zinc-500">Click "Check" to fetch latest</div>}
    </div>
  );
}
