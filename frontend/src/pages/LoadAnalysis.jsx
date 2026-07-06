import React, { useState } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { toast, Toaster } from "sonner";
import { LineChart as LineIcon, TrendingUp, TrendingDown, MinusCircle, CheckCircle2, AlertTriangle } from "lucide-react";
import { Money, Num } from "../components/Badges";

const DEFAULT_FORM = {
  offered_rate: 2400, loaded_miles: 900, deadhead_miles: 80,
  fuel_price: "", mpg: "", driver_type: "Solo", driver_pay_cpm: "",
  tolls: "", pickup_city: "Dallas, TX", delivery_city: "Atlanta, GA",
  broker: "", commodity: "", weight: 0,
  pickup_datetime: "", delivery_datetime: "",
};

export default function LoadAnalysis() {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const update = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const analyze = async () => {
    if (!form.offered_rate || !form.loaded_miles) { toast.error("Rate and loaded miles required"); return; }
    setBusy(true);
    try {
      const payload = { ...form,
        offered_rate: Number(form.offered_rate),
        loaded_miles: Number(form.loaded_miles),
        deadhead_miles: Number(form.deadhead_miles || 0),
        weight: Number(form.weight || 0),
      };
      // Only include numeric optionals if user set them
      ["fuel_price","mpg","driver_pay_cpm","tolls"].forEach(k=>{
        if (payload[k] === "" || payload[k] === null) delete payload[k];
        else payload[k] = Number(payload[k]);
      });
      const { data } = await api.post("/loads/analyze", payload);
      setResult(data);
    } catch (e) { toast.error(e?.response?.data?.detail || "Analysis failed"); }
    finally { setBusy(false); }
  };

  const bookLoad = async () => {
    // Convert analysis into a real load in Booked stage
    const p = form.pickup_city.split(",").map(s=>s.trim());
    const d = form.delivery_city.split(",").map(s=>s.trim());
    await api.post("/loads", {
      customer: form.broker || "New Customer",
      broker: form.broker,
      pickup_address: form.pickup_city, pickup_city: p[0]||"", pickup_state: p[1]||"",
      delivery_address: form.delivery_city, delivery_city: d[0]||"", delivery_state: d[1]||"",
      pickup_appt: form.pickup_datetime, delivery_appt: form.delivery_datetime,
      miles: result.total_miles, rate: Number(form.offered_rate),
      fuel_cost: result.fuel_cost, tolls: result.tolls, driver_pay: result.driver_pay,
      factoring_fee: result.factoring, risk: result.risk === "Green" ? "Low" : result.risk === "Yellow" ? "Medium" : "High",
    });
    toast.success("Load booked and added to Dispatch Board");
    setResult(null); setForm(DEFAULT_FORM);
  };

  const decisionIcon = { Book: CheckCircle2, Negotiate: MinusCircle, Reject: AlertTriangle };

  return (
    <div>
      <Toaster position="top-right" />
      <Topbar title="Load Market Analysis" subtitle="AI Decision Engine · Book / Negotiate / Reject" />
      <div className="p-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* INPUT */}
        <div className="terminal-card p-5">
          <div className="kpi-label mb-3 flex items-center gap-1.5"><LineIcon className="w-3.5 h-3.5" /> Load Details</div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Broker / Customer"><input data-testid="ma-broker" value={form.broker} onChange={e=>update("broker", e.target.value)} className="input" /></Field>
            <Field label="Commodity"><input data-testid="ma-commodity" value={form.commodity} onChange={e=>update("commodity", e.target.value)} className="input" /></Field>
            <Field label="Pickup (City, State)"><input data-testid="ma-pickup" value={form.pickup_city} onChange={e=>update("pickup_city", e.target.value)} className="input" /></Field>
            <Field label="Delivery (City, State)"><input data-testid="ma-delivery" value={form.delivery_city} onChange={e=>update("delivery_city", e.target.value)} className="input" /></Field>
            <Field label="Pickup Date/Time"><input type="datetime-local" data-testid="ma-pickup-dt" value={form.pickup_datetime} onChange={e=>update("pickup_datetime", e.target.value)} className="input" /></Field>
            <Field label="Delivery Date/Time"><input type="datetime-local" data-testid="ma-delivery-dt" value={form.delivery_datetime} onChange={e=>update("delivery_datetime", e.target.value)} className="input" /></Field>
            <Field label="Offered Rate ($)"><input data-testid="ma-rate" type="number" value={form.offered_rate} onChange={e=>update("offered_rate", e.target.value)} className="input" /></Field>
            <Field label="Loaded Miles"><input data-testid="ma-loaded" type="number" value={form.loaded_miles} onChange={e=>update("loaded_miles", e.target.value)} className="input" /></Field>
            <Field label="Deadhead Miles"><input data-testid="ma-deadhead" type="number" value={form.deadhead_miles} onChange={e=>update("deadhead_miles", e.target.value)} className="input" /></Field>
            <Field label="Weight (lb)"><input type="number" value={form.weight} onChange={e=>update("weight", e.target.value)} className="input" /></Field>
            <Field label="Driver Type">
              <select value={form.driver_type} onChange={e=>update("driver_type", e.target.value)} className="input"><option>Solo</option><option>Team</option></select>
            </Field>
            <Field label="Driver Pay CPM (override)"><input type="number" step="0.01" value={form.driver_pay_cpm} onChange={e=>update("driver_pay_cpm", e.target.value)} placeholder="use default" className="input" /></Field>
            <Field label="Fuel Price (override)"><input type="number" step="0.01" value={form.fuel_price} onChange={e=>update("fuel_price", e.target.value)} placeholder="use default" className="input" /></Field>
            <Field label="MPG (override)"><input type="number" step="0.1" value={form.mpg} onChange={e=>update("mpg", e.target.value)} placeholder="use default" className="input" /></Field>
            <Field label="Toll Estimate"><input type="number" value={form.tolls} onChange={e=>update("tolls", e.target.value)} placeholder="use default" className="input" /></Field>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button onClick={()=>{setForm(DEFAULT_FORM); setResult(null);}} className="px-3 py-1.5 text-sm rounded" style={{border:"1px solid var(--border)"}}>Reset</button>
            <button onClick={analyze} disabled={busy} data-testid="ma-analyze-btn" className="btn-primary rounded px-4 py-1.5 text-sm">{busy?"Analyzing…":"Analyze Load"}</button>
          </div>
        </div>

        {/* RESULT */}
        <div className="space-y-4">
          {result ? (
            <>
              <div className="terminal-card p-5">
                <div className="flex items-center justify-between mb-3">
                  <div className="kpi-label">AI Decision</div>
                  <span className={`badge decision-${result.decision}`} data-testid="ma-decision">{result.decision.toUpperCase()}</span>
                </div>
                <div className="flex items-center gap-4">
                  {(() => { const Ic = decisionIcon[result.decision]; return <Ic className="w-10 h-10" style={{color: result.risk==="Green"?"var(--brand)":result.risk==="Yellow"?"var(--warn)":"var(--danger)"}} />; })()}
                  <div>
                    <div className="font-display font-bold text-3xl">{result.decision}</div>
                    <div className="text-sm mt-1" style={{color:"var(--text-2)"}}>Load Score: <span className="font-bold" style={{color:"var(--text)"}}>{result.score}/100</span> · Risk <span className={`badge risk-${result.risk}`}>{result.risk}</span></div>
                  </div>
                </div>
                <div className="mt-4 p-3 rounded font-mono text-xs leading-relaxed" style={{background:"var(--surface-2)", color:"var(--text-2)"}} data-testid="ma-reasoning">
                  {result.reasoning}
                </div>
              </div>

              <div className="terminal-card p-5">
                <div className="kpi-label mb-3">Financials Breakdown</div>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <Stat label="Total Miles" value={<Num v={result.total_miles} />} />
                  <Stat label="Rate Per Mile" value={<span className="font-mono">${result.rpm}</span>} />
                  <Stat label="Fuel Cost" value={<Money v={result.fuel_cost} />} sub={`${result.fuel_gallons} gal`} />
                  <Stat label="Driver Pay" value={<Money v={result.driver_pay} />} />
                  <Stat label="Tolls" value={<Money v={result.tolls} />} />
                  <Stat label="Insurance / Rental" value={<Money v={result.insurance + result.rental} />} />
                  <Stat label="Factoring Fee" value={<Money v={result.factoring} />} />
                  <Stat label="Total Trip Cost" value={<Money v={result.trip_cost} />} />
                  <Stat label="Net Profit" value={<Money v={result.net_profit} />} tone={result.net_profit>=0?"good":"bad"} />
                  <Stat label="Margin %" value={<span className="font-mono">{result.margin_pct}%</span>} tone={result.margin_pct>=15?"good":result.margin_pct>=0?"warn":"bad"} />
                  <Stat label="Profit / Mile" value={<span className="font-mono">${result.profit_per_mile}</span>} />
                  <Stat label="Deadhead %" value={<span className="font-mono">{result.deadhead_pct}%</span>} tone={result.deadhead_pct<15?"good":result.deadhead_pct<25?"warn":"bad"} />
                </div>
              </div>

              <div className="terminal-card p-5">
                <div className="kpi-label mb-3">Negotiation Targets</div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="p-3 rounded" style={{background:"var(--brand-soft)", border:"1px solid var(--brand)"}}>
                    <div className="text-[10px] font-mono uppercase" style={{color:"var(--text-3)"}}>Target Rate</div>
                    <div className="font-display font-bold text-2xl" style={{color:"var(--brand)"}}><Money v={result.target_rate} /></div>
                    <div className="text-[11px] mt-1" style={{color:"var(--text-2)"}}>To hit target margin</div>
                  </div>
                  <div className="p-3 rounded" style={{background:"var(--surface-2)", border:"1px solid var(--border)"}}>
                    <div className="text-[10px] font-mono uppercase" style={{color:"var(--text-3)"}}>Minimum Acceptable</div>
                    <div className="font-display font-bold text-2xl"><Money v={result.min_acceptable_rate} /></div>
                    <div className="text-[11px] mt-1" style={{color:"var(--text-2)"}}>Break-even + 8%</div>
                  </div>
                </div>
                {result.decision !== "Reject" && (
                  <button onClick={bookLoad} data-testid="ma-book-btn" className="mt-4 w-full btn-primary rounded px-4 py-2 text-sm">Book Load → Add to Dispatch Board</button>
                )}
              </div>
            </>
          ) : (
            <div className="terminal-card p-8 text-center">
              <LineIcon className="w-10 h-10 mx-auto mb-3" style={{color:"var(--text-3)"}} />
              <div className="font-display font-bold text-lg mb-1">Awaiting analysis</div>
              <div className="text-sm" style={{color:"var(--text-2)"}}>Enter load details and click <b>Analyze Load</b> to get an AI Book / Negotiate / Reject decision with target rates.</div>
            </div>
          )}
        </div>
      </div>
      <style>{`.input{width:100%;background:var(--surface-2);border:1px solid var(--border);border-radius:4px;padding:6px 8px;font-size:13px;color:var(--text);outline:none;font-family:'IBM Plex Mono',monospace;}`}</style>
    </div>
  );
}

function Field({ label, children }) {
  return (<div><div className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{color:"var(--text-3)"}}>{label}</div>{children}</div>);
}
function Stat({ label, value, sub, tone }) {
  const c = tone==="good"?"var(--brand)":tone==="warn"?"var(--warn)":tone==="bad"?"var(--danger)":"var(--text)";
  return (<div><div className="text-[10px] font-mono uppercase tracking-widest mb-0.5" style={{color:"var(--text-3)"}}>{label}</div><div className="font-display font-bold" style={{color:c}}>{value}</div>{sub && <div className="text-[10px]" style={{color:"var(--text-3)"}}>{sub}</div>}</div>);
}
