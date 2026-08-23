import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import { Money, Num } from "../components/Badges";
import api from "../lib/api";
import { LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { TrendingUp, TrendingDown, Truck, Users, AlertTriangle, DollarSign, Package, Clock } from "lucide-react";

const TONE = { danger: "var(--danger-text)", success: "var(--ok-text)", warn: "var(--accent-text)", default: "var(--text)" };

const KPI = ({ label, value, hint, icon: Icon, tone="default", testId }) => {
  return (
    <div className="panel panel--stat" data-testid={testId}>
      <div className="flex items-center justify-between">
        <div className="micro-label">{label}</div>
        {Icon && <Icon className="w-3.5 h-3.5" strokeWidth={1.5} style={{color: TONE[tone]}} />}
      </div>
      <div style={{fontFamily:"var(--font-mono)", fontWeight:700, fontSize:"22px", letterSpacing:"-0.02em", color: TONE[tone]}}>{value}</div>
      {hint && <div className="text-[11px] mt-1" style={{color:"var(--text-3)", fontFamily:"var(--font-mono)"}}>{hint}</div>}
    </div>
  );
};

const COLORS = ["#0EA5E9","#10B981","#F59E0B","#EF4444","#A855F7","#EC4899","#06B6D4","#84CC16","#F97316","#6366F1"];

const chartTooltipStyle = { background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12 };

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [charts, setCharts] = useState(null);

  useEffect(() => {
    api.get("/dashboard/stats").then(r => setStats(r.data));
    api.get("/dashboard/charts").then(r => setCharts(r.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!stats) return <div className="p-6" style={{color:"var(--text-3)"}}>Loading control tower…</div>;

  return (
    <div>
      <Topbar title="Command Dashboard" subtitle="Live · Owner View" />
      <div className="p-6 space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
          <KPI testId="kpi-revenue" label="Total Revenue" value={<Money v={stats.total_revenue} />} icon={DollarSign} tone="success" />
          <KPI testId="kpi-gross-profit" label="Gross Profit" value={<Money v={stats.gross_profit} />} icon={TrendingUp} tone="success" />
          <KPI testId="kpi-net-profit" label="Net Profit Est." value={<Money v={stats.net_profit} />} />
          <KPI testId="kpi-active-loads" label="Active Loads" value={<Num v={stats.active_loads} />} icon={Package} />
          <KPI testId="kpi-in-transit" label="In Transit" value={<Num v={stats.loads_transit} />} icon={Truck} />
          <KPI testId="kpi-at-risk" label="At-Risk Loads" value={<Num v={stats.at_risk_loads} />} icon={AlertTriangle} tone="danger" />
          <KPI testId="kpi-rpm" label="Revenue / Mile" value={<Money v={stats.revenue_per_mile} />} />
          <KPI testId="kpi-ppm" label="Profit / Mile" value={<Money v={stats.profit_per_mile} />} />
          <KPI testId="kpi-active-trucks" label="Active Trucks" value={<Num v={stats.active_trucks} />} icon={Truck} />
          <KPI testId="kpi-idle-trucks" label="Idle Trucks" value={<Num v={stats.idle_trucks} />} tone="warn" icon={Clock} />
          <KPI testId="kpi-active-drivers" label="Active Drivers" value={<Num v={stats.active_drivers} />} icon={Users} />
          <KPI testId="kpi-missing-updates" label="Missing Updates" value={<Num v={stats.drivers_missing_updates} />} tone="warn" />
          <KPI label="Booked" value={<Num v={stats.loads_booked} />} />
          <KPI label="Assigned" value={<Num v={stats.loads_assigned} />} />
          <KPI label="At Pickup" value={<Num v={stats.loads_pickup} />} />
          <KPI label="Delivered" value={<Num v={stats.loads_delivered} />} />
          <KPI label="BOL/POD Pending" value={<Num v={stats.bol_pending} />} tone="warn" />
          <KPI label="Invoice Pending" value={<Num v={stats.invoice_pending} />} tone="warn" />
          <KPI label="Payment Pending" value={<Num v={stats.payment_pending} />} tone="warn" />
          <KPI label="Closed" value={<Num v={stats.loads_closed} />} />
          <KPI label="Fuel Cost" value={<Money v={stats.fuel_cost} />} />
          <KPI label="Pending Invoice $" value={<Money v={stats.pending_invoice_amount} />} tone="warn" />
          <KPI label="Cash Expected (Wk)" value={<Money v={stats.cash_expected_week} />} tone="success" />
          <KPI label="Delayed" value={<Num v={stats.delayed_loads} />} tone="danger" />
        </div>

        {charts && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="panel lg:col-span-2 p-4">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <div className="micro-label">Revenue by Week</div>
                  <div className="font-display font-bold text-lg">Trend</div>
                </div>
              </div>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={charts.revenue_by_week}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" />
                  <XAxis dataKey="week" stroke="var(--text-3)" fontSize={11} />
                  <YAxis stroke="var(--text-3)" fontSize={11} />
                  <Tooltip contentStyle={chartTooltipStyle} />
                  <Line type="monotone" dataKey="revenue" stroke="var(--accent-2)" strokeWidth={2} dot={{r:3, fill:"var(--accent-2)"}} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="panel p-4">
              <div className="micro-label">Load Status Distribution</div>
              <div className="font-display font-bold text-lg mb-2">Stages</div>
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie data={charts.stage_distribution} dataKey="count" nameKey="stage" innerRadius={45} outerRadius={80} paddingAngle={2}>
                    {charts.stage_distribution.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={chartTooltipStyle} />
                </PieChart>
              </ResponsiveContainer>
            </div>

            <div className="panel p-4">
              <div className="micro-label">Profit by Truck</div>
              <div className="font-display font-bold text-lg mb-2">Fleet Performance</div>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={charts.profit_by_truck}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" />
                  <XAxis dataKey="truck" stroke="var(--text-3)" fontSize={10} />
                  <YAxis stroke="var(--text-3)" fontSize={11} />
                  <Tooltip contentStyle={chartTooltipStyle} />
                  <Bar dataKey="profit" fill="var(--ok)" />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="panel p-4">
              <div className="micro-label">Fuel Cost Trend</div>
              <div className="font-display font-bold text-lg mb-2">7-Day</div>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={charts.fuel_trend}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" />
                  <XAxis dataKey="day" stroke="var(--text-3)" fontSize={11} />
                  <YAxis stroke="var(--text-3)" fontSize={11} />
                  <Tooltip contentStyle={chartTooltipStyle} />
                  <Line type="monotone" dataKey="cost" stroke="var(--accent)" strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="panel p-4">
              <div className="micro-label">Revenue by Driver</div>
              <div className="font-display font-bold text-lg mb-2">Top Contributors</div>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={charts.profit_by_driver} layout="vertical">
                  <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" />
                  <XAxis type="number" stroke="var(--text-3)" fontSize={11} />
                  <YAxis type="category" dataKey="driver" stroke="var(--text-3)" fontSize={10} width={70} />
                  <Tooltip contentStyle={chartTooltipStyle} />
                  <Bar dataKey="revenue" fill="var(--accent-2)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
