import React from "react";
import Topbar from "../components/Topbar";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import { toast, Toaster } from "sonner";

export default function Settings() {
  const { user } = useAuth();
  const reseed = async () => {
    if (!confirm("Wipe & re-seed sample data?")) return;
    await api.post("/seed?force=true");
    toast.success("Re-seeded");
    setTimeout(()=>window.location.reload(), 1000);
  };
  return (
    <div>
      <Toaster position="top-right" theme="dark" />
      <Topbar title="Settings" subtitle="Preferences · Integrations" />
      <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="terminal-card p-4">
          <div className="kpi-label mb-2">Current User</div>
          <div className="text-sm space-y-1 font-mono">
            <div>Name: {user?.name}</div>
            <div>Email: {user?.email}</div>
            <div>Role: <span className="text-sky-400 uppercase">{user?.role}</span></div>
          </div>
        </div>
        <div className="terminal-card p-4">
          <div className="kpi-label mb-2">Integration Status (Placeholders)</div>
          <div className="text-xs space-y-1 font-mono">
            <div>✓ Claude Sonnet 4.6 (AI Assistant) — Emergent LLM Key</div>
            <div>◦ Google Maps Routes — <span className="text-zinc-500">mock (integration hook ready)</span></div>
            <div>◦ Weather API — <span className="text-zinc-500">mock</span></div>
            <div>◦ Road Conditions — <span className="text-zinc-500">mock</span></div>
            <div>◦ Samsara Telematics — <span className="text-zinc-500">mock</span></div>
            <div>◦ WhatsApp / Telegram / SMS — <span className="text-zinc-500">mock</span></div>
          </div>
        </div>
        <div className="terminal-card p-4">
          <div className="kpi-label mb-2">Roles</div>
          <div className="text-xs space-y-1 font-mono">
            <div>Owner — full access</div>
            <div>Dispatcher — loads, driver updates, stages</div>
            <div>Finance — invoices, docs, P&L</div>
            <div>Admin — users, settings, fleet</div>
            <div>Driver — assigned loads, submit updates</div>
          </div>
        </div>
        <div className="terminal-card p-4">
          <div className="kpi-label mb-2">Data</div>
          <button onClick={reseed} data-testid="reseed-btn" className="bg-red-500/20 border border-red-500/40 text-red-400 rounded px-3 py-1.5 text-xs">Wipe & Re-seed Sample Data</button>
        </div>
      </div>
    </div>
  );
}
