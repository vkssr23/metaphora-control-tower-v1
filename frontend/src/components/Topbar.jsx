import React from "react";
import { Search, Bell } from "lucide-react";

export default function Topbar({ title, subtitle, actions }) {
  return (
    <div className="border-b border-zinc-800 bg-[#0A0A0C]/80 backdrop-blur sticky top-0 z-30">
      <div className="flex items-center gap-4 px-6 py-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-3">
            <h1 className="font-display font-bold text-lg tracking-tight" data-testid="page-title">{title}</h1>
            {subtitle && <span className="text-xs text-zinc-500 font-mono uppercase tracking-widest">{subtitle}</span>}
          </div>
        </div>
        <div className="hidden md:flex items-center gap-2 bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 w-72">
          <Search className="w-3.5 h-3.5 text-zinc-500" />
          <input placeholder="Search loads, trucks, drivers…" className="bg-transparent outline-none text-sm flex-1 placeholder:text-zinc-600" data-testid="topbar-search" />
        </div>
        <button className="p-2 rounded hover:bg-zinc-800 relative" data-testid="topbar-notifications">
          <Bell className="w-4 h-4 text-zinc-400" />
          <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-red-500"></span>
        </button>
        {actions}
      </div>
    </div>
  );
}
