import React from "react";
import { Search, Bell, Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "../lib/theme";

export default function Topbar({ title, subtitle, actions }) {
  const { pref, setTheme } = useTheme();
  const nextTheme = () => setTheme(pref === "auto" ? "light" : pref === "light" ? "dark" : "auto");
  const Icon = pref === "auto" ? Monitor : pref === "light" ? Sun : Moon;

  return (
    <div className="border-b sticky top-0 z-30" style={{background:"var(--surface)", borderColor:"var(--border)"}}>
      <div className="flex items-center gap-4 px-6 py-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-3">
            <h1 className="font-display font-bold text-lg tracking-tight" data-testid="page-title">{title}</h1>
            {subtitle && <span className="text-xs font-mono uppercase tracking-widest" style={{color:"var(--text-3)"}}>{subtitle}</span>}
          </div>
        </div>
        <div
          className="hidden md:flex items-center gap-2 px-3 w-72 border"
          style={{background:"var(--bg-field)", borderColor:"var(--border-strong)", height:"var(--h-toolbar)", borderRadius:"var(--r-control)"}}
        >
          <Search className="w-3.5 h-3.5" style={{color:"var(--text-3)"}} />
          <input
            placeholder="Search loads, trucks, drivers…"
            className="bg-transparent outline-none flex-1"
            style={{color:"var(--text-3)", fontFamily:"var(--font-mono)", fontSize:"11.5px"}}
            data-testid="topbar-search"
          />
        </div>
        <button
          onClick={nextTheme}
          className="p-2 hover:opacity-70"
          style={{background:"var(--surface-2)", borderRadius:"var(--r-control)"}}
          title={`Theme: ${pref}`}
          data-testid="theme-toggle-btn"
        >
          <Icon className="w-4 h-4" style={{color:"var(--text-2)"}} />
        </button>
        <button className="p-2 hover:opacity-70 relative" style={{background:"var(--surface-2)", borderRadius:"var(--r-control)"}} data-testid="topbar-notifications">
          <Bell className="w-4 h-4" style={{color:"var(--text-2)"}} />
          <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full" style={{background:"var(--danger)"}}></span>
        </button>
        {actions}
      </div>
    </div>
  );
}
