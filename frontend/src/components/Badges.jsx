import React from "react";

const stageMap = {
  "Booked":"Booked","Assigned":"Assigned","Dispatched":"Dispatched",
  "Pickup Started":"Pickup","Arrived Pickup":"Pickup","Loaded":"Transit",
  "In Transit":"Transit","Arrived Delivery":"Delivered","Delivered":"Delivered",
  "Docs Pending":"Docs","Invoice Pending":"Invoice","Payment Pending":"Payment",
  "Closed":"Closed","Exception":"Exception"
};

export function StageBadge({ stage }) {
  const key = stageMap[stage] || "Booked";
  return <span className={`badge stage-${key}`} data-testid={`stage-badge-${stage}`}>{stage}</span>;
}

export function RiskBadge({ risk }) {
  return <span className={`badge risk-${risk || "Low"}`} data-testid={`risk-badge-${risk}`}>{risk || "Low"}</span>;
}

export function Money({ v, className="" }) {
  const n = Number(v || 0);
  return <span className={`font-mono ${className}`}>${n.toLocaleString(undefined,{minimumFractionDigits:0, maximumFractionDigits:0})}</span>;
}

export function Num({ v, decimals=0, suffix="", className="" }) {
  const n = Number(v || 0);
  return <span className={`font-mono ${className}`}>{n.toLocaleString(undefined,{minimumFractionDigits:decimals,maximumFractionDigits:decimals})}{suffix}</span>;
}
