import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Columns3, Package, TruckIcon, Users, Radio, Route,
  CloudRain, Fuel, Satellite, FileText, Receipt, TrendingUp, UserCheck,
  BarChart3, Sparkles, Settings, Gauge, LogOut, Zap
} from "lucide-react";
import { useAuth } from "../lib/auth";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/board", label: "Operations Board", icon: Columns3 },
  { to: "/loads", label: "Loads", icon: Package },
  { to: "/trucks", label: "Trucks", icon: TruckIcon },
  { to: "/drivers", label: "Drivers", icon: Users },
  { to: "/dispatch", label: "Dispatch", icon: Radio },
  { to: "/in-transit", label: "In-Transit Control", icon: Route },
  { to: "/weather", label: "Weather & Road Risk", icon: CloudRain },
  { to: "/fuel", label: "Fuel Stop Planner", icon: Fuel },
  { to: "/telematics", label: "Samsara / Telematics", icon: Satellite },
  { to: "/documents", label: "Documents", icon: FileText },
  { to: "/invoices", label: "Invoices", icon: Receipt },
  { to: "/pnl", label: "Trip P&L", icon: TrendingUp },
  { to: "/driver-scorecard", label: "Driver Scorecard", icon: UserCheck },
  { to: "/truck-scorecard", label: "Truck Scorecard", icon: Gauge },
  { to: "/reports", label: "Reports", icon: BarChart3 },
  { to: "/ai", label: "AI Assistant", icon: Sparkles },
  { to: "/settings", label: "Settings", icon: Settings },
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
          <div className="font-display font-bold text-sm tracking-tight">AI Dispatch OS</div>
          <div className="font-mono text-[10px] text-zinc-500 uppercase tracking-widest">Control Tower</div>
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5" data-testid="sidebar-nav">
        {NAV.map((n) => (
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
