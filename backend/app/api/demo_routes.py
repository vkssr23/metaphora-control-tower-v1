from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import StreamingResponse
import os, logging, uuid, bcrypt, random, math, asyncio, re
from importlib import import_module
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


def register_demo_routes(api, get_current_user, operational_write, ai_access, owner_only, enforce_seed_config, emergent_llm_key):
    EMERGENT_LLM_KEY = emergent_llm_key
    # ============ MODELS ============
    class InternalSeedTruck(BaseModel):
        id: str = Field(default_factory=lambda: new_id("T"))
        truck_number: str
        vin: str = ""
        plate: str = ""
        make: str = ""
        model: str = ""
        year: int = 2022
        status: str = "Available"
        current_location: str = ""
        assigned_driver_id: Optional[str] = None
        samsara_id: str = ""
        eld_status: str = "Active"
        insurance_expiry: str = ""
        registration_expiry: str = ""
        maintenance_status: str = "Good"
        weekly_revenue: float = 0
        weekly_miles: float = 0
        fuel_cost: float = 0
        maintenance_cost: float = 0
        idle_hours: float = 0
        utilization: float = 0
        profit_per_mile: float = 0
        created_at: str = Field(default_factory=now_iso)

    class InternalSeedDriver(BaseModel):
        id: str = Field(default_factory=lambda: new_id("D"))
        name: str
        phone: str = ""
        email: str = ""
        cdl_number: str = ""
        pay_type: str = "CPM"
        cents_per_mile: float = 0.55
        flat_weekly_pay: float = 0
        solo_team: str = "Solo"
        assigned_truck_id: Optional[str] = None
        status: str = "Available"
        current_location: str = ""
        weekly_miles: float = 0
        weekly_revenue: float = 0
        on_time_pickup_pct: float = 95
        on_time_delivery_pct: float = 93
        missed_updates: int = 0
        late_deliveries: int = 0
        safety_issues: int = 0
        score: float = 85
        created_at: str = Field(default_factory=now_iso)

    STAGES = [
        "Booked", "Assigned", "Dispatched", "Pickup Started", "Arrived Pickup",
        "Loaded", "In Transit", "Arrived Delivery", "Delivered",
        "Docs Pending", "Invoice Pending", "Payment Pending", "Closed", "Exception"
    ]

    class InternalSeedLoad(BaseModel):
        id: str = Field(default_factory=lambda: new_id("L"))
        customer: str
        broker: str = ""
        rate_con_number: str = ""
        pickup_address: str
        pickup_city: str = ""
        pickup_state: str = ""
        pickup_zip: str = ""
        pickup_appt: str = ""
        delivery_address: str
        delivery_city: str = ""
        delivery_state: str = ""
        delivery_zip: str = ""
        delivery_appt: str = ""
        miles: float = 0
        est_drive_hours: float = 0
        rate: float = 0
        rpm: float = 0
        truck_id: Optional[str] = None
        driver_id: Optional[str] = None
        dispatcher: str = ""
        stage: str = "Booked"
        risk: str = "Low"  # Low / Medium / High / Critical
        eta: str = ""
        notes: str = ""
        bol_status: str = "Pending"
        pod_status: str = "Pending"
        invoice_status: str = "Not Ready"
        payment_status: str = "Pending"
        fuel_cost: float = 0
        tolls: float = 0
        lumper: float = 0
        driver_pay: float = 0
        factoring_fee: float = 0
        other_expenses: float = 0
        created_at: str = Field(default_factory=now_iso)
        updated_at: str = Field(default_factory=now_iso)

    class InternalSeedInvoice(BaseModel):
        id: str = Field(default_factory=lambda: new_id("INV"))
        load_id: str
        customer: str = ""
        amount: float = 0
        status: str = "Not Ready"
        due_date: str = ""
        paid_date: str = ""
        created_at: str = Field(default_factory=now_iso)


    # ============ PLACEHOLDER INTEGRATION FUNCTIONS ============
    @api.post("/routing/calc")
    async def calc_route(data: RouteCalculationRequest, user=Depends(operational_write)):
        """Mock Google Maps route mileage."""
        pickup = data.pickup; delivery = data.delivery
        seed = (hash(pickup + delivery) & 0x7fffffff) or 1
        random.seed(seed)
        miles = round(random.uniform(180, 1400), 0)
        hours = round(miles / random.uniform(48, 58), 1)
        return {
            "pickup": pickup, "delivery": delivery,
            "miles": miles, "drive_hours": hours,
            "route_summary": f"I-{random.choice([80,40,10,70,90])} corridor via {random.choice(['Kansas City','Denver','Nashville','Atlanta','Dallas'])}",
            "risk": random.choice(["Low","Low","Medium","Medium","High"]),
            "gmaps_link": f"https://www.google.com/maps/dir/{pickup.replace(' ','+')}/{delivery.replace(' ','+')}"
        }

    @api.post("/weather/check")
    async def weather_check(data: WeatherCheckRequest, user=Depends(operational_write)):
        random.seed(hash(str(data.model_dump())) & 0x7fffffff)
        levels = ["Low","Medium","High","Critical"]
        return {
            "pickup": {"temp_f": random.randint(20,90), "rain": random.choice(levels), "wind": random.choice(levels), "visibility": random.choice(levels)},
            "delivery": {"temp_f": random.randint(20,90), "rain": random.choice(levels), "snow": random.choice(levels[:3]), "storm_alert": random.choice([False,False,True])},
            "route": {"overall_risk": random.choice(levels), "advisory": "Heavy rain expected between mile 220-340. Reduce speed.", "eta_impact_minutes": random.randint(0, 90)},
        }

    @api.post("/roads/check")
    async def roads_check(data: LoadIdRequest, user=Depends(operational_write)):
        await require_tenant_reference(db.loads, user, data.load_id, "load")
        random.seed(hash(str(data.model_dump())+"r") & 0x7fffffff)
        return {
            "traffic_delay_min": random.randint(0, 45),
            "accident_risk": random.choice(["Low","Medium","High"]),
            "closure_alert": random.choice([None, "Lane closure I-40 EB near Amarillo TX", "Construction I-70 WB Denver"]),
            "construction": random.choice([True, False]),
            "reroute_suggestion": random.choice([None, "Via US-287", "Via I-44"]),
            "eta_impact_minutes": random.randint(0, 60),
        }

    @api.post("/samsara/vehicle")
    async def samsara_vehicle(data: SamsaraVehicleRequest, user=Depends(operational_write)):
        identifier = {"id": data.truck_id} if data.truck_id is not None else {"samsara_id": data.vehicle_id}
        truck = await safe_db(db.trucks.find_one(tenant_filter(user, identifier), {"_id": 0}), "Samsara truck lookup")
        if not truck:
            raise HTTPException(404, "Not found")
        vid = truck.get("samsara_id") or f"simulated:{truck['id']}"
        random.seed(hash(vid) & 0x7fffffff)
        return {
            "simulated": True,
            "truck_id": truck["id"],
            "vehicle_id": vid,
            "location": f"{random.choice(['Amarillo TX','OKC OK','Little Rock AR','Nashville TN','Flagstaff AZ'])}",
            "engine": random.choice(["ON","ON","OFF"]),
            "speed_mph": random.randint(0, 68),
            "idle_minutes": random.randint(0, 45),
            "odometer": random.randint(120000, 480000),
            "fuel_pct": random.randint(15, 90),
            "hos_remaining_hours": round(random.uniform(1.5, 10.5), 1),
            "duty_status": random.choice(["Driving","On Duty","Off Duty","Sleeper"]),
            "harsh_events": random.randint(0, 3),
            "last_sync": now_iso(),
        }

    @api.post("/fuel/plan")
    async def fuel_plan(data: LoadIdRequest, user=Depends(operational_write)):
        await require_tenant_reference(db.loads, user, data.load_id, "load")
        random.seed(hash(str(data.model_dump())+"f") & 0x7fffffff)
        stops = ["Loves","Pilot","TA","Flying J","Sapp Bros","Petro"]
        return {
            "fuel_level_pct": random.randint(20, 60),
            "miles_remaining": random.randint(220, 700),
            "recommended_stop": {
                "name": random.choice(stops),
                "address": f"{random.randint(100,999)} I-{random.choice([40,10,70,80])} Exit {random.randint(100,400)}",
                "distance_miles": random.randint(30, 180),
                "price_per_gallon": round(random.uniform(3.4, 4.6), 2),
                "parking_available": random.choice([True, True, False]),
            },
            "estimated_gallons": random.randint(80, 180),
        }

    @api.post("/truckstops/plan")
    async def truckstop_plan(data: LoadIdRequest, user=Depends(operational_write)):
        await require_tenant_reference(db.loads, user, data.load_id, "load")
        random.seed(hash(str(data.model_dump())+"ts") & 0x7fffffff)
        return {
            "name": random.choice(["Loves 344","Pilot 208","TA Ontario","Sapp Bros"]),
            "distance_miles": random.randint(40, 200),
            "parking_available": random.choice([True, False]),
            "amenities": random.sample(["Showers","Food","Laundry","Wifi","ATM"], 3),
            "eta_arrival": (datetime.now(timezone.utc)+timedelta(hours=random.uniform(1,6))).isoformat(),
        }

    @api.post("/alerts/generate")
    async def generate_alert(a: DriverAlertRequest, user=Depends(operational_write)):
        load = await safe_db(db.loads.find_one(tenant_filter(user, {"id": a.load_id}), {"_id": 0}), "alert load lookup")
        if not load: raise HTTPException(404, "Not found")
        driver = None; truck = None
        if load:
            if load.get("driver_id"):
                driver = await safe_db(db.drivers.find_one(tenant_filter(user, {"id": load["driver_id"]}), {"_id": 0}), "alert driver lookup")
            if load.get("truck_id"):
                truck = await safe_db(db.trucks.find_one(tenant_filter(user, {"id": load["truck_id"]}), {"_id": 0}), "alert truck lookup")
        alert_id = new_id("ALT")
        audit = await begin_audit(db.audit_events, user, "alert.generated", AuditEntityType.ALERT, alert_id,
                                  changed_fields=["load_id", "alert_type"], previous={"load_id": a.load_id})
        msg = f"""DRIVER ALERT
    Load ID: {a.load_id}
    Driver: {driver['name'] if driver else 'Unassigned'}
    Truck: {truck['truck_number'] if truck else 'Unassigned'}
    Type: {a.alert_type.upper()}
    Current: {load.get('stage','') if load else ''}
    Route: {load.get('pickup_city','') if load else ''} → {load.get('delivery_city','') if load else ''}
    Issue: {a.message}
    ETA: {load.get('eta','TBD') if load else 'TBD'}
    Next update required by: {(datetime.now(timezone.utc)+timedelta(hours=2)).strftime('%H:%M UTC')}
    Dispatcher: {user.get('name', user['id'])}"""
        await audit.succeeded({"load_id": a.load_id, "alert_type": a.alert_type.value})
        return {"message": msg}

    # ============ AI ASSISTANT (Claude Sonnet) ============
    @api.post("/ai/chat")
    async def ai_chat(data: AiChatRequest, user=Depends(ai_access)):
        try:
            provider = import_module("emergentintegrations.llm.chat")
        except ModuleNotFoundError:
            raise HTTPException(503, "LEGACY_AI_PROVIDER_UNAVAILABLE")
        provider_key = EMERGENT_LLM_KEY or os.environ.get("EMERGENT_LLM_KEY", "")
        if not provider_key:
            raise HTTPException(503, "LEGACY_AI_PROVIDER_UNAVAILABLE")
        LlmChat = provider.LlmChat
        UserMessage = provider.UserMessage
        TextDelta = provider.TextDelta
        StreamDone = provider.StreamDone
        # Gather live data context
        scope = tenant_filter(user)
        loads = await safe_db(db.loads.find(scope, {"_id": 0}).to_list(200), "AI load context")
        trucks = await safe_db(db.trucks.find(scope, {"_id": 0}).to_list(200), "AI truck context")
        drivers = await safe_db(db.drivers.find(scope, {"_id": 0}).to_list(200), "AI driver context")
        invoices = await safe_db(db.invoices.find(scope, {"_id": 0}).to_list(200), "AI invoice context")
        context = f"""Live business data snapshot (JSON):
    LOADS ({len(loads)}): {loads[:20]}
    TRUCKS ({len(trucks)}): {trucks[:15]}
    DRIVERS ({len(drivers)}): {drivers[:15]}
    INVOICES ({len(invoices)}): {invoices[:15]}
    Answer as the Metaphora Control Tower operations assistant for a USA trucking carrier. Be crisp, use bullet points, cite Load IDs, driver names, and truck numbers. Focus on decisions and next actions."""

        async def stream():
            try:
                chat = LlmChat(
                    api_key=provider_key,
                    session_id=data.session_id,
                    system_message=context,
                ).with_model("anthropic", "claude-sonnet-4-6")
                async for ev in chat.stream_message(UserMessage(text=data.message)):
                    if isinstance(ev, TextDelta):
                        yield ev.content
                    elif isinstance(ev, StreamDone):
                        break
            except Exception:
                logger.error("AI provider request failed")
                yield "[AI unavailable]\n\nFalling back to rule-based analysis:\n"
                yield rule_based_answer(data.message, loads, trucks, drivers, invoices)

        return StreamingResponse(stream(), media_type="text/plain",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def rule_based_answer(q, loads, trucks, drivers, invoices):
        q = q.lower()
        if "risk" in q or "delay" in q:
            risky = [l for l in loads if l.get("risk") in ("High","Critical")]
            return "At-risk loads:\n" + "\n".join(f"• {l['id']} — {l['pickup_city']}→{l['delivery_city']} ({l.get('risk')})" for l in risky[:10])
        if "profitable" in q or "profit" in q:
            s = sorted(trucks, key=lambda t: t.get("profit_per_mile", 0), reverse=True)
            return "Most profitable trucks (PPM):\n" + "\n".join(f"• {t['truck_number']} — ${t.get('profit_per_mile',0):.2f}/mi" for t in s[:5])
        if "invoice" in q or "pending" in q:
            pending = [i for i in invoices if i.get("status") not in ("Paid","Closed")]
            total = sum(i.get("amount",0) for i in pending)
            return f"Pending invoices: {len(pending)} totaling ${total:,.2f}"
        if "idle" in q:
            idle = [t for t in trucks if t.get("status")=="Idle" or t.get("idle_hours",0)>10]
            return "Idle trucks:\n" + "\n".join(f"• {t['truck_number']} — {t.get('idle_hours',0)}h idle" for t in idle[:10])
        return "I couldn't parse that. Try: 'Which loads are at risk?', 'Which trucks are most profitable?', 'Pending invoices?', 'Idle trucks?'"


    # ============ SEED ============
    def enforce_seed_config(force: bool) -> None:
        """Validate all configuration gates before seed reads or writes begin."""
        if not settings.allow_seed_endpoint:
            raise HTTPException(403, "Seed endpoint is disabled")
        if force and not force_seed_allowed(settings.app_env):
            raise HTTPException(403, "Forced seed is disabled in this environment")


    @api.post("/seed")
    async def seed(force: bool = False, user=Depends(owner_only)):
        enforce_seed_config(force)
        scope = tenant_filter(user)
        if not force:
            c = await db.loads.count_documents(scope)
            if c > 0:
                return {"ok": True, "already_seeded": True, "count": c}
        audit = await begin_audit(db.audit_events, user, "seed.executed", AuditEntityType.SEED,
                                  require_tenant_id(user), changed_fields=["force"],
                                  source=AuditSource.SEED)
        await db.loads.delete_many(scope); await db.trucks.delete_many(scope)
        await db.drivers.delete_many(scope)
        await db.invoices.delete_many(scope); await db.documents.delete_many(scope)

        # Users are NOT pre-seeded. Every user must self-register via /api/auth/signup.

        # Trucks
        makes = ["Freightliner Cascadia","Peterbilt 579","Kenworth T680","Volvo VNL"]
        truck_docs = []
        for i in range(8):
            # Varied expiry dates for realistic compliance data
            ins_days = random.choice([-5, 15, 45, 120, 200, 300])
            reg_days = random.choice([10, 25, 60, 150, 250])
            insp_days = random.choice([-2, 20, 40, 90, 180])
            t = InternalSeedTruck(
                truck_number=f"TRK-{100+i}",
                vin=f"1HGBH41JXMN{100000+i}",
                plate=f"USA-{2000+i}",
                make=makes[i%len(makes)].split()[0], model=makes[i%len(makes)].split()[1],
                year=2019 + (i%5),
                status=random.choice(["Available","Assigned","In Transit","Idle","At Pickup"]),
                current_location=random.choice(["Dallas TX","Atlanta GA","OKC OK","Denver CO","Nashville TN","Phoenix AZ","Chicago IL","Memphis TN"]),
                samsara_id=f"VEH{100+i}",
                insurance_expiry=(datetime.now(timezone.utc)+timedelta(days=ins_days)).isoformat(),
                registration_expiry=(datetime.now(timezone.utc)+timedelta(days=reg_days)).isoformat(),
                maintenance_status=random.choice(["Good","Good","Warn","Good"]),
                weekly_revenue=round(random.uniform(4500, 9500),0),
                weekly_miles=round(random.uniform(2200, 3400),0),
                fuel_cost=round(random.uniform(900, 1600),0),
                maintenance_cost=round(random.uniform(0, 800),0),
                idle_hours=round(random.uniform(2, 18),1),
                utilization=round(random.uniform(60, 95),0),
                profit_per_mile=round(random.uniform(0.35, 0.95),2),
            ).model_dump()
            t["annual_inspection_expiry"] = (datetime.now(timezone.utc)+timedelta(days=insp_days)).isoformat()
            truck_docs.append(tenant_document(user, t))
        await db.trucks.insert_many(truck_docs)

        # Drivers
        first = ["Mike","Carlos","James","Robert","David","Chris","Anthony","Steven","Kevin","Brian"]
        last  = ["Johnson","Rodriguez","Smith","Brown","Davis","Miller","Wilson","Moore","Taylor","Anderson"]
        driver_docs = []
        for i in range(10):
            cdl_days = random.choice([-3, 20, 45, 120, 220, 400])
            med_days = random.choice([-1, 15, 35, 90, 180])
            d = InternalSeedDriver(
                name=f"{first[i]} {last[i]}",
                phone=f"+1-{random.randint(200,999)}-{random.randint(200,999)}-{random.randint(1000,9999)}",
                email=f"{first[i].lower()}.{last[i].lower()}@dispatch.com",
                cdl_number=f"CDL{random.randint(1000000,9999999)}",
                pay_type=random.choice(["CPM","Flat"]),
                cents_per_mile=round(random.uniform(0.50,0.68),2),
                flat_weekly_pay=random.choice([0,1200,1400]),
                assigned_truck_id=truck_docs[i % 8]["id"] if i < 8 else None,
                status=random.choice(["Available","Driving","Assigned","Off Duty","Missing Update"]),
                current_location=truck_docs[i%8]["current_location"] if i < 8 else "Home",
                weekly_miles=round(random.uniform(1800,3400),0),
                weekly_revenue=round(random.uniform(4200,9000),0),
                on_time_pickup_pct=round(random.uniform(75,99),1),
                on_time_delivery_pct=round(random.uniform(72,99),1),
                missed_updates=random.randint(0,3),
                late_deliveries=random.randint(0,4),
                safety_issues=random.randint(0,2),
                score=round(random.uniform(65,98),0),
            ).model_dump()
            # Compliance fields
            d["cdl_state"] = random.choice(["TX","CA","FL","GA","IL","OH","NC","AZ"])
            d["cdl_expiry"] = (datetime.now(timezone.utc)+timedelta(days=cdl_days)).isoformat()
            d["medical_expiry"] = (datetime.now(timezone.utc)+timedelta(days=med_days)).isoformat()
            d["mvr_status"] = random.choice(["Clear","Clear","Clear","Review","Expired"])
            d["clearinghouse_status"] = random.choice(["Clear","Clear","Pending","Clear","Issue"])
            d["employment_verification"] = random.choice(["Complete","Complete","Pending"])
            d["driver_type"] = random.choice(["Solo","Solo","Team"])
            driver_docs.append(tenant_document(user, d))
        await db.drivers.insert_many(driver_docs)

        # Loads
        cities = [("Dallas","TX","75201"),("Atlanta","GA","30301"),("Chicago","IL","60601"),("Los Angeles","CA","90001"),
                  ("Phoenix","AZ","85001"),("Miami","FL","33101"),("Denver","CO","80201"),("Nashville","TN","37201"),
                  ("Memphis","TN","38101"),("Houston","TX","77001"),("Charlotte","NC","28201"),("Seattle","WA","98101")]
        brokers = ["CH Robinson","TQL","Landstar","Coyote","Uber Freight","Convoy","DAT","Amazon Freight"]
        customers = ["Walmart","Amazon","Home Depot","Target","Costco","FedEx Ground","UPS","Kroger"]
        stages_dist = ["Booked","Booked","Assigned","Dispatched","Pickup Started","Arrived Pickup",
                       "Loaded","In Transit","In Transit","In Transit","Arrived Delivery","Delivered",
                       "Docs Pending","Invoice Pending","Payment Pending"]
        load_docs = []
        for i in range(15):
            p = random.choice(cities); dv = random.choice([c for c in cities if c != p])
            rate = round(random.uniform(1800, 6800), 0)
            miles = round(random.uniform(320, 1650), 0)
            stg = stages_dist[i]
            risk = random.choice(["Low","Low","Low","Medium","Medium","High","Critical"])
            pickup_dt = datetime.now(timezone.utc) + timedelta(days=random.randint(-3,4))
            delivery_dt = pickup_dt + timedelta(days=random.randint(1,4))
            assigned = stg not in ("Booked",)
            t_idx = i % 8; d_idx = i % 10
            l = InternalSeedLoad(
                customer=random.choice(customers), broker=random.choice(brokers),
                rate_con_number=f"RC{random.randint(100000,999999)}",
                pickup_address=f"{random.randint(100,9999)} Warehouse Dr, {p[0]}, {p[1]} {p[2]}",
                pickup_city=p[0], pickup_state=p[1], pickup_zip=p[2],
                pickup_appt=pickup_dt.isoformat(),
                delivery_address=f"{random.randint(100,9999)} DC Blvd, {dv[0]}, {dv[1]} {dv[2]}",
                delivery_city=dv[0], delivery_state=dv[1], delivery_zip=dv[2],
                delivery_appt=delivery_dt.isoformat(),
                miles=miles, est_drive_hours=round(miles/55, 1), rate=rate, rpm=round(rate/miles,2),
                truck_id=truck_docs[t_idx]["id"] if assigned else None,
                driver_id=driver_docs[d_idx]["id"] if assigned else None,
                dispatcher=random.choice(["Maria Dispatch","Alex Kim","Priya S."]),
                stage=stg, risk=risk,
                eta=delivery_dt.isoformat(),
                bol_status="Received" if stg in ("Loaded","In Transit","Arrived Delivery","Delivered","Docs Pending","Invoice Pending","Payment Pending","Closed") else "Pending",
                pod_status="Received" if stg in ("Delivered","Invoice Pending","Payment Pending","Closed") else "Pending",
                invoice_status="Payment Pending" if stg=="Payment Pending" else ("Ready to Invoice" if stg=="Invoice Pending" else ("Docs Pending" if stg=="Docs Pending" else "Not Ready")),
                payment_status="Pending",
                fuel_cost=round(miles*0.55, 0), tolls=round(random.uniform(0,120),0),
                lumper=random.choice([0,0,150,250]), driver_pay=round(miles*driver_docs[d_idx]["cents_per_mile"],0),
                factoring_fee=round(rate*0.03,0), other_expenses=round(random.uniform(0,120),0),
            ).model_dump()
            load_docs.append(tenant_document(user, l))
        await db.loads.insert_many(load_docs)

        # Invoices for loads at invoice stage or beyond
        inv_docs = []
        for l in load_docs:
            if l["stage"] in ("Invoice Pending","Payment Pending","Docs Pending"):
                inv_docs.append(tenant_document(user, InternalSeedInvoice(
                    load_id=l["id"], customer=l["customer"], amount=l["rate"],
                    status=l["invoice_status"], due_date=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()
                ).model_dump()))
        if inv_docs: await db.invoices.insert_many(inv_docs)

        await audit.succeeded({"force": force, "count": len(load_docs)})
        return {"ok": True, "loads": len(load_docs), "trucks": len(truck_docs), "drivers": len(driver_docs), "invoices": len(inv_docs)}

    return {"ai_chat": ai_chat}

