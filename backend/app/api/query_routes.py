from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import StreamingResponse
import os, logging, uuid, bcrypt, random, math, asyncio, re
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from app.config import force_seed_allowed
from app.permissions import require_capability, require_owner, require_audit_reader
from app.audit import begin_audit
from app.domain.audit_events import incomplete_operations
from app.schemas.audit import AuditEntityType, AuditOutcome, AuditSource
from app.security import create_token, public_user
from app.tenant import new_tenant_id, tenant_document, tenant_filter, require_tenant_id, require_tenant_reference
from app.production_integrity import evaluate_environment, evaluate_production_readiness
from app.domain.load_transitions import transition_allowed
from app.domain.load_passports import MATERIAL_LOAD_FIELDS, bounded_load_snapshot, build_preinvalidation, material_categories, utc_now
from app.invoice_readiness_invalidation import invalidate_invoice_readiness
from app.domain.invoice_readiness import BILLING_DOCUMENT_TYPES
from app.pickup_release_invalidation import preinvalidate_pickup_release, preinvalidate_pickup_for_execution_snapshot
from app.domain.party_verification import build_case_preinvalidation, build_passport_preinvalidation, is_insurance_document
from app.execution_invalidation import preinvalidate_for_load, preinvalidate_for_snapshot
from app.execution_material_change import control_material_load_change
from app.domain.mutation_impact import MutationType, SourceEntityType, TargetDomain, impact_for, has_impact, plan_mutation
from app.domain.invoice_authority import InvoiceAuthority, classify_invoice_authority, is_modern_invoice, legacy_write_allowed
from app.domain.execution_eligibility import DRIVER_MATERIAL_FIELDS, TRUCK_MATERIAL_FIELDS
from app.schemas import (
    AiChatRequest, AssumptionUpdate, DocumentCreate, DriverAlertRequest, DriverCreate,
    DriverUpdate, InvoiceCreate, InvoiceUpdate, LoadAnalysisRequest, LoadCreate,
    LoadIdRequest, LoadStage, LoadUpdate, RouteCalculationRequest,
    SamsaraVehicleRequest, StageChange as SafeStageChange, TruckCreate, TruckUpdate,
    WeatherCheckRequest,
)
from app.runtime import db, settings, now_iso, new_id, clean_doc, safe_db, audited_db
from app.constants import DEFAULT_ASSUMPTIONS


