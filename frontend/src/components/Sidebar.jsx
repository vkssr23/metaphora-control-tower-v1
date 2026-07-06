import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Columns3, Package, TruckIcon, Users, Radio, Route,
  CloudRain, Fuel, Satellite, FileText, Receipt, TrendingUp, UserCheck,
  BarChart3, Sparkles, Settings, Gauge, LogOut, ShieldCheck, LineChart, BellRing,
  Command
} from "lucide-react";
import { useAuth } from "../lib/auth";

const NAV = [
  { to: "/", label: "Executive Dashboard", icon: LayoutDashboard, roles: ["owner","dispatcher","finance","admin","driver","operations","safety","compliance"] },
  { to: "/analyze", label: "Load Market Analysis", icon: LineChart, roles: ["owner","dispatcher","operations","admin"] },
  { to: "/board", label: "Dispatch Board", icon: Columns3, roles: ["owner","dispatcher","operations","admin"] },
  { to: "/loads", label: "Loads", icon: Package, roles: ["owner","dispatcher","finance","admin","operations"] },
  { to: "/trucks", label: "Trucks", icon: TruckIcon, roles: ["owner","dispatcher","operations","admin"] },
  { to: "/drivers", label: "Drivers", icon: Users, roles: ["owner","dispatcher","operations","admin","safety"] },
  { to: "/compliance", label: "Compliance", icon: ShieldCheck, roles: ["owner","safety","compliance","operations","admin"] },
  { to: "/dispatch", label: "Dispatch Queue", icon: Radio, roles: ["owner","dispatcher","operations","admin"] },
  { to: "/in-transit", label: "In-Transit", icon: Route, roles: ["owner","dispatcher","operations","admin"] },
  { to: "/weather", label: "Weather & Roads", icon: CloudRain, roles: ["owner","dispatcher","operations","admin"] },
  { to: "/fuel", label: "Fuel Stops", icon: Fuel, roles: ["owner","dispatcher","operations","admin"] },
  { to: "/telematics", label: "Telematics", icon: Satellite, roles: ["owner","dispatcher","operations","admin"] },
  { to: "/documents", label: "Documents", icon: FileText, roles: ["owner","dispatcher","finance","admin","operations"] },
  { to: "/invoices", label: "Invoices", icon: Receipt, roles: ["owner","finance","admin"] },
  { to: "/pnl", label: "Profitability", icon: TrendingUp, roles: ["owner","finance","admin"] },
  { to: "/driver-scorecard", label: "Driver Scorecard", icon: UserCheck, roles: ["owner","dispatcher","finance","admin","safety"] },
  { to: "/truck-scorecard", label: "Truck Scorecard", icon: Gauge, roles: ["owner","admin","operations"] },
  { to: "/reports", label: "Reports", icon: BarChart3, roles: ["owner","finance","admin","operations"] },
  { to: "/ai", label: "AI Assistant", icon: Sparkles, roles: ["owner","dispatcher","finance","admin","operations","safety","compliance"] },
  { to: "/settings", label: "Settings", icon: Settings, roles: ["owner","admin"] },
];

export default function Sidebar() {
  const { user, logout } = useAuth();
  const nav = useNavigate();

  return (
    <aside className="w-64 shrink-0 border-r flex flex-col h-screen sticky top-0" style={{background:"var(--surface)", borderColor:"var(--border)"}}>
      <div className="px-4 py-4 border-b flex items-center gap-2" style={{borderColor:"var(--border)"}}>
        <div className="w-9 h-9 rounded-md flex items-center justify-center" style={{background:"var(--brand-soft)", border:"1px solid var(--brand)"}}>
          <Command className="w-4 h-4" strokeWidth={2} style={{color:"var(--brand)"}} />
        </div>
        <div>
          <div className="font-display font-bold text-sm tracking-tight" style={{color:"var(--text)"}}>Metaphora AI</div>
          <div className="font-mono text-[10px] uppercase tracking-widest" style={{color:"var(--text-3)"}}>Control Tower</div>
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5" data-testid="sidebar-nav">
        {NAV.filter(n => !user?.role || n.roles.includes(user.role)).map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === "/"}
            data-testid={`nav-${n.label.toLowerCase().replace(/[^a-z0-9]+/g,'-')}`}
            className={({ isActive }) => `sidebar-item ${isActive ? "active" : ""}`}
          >
            <n.icon className="w-4 h-4" strokeWidth={1.5} />
            <span>{n.label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="border-t p-3" style={{borderColor:"var(--border)"}}>
        <div className="flex items-center gap-2 mb-2">
          <div className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-mono" style={{background:"var(--surface-2)"}}>
            {(user?.name || "U").slice(0,1)}
          </div>
          <div className="min-w-0">
            <div className="text-xs font-medium truncate" style={{color:"var(--text)"}}>{user?.name || "Guest"}</div>
            <div className="text-[10px] font-mono uppercase" style={{color:"var(--text-3)"}}>{user?.role || "guest"}</div>
          </div>
          <button
            onClick={() => { logout(); nav("/login"); }}
            data-testid="sidebar-logout-btn"
            className="ml-auto p-1.5 rounded hover:opacity-70"
            style={{color:"var(--text-3)"}}
            title="Logout"
          >
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </aside>
  );
}
