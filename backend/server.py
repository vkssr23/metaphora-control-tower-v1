"""AI Dispatch.RR - Trucking TMS Backend"""
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os, logging, uuid, jwt, bcrypt, random, math, asyncio
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_SECRET = os.environ.get('JWT_SECRET', 'dev_secret')
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')

app = FastAPI(title="AI Dispatch.RR")
api = APIRouter(prefix="/api")

# ============ UTILITIES ============
def now_iso():
    return datetime.now(timezone.utc).isoformat()

def new_id(prefix=""):
    return f"{prefix}{uuid.uuid4().hex[:8].upper()}"

def clean_doc(d):
    if d and '_id' in d:
        d.pop('_id', None)
    return d

# ============ AUTH ============
class LoginIn(BaseModel):
    email: str
    password: str

class SignupIn(BaseModel):
    email: str
    password: str
    name: str
    role: str = "dispatcher"

def create_token(user):
    payload = {
        "id": user["id"], "email": user["email"], "role": user["role"], "name": user["name"],
        "exp": datetime.now(timezone.utc) + timedelta(days=30)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

async def get_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    try:
        payload = jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
        return payload
    except Exception:
        raise HTTPException(401, "Invalid token")

@api.post("/auth/signup")
async def signup(data: SignupIn):
    existing = await db.users.find_one({"email": data.email})
    if existing:
        raise HTTPException(400, "Email exists")
    user = {
        "id": new_id("U"), "email": data.email, "name": data.name, "role": data.role,
        "password": bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(),
        "created_at": now_iso()
    }
    await db.users.insert_one(user)
    user.pop("password"); clean_doc(user)
    return {"token": create_token(user), "user": user}

@api.post("/auth/login")
async def login(data: LoginIn):
    user = await db.users.find_one({"email": data.email})
    if not user or not bcrypt.checkpw(data.password.encode(), user["password"].encode()):
        raise HTTPException(401, "Invalid credentials")
    clean_doc(user); user.pop("password", None)
    return {"token": create_token(user), "user": user}

@api.get("/auth/me")
async def me(user=Depends(get_user)):
    return user

# ============ MODELS ============
class Truck(BaseModel):
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

class Driver(BaseModel):
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

class Load(BaseModel):
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

# ============ TRUCKS ============
@api.get("/trucks")
async def list_trucks():
    docs = await db.trucks.find({}, {"_id": 0}).to_list(1000)
    return docs

@api.post("/trucks")
async def create_truck(t: Truck):
    d = t.model_dump()
    await db.trucks.insert_one(d); clean_doc(d)
    return d

@api.put("/trucks/{tid}")
async def update_truck(tid: str, data: dict):
    await db.trucks.update_one({"id": tid}, {"$set": data})
    return {"ok": True}

@api.delete("/trucks/{tid}")
async def delete_truck(tid: str):
    await db.trucks.delete_one({"id": tid}); return {"ok": True}

# ============ DRIVERS ============
@api.get("/drivers")
async def list_drivers():
    return await db.drivers.find({}, {"_id": 0}).to_list(1000)

@api.post("/drivers")
async def create_driver(d: Driver):
    doc = d.model_dump(); await db.drivers.insert_one(doc); clean_doc(doc)
    return doc

@api.put("/drivers/{did}")
async def update_driver(did: str, data: dict):
    await db.drivers.update_one({"id": did}, {"$set": data}); return {"ok": True}

@api.delete("/drivers/{did}")
async def delete_driver(did: str):
    await db.drivers.delete_one({"id": did}); return {"ok": True}

# ============ LOADS ============
@api.get("/loads")
async def list_loads():
    return await db.loads.find({}, {"_id": 0}).to_list(2000)

@api.get("/loads/{lid}")
async def get_load(lid: str):
    l = await db.loads.find_one({"id": lid}, {"_id": 0})
    if not l: raise HTTPException(404, "Not found")
    return l

@api.post("/loads")
async def create_load(l: Load):
    d = l.model_dump()
    if d["miles"] and d["rate"]:
        d["rpm"] = round(d["rate"] / d["miles"], 2)
    await db.loads.insert_one(d); clean_doc(d)
    await log_activity(d["id"], "Load Created", "", "Booked", d.get("dispatcher","system"), "Load created")
    return d

@api.put("/loads/{lid}")
async def update_load(lid: str, data: dict):
    data["updated_at"] = now_iso()
    if data.get("miles") and data.get("rate"):
        data["rpm"] = round(data["rate"] / data["miles"], 2)
    await db.loads.update_one({"id": lid}, {"$set": data})
    return {"ok": True}

@api.delete("/loads/{lid}")
async def delete_load(lid: str):
    await db.loads.delete_one({"id": lid}); return {"ok": True}

class StageChange(BaseModel):
    stage: str
    updated_by: str = "system"
    notes: str = ""

@api.post("/loads/{lid}/stage")
async def change_stage(lid: str, data: StageChange):
    load = await db.loads.find_one({"id": lid}, {"_id": 0})
    if not load: raise HTTPException(404, "Not found")
    old = load.get("stage", "")
    updates = {"stage": data.stage, "updated_at": now_iso()}
    # Auto-update related statuses
    if data.stage == "Loaded": updates["bol_status"] = "Received"
    if data.stage == "Delivered": updates["pod_status"] = "Pending"
    if data.stage == "Docs Pending": updates["invoice_status"] = "Docs Pending"
    if data.stage == "Invoice Pending": updates["invoice_status"] = "Ready to Invoice"
    if data.stage == "Payment Pending": updates["invoice_status"] = "Payment Pending"
    if data.stage == "Closed": updates["payment_status"] = "Paid"; updates["invoice_status"] = "Paid"
    await db.loads.update_one({"id": lid}, {"$set": updates})
    await log_activity(lid, "Stage Change", old, data.stage, data.updated_by, data.notes)
    return {"ok": True, "stage": data.stage}

# ============ ACTIVITY LOG ============
async def log_activity(load_id, action, old, new, user, notes=""):
    entry = {
        "id": new_id("A"), "load_id": load_id, "action": action,
        "old_status": old, "new_status": new,
        "updated_by": user, "timestamp": now_iso(), "notes": notes
    }
    await db.activity.insert_one(entry)

@api.get("/activity")
async def list_activity(load_id: Optional[str] = None):
    q = {"load_id": load_id} if load_id else {}
    return await db.activity.find(q, {"_id": 0}).sort("timestamp", -1).to_list(500)

# ============ DOCUMENTS ============
class Document(BaseModel):
    id: str = Field(default_factory=lambda: new_id("DOC"))
    load_id: str
    doc_type: str  # rate_con, bol, pod, lumper, scale, invoice, other
    filename: str = ""
    url: str = ""
    uploaded_by: str = ""
    uploaded_at: str = Field(default_factory=now_iso)
    notes: str = ""

@api.get("/documents")
async def list_docs(load_id: Optional[str] = None):
    q = {"load_id": load_id} if load_id else {}
    return await db.documents.find(q, {"_id": 0}).to_list(1000)

@api.post("/documents")
async def create_doc(d: Document):
    doc = d.model_dump(); await db.documents.insert_one(doc); clean_doc(doc)
    await log_activity(d.load_id, f"Uploaded {d.doc_type}", "", "", d.uploaded_by, d.filename)
    return doc

# ============ INVOICES ============
class Invoice(BaseModel):
    id: str = Field(default_factory=lambda: new_id("INV"))
    load_id: str
    customer: str = ""
    amount: float = 0
    status: str = "Not Ready"
    due_date: str = ""
    paid_date: str = ""
    dispute: bool = False
    notes: str = ""
    created_at: str = Field(default_factory=now_iso)

@api.get("/invoices")
async def list_invoices():
    return await db.invoices.find({}, {"_id": 0}).to_list(1000)

@api.post("/invoices")
async def create_invoice(inv: Invoice):
    doc = inv.model_dump(); await db.invoices.insert_one(doc); clean_doc(doc)
    return doc

@api.put("/invoices/{iid}")
async def update_invoice(iid: str, data: dict):
    await db.invoices.update_one({"id": iid}, {"$set": data}); return {"ok": True}

# ============ PLACEHOLDER INTEGRATION FUNCTIONS ============
@api.post("/routing/calc")
async def calc_route(data: dict):
    """Mock Google Maps route mileage."""
    pickup = data.get("pickup", ""); delivery = data.get("delivery", "")
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
async def weather_check(data: dict):
    random.seed(hash(str(data)) & 0x7fffffff)
    levels = ["Low","Medium","High","Critical"]
    return {
        "pickup": {"temp_f": random.randint(20,90), "rain": random.choice(levels), "wind": random.choice(levels), "visibility": random.choice(levels)},
        "delivery": {"temp_f": random.randint(20,90), "rain": random.choice(levels), "snow": random.choice(levels[:3]), "storm_alert": random.choice([False,False,True])},
        "route": {"overall_risk": random.choice(levels), "advisory": "Heavy rain expected between mile 220-340. Reduce speed.", "eta_impact_minutes": random.randint(0, 90)},
    }

@api.post("/roads/check")
async def roads_check(data: dict):
    random.seed(hash(str(data)+"r") & 0x7fffffff)
    return {
        "traffic_delay_min": random.randint(0, 45),
        "accident_risk": random.choice(["Low","Medium","High"]),
        "closure_alert": random.choice([None, "Lane closure I-40 EB near Amarillo TX", "Construction I-70 WB Denver"]),
        "construction": random.choice([True, False]),
        "reroute_suggestion": random.choice([None, "Via US-287", "Via I-44"]),
        "eta_impact_minutes": random.randint(0, 60),
    }

@api.post("/samsara/vehicle")
async def samsara_vehicle(data: dict):
    vid = data.get("vehicle_id","VEH000")
    random.seed(hash(vid) & 0x7fffffff)
    return {
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
async def fuel_plan(data: dict):
    random.seed(hash(str(data)+"f") & 0x7fffffff)
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
async def truckstop_plan(data: dict):
    random.seed(hash(str(data)+"ts") & 0x7fffffff)
    return {
        "name": random.choice(["Loves 344","Pilot 208","TA Ontario","Sapp Bros"]),
        "distance_miles": random.randint(40, 200),
        "parking_available": random.choice([True, False]),
        "amenities": random.sample(["Showers","Food","Laundry","Wifi","ATM"], 3),
        "eta_arrival": (datetime.now(timezone.utc)+timedelta(hours=random.uniform(1,6))).isoformat(),
    }

class DriverAlertIn(BaseModel):
    load_id: str
    alert_type: str  # weather, road, fuel, eta, safety
    message: str = ""
    dispatcher: str = "Dispatcher"

@api.post("/alerts/generate")
async def generate_alert(a: DriverAlertIn):
    load = await db.loads.find_one({"id": a.load_id}, {"_id": 0})
    driver = None; truck = None
    if load:
        if load.get("driver_id"):
            driver = await db.drivers.find_one({"id": load["driver_id"]}, {"_id": 0})
        if load.get("truck_id"):
            truck = await db.trucks.find_one({"id": load["truck_id"]}, {"_id": 0})
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
Dispatcher: {a.dispatcher}"""
    await log_activity(a.load_id, "Driver Alert Generated", "", a.alert_type, a.dispatcher, a.message)
    return {"message": msg}

# ============ AI ASSISTANT (Claude Sonnet) ============
class AiChatIn(BaseModel):
    session_id: str = "default"
    message: str

@api.post("/ai/chat")
async def ai_chat(data: AiChatIn):
    # Gather live data context
    loads = await db.loads.find({}, {"_id": 0}).to_list(200)
    trucks = await db.trucks.find({}, {"_id": 0}).to_list(200)
    drivers = await db.drivers.find({}, {"_id": 0}).to_list(200)
    invoices = await db.invoices.find({}, {"_id": 0}).to_list(200)
    context = f"""Live business data snapshot (JSON):
LOADS ({len(loads)}): {loads[:20]}
TRUCKS ({len(trucks)}): {trucks[:15]}
DRIVERS ({len(drivers)}): {drivers[:15]}
INVOICES ({len(invoices)}): {invoices[:15]}
Answer as the AI Dispatch.RR control tower assistant. Be crisp, use bullet points, cite Load IDs, driver names, and truck numbers."""

    async def stream():
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone
            chat = LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=data.session_id,
                system_message=context,
            ).with_model("anthropic", "claude-sonnet-4-6")
            async for ev in chat.stream_message(UserMessage(text=data.message)):
                if isinstance(ev, TextDelta):
                    yield ev.content
                elif isinstance(ev, StreamDone):
                    break
        except Exception as e:
            yield f"[AI Error] {str(e)}\n\nFalling back to rule-based analysis:\n"
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

# ============ DASHBOARD ============
@api.get("/dashboard/stats")
async def dashboard_stats():
    loads = await db.loads.find({}, {"_id": 0}).to_list(2000)
    trucks = await db.trucks.find({}, {"_id": 0}).to_list(1000)
    drivers = await db.drivers.find({}, {"_id": 0}).to_list(1000)
    invoices = await db.invoices.find({}, {"_id": 0}).to_list(2000)

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
async def dashboard_charts():
    loads = await db.loads.find({}, {"_id": 0}).to_list(2000)
    trucks = await db.trucks.find({}, {"_id": 0}).to_list(1000)
    drivers = await db.drivers.find({}, {"_id": 0}).to_list(1000)

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

# ============ SEED ============
@api.post("/seed")
async def seed(force: bool = False):
    if not force:
        c = await db.loads.count_documents({})
        if c > 0:
            return {"ok": True, "already_seeded": True, "count": c}
    await db.loads.delete_many({}); await db.trucks.delete_many({})
    await db.drivers.delete_many({}); await db.activity.delete_many({})
    await db.invoices.delete_many({}); await db.documents.delete_many({})

    # Users
    if await db.users.count_documents({}) == 0:
        users = [
            {"email":"owner@dispatch.com","password":"owner123","name":"John Owner","role":"owner"},
            {"email":"dispatcher@dispatch.com","password":"dispatch123","name":"Maria Dispatch","role":"dispatcher"},
            {"email":"finance@dispatch.com","password":"finance123","name":"Sam Finance","role":"finance"},
        ]
        for u in users:
            doc = {"id": new_id("U"), "email":u["email"], "name":u["name"], "role":u["role"],
                   "password": bcrypt.hashpw(u["password"].encode(), bcrypt.gensalt()).decode(),
                   "created_at": now_iso()}
            await db.users.insert_one(doc)

    # Trucks
    makes = ["Freightliner Cascadia","Peterbilt 579","Kenworth T680","Volvo VNL"]
    truck_docs = []
    for i in range(8):
        t = Truck(
            truck_number=f"TRK-{100+i}",
            vin=f"1HGBH41JXMN{100000+i}",
            plate=f"USA-{2000+i}",
            make=makes[i%len(makes)].split()[0], model=makes[i%len(makes)].split()[1],
            year=2019 + (i%5),
            status=random.choice(["Available","Assigned","In Transit","Idle","At Pickup"]),
            current_location=random.choice(["Dallas TX","Atlanta GA","OKC OK","Denver CO","Nashville TN","Phoenix AZ","Chicago IL","Memphis TN"]),
            samsara_id=f"VEH{100+i}",
            insurance_expiry="2026-12-31", registration_expiry="2026-08-15",
            weekly_revenue=round(random.uniform(4500, 9500),0),
            weekly_miles=round(random.uniform(2200, 3400),0),
            fuel_cost=round(random.uniform(900, 1600),0),
            maintenance_cost=round(random.uniform(0, 800),0),
            idle_hours=round(random.uniform(2, 18),1),
            utilization=round(random.uniform(60, 95),0),
            profit_per_mile=round(random.uniform(0.35, 0.95),2),
        ).model_dump()
        truck_docs.append(t)
    await db.trucks.insert_many(truck_docs)

    # Drivers
    first = ["Mike","Carlos","James","Robert","David","Chris","Anthony","Steven","Kevin","Brian"]
    last  = ["Johnson","Rodriguez","Smith","Brown","Davis","Miller","Wilson","Moore","Taylor","Anderson"]
    driver_docs = []
    for i in range(10):
        d = Driver(
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
        driver_docs.append(d)
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
        l = Load(
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
        load_docs.append(l)
    await db.loads.insert_many(load_docs)

    # Invoices for loads at invoice stage or beyond
    inv_docs = []
    for l in load_docs:
        if l["stage"] in ("Invoice Pending","Payment Pending","Docs Pending"):
            inv_docs.append(Invoice(
                load_id=l["id"], customer=l["customer"], amount=l["rate"],
                status=l["invoice_status"], due_date=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()
            ).model_dump())
    if inv_docs: await db.invoices.insert_many(inv_docs)

    # Activity
    for l in load_docs:
        await log_activity(l["id"], "Load Created", "", "Booked", l["dispatcher"], "Seeded")
        if l["stage"] != "Booked":
            await log_activity(l["id"], "Stage Change", "Booked", l["stage"], l["dispatcher"], "")

    return {"ok": True, "loads": len(load_docs), "trucks": len(truck_docs), "drivers": len(driver_docs), "invoices": len(inv_docs)}

# ============ HEALTH ============
@api.get("/")
async def root():
    return {"app": "AI Dispatch.RR", "status": "operational", "time": now_iso()}

app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS','*').split(','),
    allow_methods=["*"], allow_headers=["*"])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown():
    client.close()