def register_query_routes(api, get_current_user, operational_write, finance_write):
    # ============ DASHBOARD ============
    @api.get("/dashboard/stats")
    async def dashboard_stats(user=Depends(get_current_user)):
        scope = tenant_filter(user)
        loads = await db.loads.find(scope, {"_id": 0}).to_list(2000)
        trucks = await db.trucks.find(scope, {"_id": 0}).to_list(1000)
        drivers = await db.drivers.find(scope, {"_id": 0}).to_list(1000)
        invoices = await db.invoices.find(scope, {"_id": 0}).to_list(2000)

        def in_stage(*stages): return [l for l in loads if l.get("stage") in stages]
        total_rev = sum(l.get("rate",0) for l in loads)
        total_exp = sum(l.get("fuel_cost",0)+l.get("tolls",0)+l.get("lumper",0)+l.get("driver_pay",0)+l.get("factoring_fee",0)+l.get("other_expenses",0) for l in loads)
        profit = total_rev - total_exp
        total_miles = sum(l.get("miles",0) for l in loads) or 1

        return {
            "total_revenue": total_rev,
            "gross_profit": profit,
            "net_profit": profit * 0.85,
            "active_loads": len([l for l in loads if l.get("stage") not in ("Closed","Exception")]),
            "loads_booked": len(in_stage("Booked")),
            "loads_assigned": len(in_stage("Assigned")),
            "loads_pickup": len(in_stage("Pickup Started","Arrived Pickup")),
            "loads_transit": len(in_stage("In Transit","Loaded")),
            "loads_delivered": len(in_stage("Delivered","Arrived Delivery")),
            "bol_pending": len([l for l in loads if l.get("bol_status")=="Pending" and l.get("stage") in ("Loaded","In Transit","Arrived Delivery","Delivered")]),
            "invoice_pending": len([l for l in loads if l.get("invoice_status") in ("Docs Pending","Ready to Invoice","Invoice Created","Invoice Shared","Payment Pending")]),
            "payment_pending": len([l for l in loads if l.get("payment_status")=="Pending" and l.get("stage") not in ("Booked","Assigned")]),
            "loads_closed": len(in_stage("Closed")),
            "active_trucks": len([t for t in trucks if t.get("status") not in ("Idle","Out of Service","Maintenance")]),
            "idle_trucks": len([t for t in trucks if t.get("status")=="Idle"]),
            "active_drivers": len([d for d in drivers if d.get("status") in ("Driving","Assigned","Available")]),
            "drivers_missing_updates": len([d for d in drivers if d.get("missed_updates",0)>0]),
            "at_risk_loads": len([l for l in loads if l.get("risk") in ("High","Critical")]),
            "delayed_loads": len([l for l in loads if l.get("risk") == "Critical"]),
            "fuel_cost": sum(l.get("fuel_cost",0) for l in loads),
            "revenue_per_mile": round(total_rev / total_miles, 2),
            "profit_per_mile": round(profit / total_miles, 2),
            "pending_invoice_amount": sum(i.get("amount",0) for i in invoices if i.get("status") not in ("Paid",)),
            "cash_expected_week": sum(i.get("amount",0) for i in invoices if i.get("status") in ("Invoice Shared","Payment Pending")),
        }

    @api.get("/dashboard/charts")
    async def dashboard_charts(user=Depends(get_current_user)):
        scope = tenant_filter(user)
        loads = await db.loads.find(scope, {"_id": 0}).to_list(2000)
        trucks = await db.trucks.find(scope, {"_id": 0}).to_list(1000)
        drivers = await db.drivers.find(scope, {"_id": 0}).to_list(1000)

        # revenue by week (last 6 weeks) - synthesize from load dates
        weeks = []
        for i in range(6, 0, -1):
            wk_start = datetime.now(timezone.utc) - timedelta(weeks=i)
            wk_rev = sum(l.get("rate",0) for l in loads if l.get("created_at","") >= wk_start.isoformat()) / (i+1)
            weeks.append({"week": f"W-{i}", "revenue": round(wk_rev, 0)})

        stage_dist = {}
        for l in loads:
            s = l.get("stage","?"); stage_dist[s] = stage_dist.get(s,0) + 1
        profit_by_truck = []
        for t in trucks[:12]:
            tloads = [l for l in loads if l.get("truck_id")==t.get("id")]
            rev = sum(l.get("rate",0) for l in tloads)
            exp = sum(l.get("fuel_cost",0)+l.get("driver_pay",0) for l in tloads)
            profit_by_truck.append({"truck": t.get("truck_number","?"), "profit": round(rev-exp, 0)})
        profit_by_driver = []
        for d in drivers[:10]:
            dloads = [l for l in loads if l.get("driver_id")==d.get("id")]
            rev = sum(l.get("rate",0) for l in dloads)
            profit_by_driver.append({"driver": d.get("name","?").split()[0], "revenue": round(rev, 0)})

        return {
            "revenue_by_week": weeks,
            "stage_distribution": [{"stage": k, "count": v} for k,v in stage_dist.items()],
            "profit_by_truck": profit_by_truck,
            "profit_by_driver": profit_by_driver,
            "fuel_trend": [{"day": f"D-{n}", "cost": random.randint(400, 1400)} for n in range(7,0,-1)],
        }


    @api.get("/assumptions")
    async def get_assumptions(user=Depends(get_current_user)):
        predicate = tenant_filter(user, {"id": "default"})
        doc = await db.assumptions.find_one(predicate, {"_id": 0})
        if not doc:
            defaults = tenant_document(user, DEFAULT_ASSUMPTIONS)
            await db.assumptions.insert_one(defaults)
            return defaults
        return doc

    @api.put("/assumptions")
    async def update_assumptions(data: AssumptionUpdate, user=Depends(finance_write)):
        updates = data.model_dump(mode="json", exclude_unset=True)
        previous = await safe_db(db.assumptions.find_one(tenant_filter(user, {"id": "default"}), {"_id": 0}), "assumption lookup")
        audit = await begin_audit(db.audit_events, user, "assumptions.updated", AuditEntityType.ASSUMPTIONS,
                                  "default", changed_fields=list(updates), previous=previous)
        await audited_db(audit, db.assumptions.update_one(tenant_filter(user, {"id": "default"}), {"$set": updates, "$setOnInsert": tenant_document(user, {"id": "default"})}, upsert=True), "assumption update")
        await audit.succeeded(updates)
        return {"ok": True}

    # ============ LOAD DECISION ENGINE ============
    @api.post("/loads/analyze")
    async def analyze_load(data: LoadAnalysisRequest, user=Depends(operational_write)):
        a = await safe_db(db.assumptions.find_one(tenant_filter(user, {"id": "default"}), {"_id": 0}), "analysis assumption lookup") or tenant_document(user, DEFAULT_ASSUMPTIONS)
        fuel_price = data.fuel_price if data.fuel_price is not None else a["fuel_price"]
        mpg = data.mpg if data.mpg is not None else a["mpg"]
        driver_cpm = data.driver_pay_cpm if data.driver_pay_cpm is not None else (a["driver_pay_team_cpm"] if data.driver_type.value == "Team" else a["driver_pay_solo_cpm"])
        tolls = data.tolls if data.tolls is not None else a["default_toll"]

        total_miles = data.loaded_miles + data.deadhead_miles
        if total_miles <= 0:
            raise HTTPException(400, "Miles must be > 0")

        rpm = round(data.offered_rate / total_miles, 2)
        fuel_gallons = round(total_miles / mpg, 1) if mpg > 0 else 0
        fuel_cost = round(fuel_gallons * fuel_price, 2)
        driver_pay = round(total_miles * driver_cpm, 2)
        insurance = round(a["insurance_per_week"] / 5, 2)   # amortize per trip (~5 trips/wk)
        rental = round(a["rental_per_week"] / 5, 2)
        factoring = round(data.offered_rate * a["factoring_fee_pct"] / 100, 2)

        trip_cost = fuel_cost + driver_pay + tolls + insurance + rental + factoring
        net_profit = round(data.offered_rate - trip_cost, 2)
        margin_pct = round((net_profit / data.offered_rate) * 100, 1) if data.offered_rate > 0 else 0
        profit_per_mile = round(net_profit / total_miles, 2) if total_miles > 0 else 0

        # Decision logic
        reasons = []
        risk = "Green"
        decision = "Book"

        if net_profit < 0:
            decision = "Reject"; risk = "Red"
            reasons.append(f"Negative net profit of ${net_profit}")
        elif rpm < a["min_rpm"] * 0.8:
            decision = "Reject"; risk = "Red"
            reasons.append(f"RPM ${rpm}/mi is critically below floor ${a['min_rpm']}/mi")
        elif net_profit < a["min_net_profit"] or margin_pct < a["target_margin_pct"] * 0.6:
            decision = "Negotiate"; risk = "Yellow"
            reasons.append(f"Net profit ${net_profit} below minimum ${a['min_net_profit']}" if net_profit < a["min_net_profit"] else f"Margin {margin_pct}% below target {a['target_margin_pct']}%")
        elif rpm < a["min_rpm"]:
            decision = "Negotiate"; risk = "Yellow"
            reasons.append(f"RPM ${rpm}/mi below minimum ${a['min_rpm']}/mi")
        else:
            reasons.append(f"Healthy margin {margin_pct}% at ${rpm}/mi")

        # Deadhead flag
        deadhead_pct = (data.deadhead_miles / total_miles) * 100 if total_miles else 0
        if deadhead_pct > 25:
            reasons.append(f"High deadhead {deadhead_pct:.0f}% of total miles")
            if risk == "Green": risk = "Yellow"

        # Target negotiation rate: bring margin to target
        target_margin = a["target_margin_pct"] / 100
        target_rate = round(trip_cost / (1 - target_margin), 0)
        # Minimum acceptable rate = trip_cost * (1 + 8% margin)
        min_rate = round(trip_cost * 1.08, 0)

        # Load score 0-100
        score = 50 + (margin_pct - a["target_margin_pct"]) * 1.5
        score = max(0, min(100, round(score, 0)))

        summary = f"Decision: {decision}. {'; '.join(reasons)}. Target rate ${target_rate:,.0f}, minimum ${min_rate:,.0f}."

        return {
            "total_miles": total_miles,
            "rpm": rpm,
            "fuel_gallons": fuel_gallons,
            "fuel_cost": fuel_cost,
            "driver_pay": driver_pay,
            "tolls": tolls,
            "insurance": insurance,
            "rental": rental,
            "factoring": factoring,
            "trip_cost": round(trip_cost, 2),
            "net_profit": net_profit,
            "margin_pct": margin_pct,
            "profit_per_mile": profit_per_mile,
            "deadhead_pct": round(deadhead_pct, 1),
            "decision": decision,
            "risk": risk,
            "score": int(score),
            "target_rate": target_rate,
            "min_acceptable_rate": min_rate,
            "reasoning": summary,
            "reasons": reasons,
        }

    # ============ COMPLIANCE ============
    def _days_until(iso_str):
        if not iso_str: return None
        try:
            d = datetime.fromisoformat(iso_str.replace("Z","+00:00")) if isinstance(iso_str,str) else iso_str
            if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
            return (d - datetime.now(timezone.utc)).days
        except Exception:
            return None

    @api.get("/compliance")
    async def compliance_overview(user=Depends(get_current_user)):
        scope = tenant_filter(user)
        drivers = await db.drivers.find(scope, {"_id": 0}).to_list(1000)
        trucks = await db.trucks.find(scope, {"_id": 0}).to_list(1000)
        items = []

        for d in drivers:
            blockers = []; warns = []
            cdl_days = _days_until(d.get("cdl_expiry"))
            med_days = _days_until(d.get("medical_expiry"))
            if cdl_days is not None and cdl_days < 0: blockers.append(f"CDL expired {abs(cdl_days)}d ago")
            elif cdl_days is not None and cdl_days < 30: warns.append(f"CDL expires in {cdl_days}d")
            if med_days is not None and med_days < 0: blockers.append(f"Medical card expired {abs(med_days)}d ago")
            elif med_days is not None and med_days < 30: warns.append(f"Medical expires in {med_days}d")
            if d.get("clearinghouse_status") == "Issue": blockers.append("Clearinghouse issue")
            elif d.get("clearinghouse_status") == "Pending": warns.append("Clearinghouse pending")
            if d.get("mvr_status") == "Expired": blockers.append("MVR expired")
            elif d.get("mvr_status") == "Review": warns.append("MVR review")
            if d.get("employment_verification") == "Pending": warns.append("Employment verification pending")

            status = "Red" if blockers else ("Yellow" if warns else "Green")
            items.append({
                "entity_type": "Driver", "entity_id": d["id"], "entity_name": d["name"],
                "status": status, "blockers": blockers, "warnings": warns,
                "dispatch_allowed": not blockers,
                "details": {
                    "cdl_expiry": d.get("cdl_expiry"), "cdl_days": cdl_days,
                    "medical_expiry": d.get("medical_expiry"), "medical_days": med_days,
                    "mvr_status": d.get("mvr_status"),
                    "clearinghouse_status": d.get("clearinghouse_status"),
                    "employment_verification": d.get("employment_verification"),
                }
            })

        for t in trucks:
            blockers = []; warns = []
            ins_days = _days_until(t.get("insurance_expiry"))
            reg_days = _days_until(t.get("registration_expiry"))
            insp_days = _days_until(t.get("annual_inspection_expiry"))
            if ins_days is not None and ins_days < 0: blockers.append(f"Insurance expired {abs(ins_days)}d ago")
            elif ins_days is not None and ins_days < 30: warns.append(f"Insurance expires in {ins_days}d")
            if reg_days is not None and reg_days < 0: blockers.append(f"Registration expired {abs(reg_days)}d ago")
            elif reg_days is not None and reg_days < 30: warns.append(f"Registration expires in {reg_days}d")
            if insp_days is not None and insp_days < 0: blockers.append(f"Annual inspection expired {abs(insp_days)}d ago")
            elif insp_days is not None and insp_days < 45: warns.append(f"Annual inspection expires in {insp_days}d")
            if t.get("maintenance_status") == "Bad": blockers.append("Maintenance blocker")
            elif t.get("maintenance_status") == "Warn": warns.append("Maintenance attention")

            status = "Red" if blockers else ("Yellow" if warns else "Green")
            items.append({
                "entity_type": "Truck", "entity_id": t["id"], "entity_name": t["truck_number"],
                "status": status, "blockers": blockers, "warnings": warns,
                "dispatch_allowed": not blockers,
                "details": {
                    "insurance_expiry": t.get("insurance_expiry"), "insurance_days": ins_days,
                    "registration_expiry": t.get("registration_expiry"), "registration_days": reg_days,
                    "inspection_expiry": t.get("annual_inspection_expiry"), "inspection_days": insp_days,
                    "maintenance_status": t.get("maintenance_status"),
                }
            })

        summary = {
            "total": len(items),
            "green": sum(1 for i in items if i["status"]=="Green"),
            "yellow": sum(1 for i in items if i["status"]=="Yellow"),
            "red": sum(1 for i in items if i["status"]=="Red"),
            "dispatch_blocked": sum(1 for i in items if not i["dispatch_allowed"]),
        }
        return {"summary": summary, "items": items}

