import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import { useAuth } from "../lib/auth";
import { useTheme } from "../lib/theme";
import api from "../lib/api";
import { toast, Toaster } from "sonner";
import { Monitor, Sun, Moon, User, Palette, Sliders } from "lucide-react";

export default function Settings() {
  const { user } = useAuth();
  const { pref, resolved, setTheme } = useTheme();
  const [a, setA] = useState(null);

  useEffect(() => { api.get("/assumptions").then(r=>setA(r.data)); }, []);

  const reseed = async () => {
    if (!window.confirm("Wipe & re-seed sample data?")) return;
    await api.post("/seed?force=true");
    toast.success("Re-seeded");
    setTimeout(()=>window.location.reload(), 1000);
  };

  const saveAssumptions = async () => {
    const editable = Object.fromEntries(numFields.map(([key]) => [key, a[key]]));
    await api.put("/assumptions", editable);
    toast.success("Cost assumptions saved");
  };

  const themes = [
    { k: "auto", label: "Automatic / System", icon: Monitor, desc: "Follow device preference" },
    { k: "light", label: "Light", icon: Sun, desc: "Warm ivory + amber" },
    { k: "dark",  label: "Dark",  icon: Moon, desc: "Dark navy + amber" },
  ];

  const numFields = [
    ["fuel_price", "Fuel Price ($/gal)", 0.01],
    ["mpg", "Estimated MPG", 0.1],
    ["driver_pay_solo_cpm", "Solo Driver Pay ($/mi)", 0.01],
    ["driver_pay_team_cpm", "Team Driver Pay ($/mi)", 0.01],
    ["insurance_per_week", "Insurance ($/truck/wk)", 10],
    ["rental_per_week", "Rental ($/truck/wk)", 10],
    ["factoring_fee_pct", "Factoring Fee (%)", 0.1],
    ["default_toll", "Default Toll ($)", 5],
    ["target_margin_pct", "Target Margin (%)", 1],
    ["min_rpm", "Minimum RPM ($/mi)", 0.05],
    ["min_net_profit", "Min Net Profit / Load ($)", 25],
  ];

  return (
    <div>
      <Toaster position="top-right" />
      <Topbar title="Settings" subtitle="Preferences · Cost Assumptions · Integrations" />
      <div className="p-6 grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Theme */}
        <div className="terminal-card p-4 lg:col-span-2">
          <div className="kpi-label mb-3 flex items-center gap-1.5"><Palette className="w-3.5 h-3.5" /> Theme</div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {themes.map(t => {
              const active = pref === t.k;
              return (
                <button
                  key={t.k}
                  onClick={()=>setTheme(t.k)}
                  data-testid={`theme-${t.k}`}
                  className={`text-left p-4 rounded transition-all ${active?"ring-2":""}`}
                  style={{background: active?"var(--brand-soft)":"var(--surface-2)", border:`1px solid ${active?"var(--brand)":"var(--border)"}`}}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <t.icon className="w-4 h-4" style={{color: active?"var(--brand)":"var(--text-2)"}} />
                    <div className="font-display font-bold">{t.label}</div>
                    {active && <span className="badge decision-Book ml-auto">ACTIVE</span>}
                  </div>
                  <div className="text-xs" style={{color:"var(--text-2)"}}>{t.desc}</div>
                </button>
              );
            })}
          </div>
          <div className="mt-3 text-xs font-mono" style={{color:"var(--text-3)"}}>Preference: <b>{pref}</b> · currently rendering: <b style={{color:"var(--brand)"}}>{resolved}</b></div>
        </div>

        {/* User */}
        <div className="terminal-card p-4">
          <div className="kpi-label mb-2 flex items-center gap-1.5"><User className="w-3.5 h-3.5" /> Current User</div>
          <div className="text-sm space-y-1 font-mono">
            <div>Name: {user?.name}</div>
            <div>Email: {user?.email}</div>
            <div>Role: <span className="font-bold uppercase" style={{color:"var(--brand)"}}>{user?.role}</span></div>
          </div>
        </div>

        {/* Integrations */}
        <div className="terminal-card p-4">
          <div className="kpi-label mb-2">Integration Status (Placeholders)</div>
          <div className="text-xs space-y-1 font-mono" style={{color:"var(--text-2)"}}>
            <div>✓ Claude Sonnet 4.6 — Emergent LLM Key</div>
            <div>◦ Google Maps Routes — mock (hook ready)</div>
            <div>◦ OpenWeatherMap — mock</div>
            <div>◦ Samsara Telematics — mock</div>
            <div>◦ Twilio SMS / WhatsApp — mock</div>
            <div>◦ Telegram — mock</div>
            <div>◦ Emergent Object Storage — metadata only</div>
          </div>
        </div>

        {/* Cost Assumptions */}
        <div className="terminal-card p-4 lg:col-span-2">
          <div className="kpi-label mb-3 flex items-center gap-1.5"><Sliders className="w-3.5 h-3.5" /> Cost Assumptions (Load Decision Engine)</div>
          <div className="text-xs mb-3" style={{color:"var(--text-2)"}}>These drive the Book / Negotiate / Reject decisions on the Load Market Analysis screen.</div>
          {a ? (
            <>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                {numFields.map(([k, l, step]) => (
                  <div key={k}>
                    <div className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{color:"var(--text-3)"}}>{l}</div>
                    <input
                      type="number" step={step} value={a[k] ?? 0}
                      onChange={e=>setA({...a, [k]: Number(e.target.value)})}
                      data-testid={`assumption-${k}`}
                      className="w-full rounded px-2 py-1.5 text-sm outline-none font-mono"
                      style={{background:"var(--surface-2)", border:"1px solid var(--border)", color:"var(--text)"}}
                    />
                  </div>
                ))}
              </div>
              <div className="mt-4 flex justify-end">
                <button onClick={saveAssumptions} data-testid="save-assumptions-btn" className="btn-primary rounded px-4 py-1.5 text-sm">Save Assumptions</button>
              </div>
            </>
          ) : <div className="text-xs" style={{color:"var(--text-3)"}}>Loading…</div>}
        </div>

        {/* Data */}
        <div className="terminal-card p-4 lg:col-span-2">
          <div className="kpi-label mb-2">Data</div>
          <button onClick={reseed} data-testid="reseed-btn" className="rounded px-3 py-1.5 text-xs" style={{background:"rgba(239,68,68,0.15)", border:"1px solid var(--danger)", color:"var(--danger)"}}>Wipe & Re-seed Sample Data</button>
        </div>
      </div>
    </div>
  );
}
