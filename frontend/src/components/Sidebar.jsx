import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Columns3, Package, TruckIcon, Users, Radio, Route,
  CloudRain, Fuel, Satellite, FileText, Receipt, TrendingUp, UserCheck,
  BarChart3, Sparkles, Settings, Gauge, LogOut, Zap
} from "lucide-react";
import { useAuth } from "../lib/auth";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, roles: ["owner","dispatcher","finance","admin","driver"] },
  { to: "/board", label: "Operations Board", icon: Columns3, roles: ["owner","dispatcher","admin"] },
  { to: "/loads", label: "Loads", icon: Package, roles: ["owner","dispatcher","finance","admin","driver"] },
  { to: "/trucks", label: "Trucks", icon: TruckIcon, roles: ["owner","dispatcher","admin"] },
  { to: "/drivers", label: "Drivers", icon: Users, roles: ["owner","dispatcher","admin"] },
  { to: "/dispatch", label: "Dispatch", icon: Radio, roles: ["owner","dispatcher","admin"] },
  { to: "/in-transit", label: "In-Transit Control", icon: Route, roles: ["owner","dispatcher","admin"] },
  { to: "/weather", label: "Weather & Road Risk", icon: CloudRain, roles: ["owner","dispatcher","admin"] },
  { to: "/fuel", label: "Fuel Stop Planner", icon: Fuel, roles: ["owner","dispatcher","admin"] },
  { to: "/telematics", label: "Samsara / Telematics", icon: Satellite, roles: ["owner","dispatcher","admin"] },
  { to: "/documents", label: "Documents", icon: FileText, roles: ["owner","dispatcher","finance","admin"] },
  { to: "/invoices", label: "Invoices", icon: Receipt, roles: ["owner","finance","admin"] },
  { to: "/pnl", label: "Trip P&L", icon: TrendingUp, roles: ["owner","finance","admin"] },
  { to: "/driver-scorecard", label: "Driver Scorecard", icon: UserCheck, roles: ["owner","dispatcher","finance","admin"] },
  { to: "/truck-scorecard", label: "Truck Scorecard", icon: Gauge, roles: ["owner","admin"] },
  { to: "/reports", label: "Reports", icon: BarChart3, roles: ["owner","finance","admin"] },
  { to: "/ai", label: "AI Assistant", icon: Sparkles, roles: ["owner","dispatcher","finance","admin"] },
  { to: "/settings", label: "Settings", icon: Settings, roles: ["owner","admin"] },
];

export default function Sidebar() {
  const { user, logout } = useAuth();
  const nav = useNavigate();

  return (
    <aside className="w-64 shrink-0 border-r border-zinc-800 bg-[#0A0A0C] flex flex-col h-screen sticky top-0">
      <div className="px-4 py-4 border-b border-zinc-800 flex items-center gap-2">
        <div className="w-8 h-8 rounded-md bg-sky-500/10 border border-sky-500/30 flex items-center justify-center">
          <Zap className="w-4 h-4 text-sky-400" strokeWidth={2} />
        </div>
        <div>
          <div className="font-display font-bold text-sm tracking-tight">AI Dispatch.RR</div>
          <div className="font-mono text-[10px] text-zinc-500 uppercase tracking-widest">Control Tower</div>
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
      <div className="border-t border-zinc-800 p-3">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-8 h-8 rounded-full bg-zinc-800 flex items-center justify-center text-xs font-mono">
            {(user?.name || "U").slice(0,1)}
          </div>
          <div className="min-w-0">
            <div className="text-xs font-medium truncate">{user?.name || "Guest"}</div>
            <div className="text-[10px] text-zinc-500 font-mono uppercase">{user?.role || "guest"}</div>
          </div>
          <button
            onClick={() => { logout(); nav("/login"); }}
            data-testid="sidebar-logout-btn"
            className="ml-auto p-1.5 rounded text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800"
            title="Logout"
          >
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </aside>
  );
}
