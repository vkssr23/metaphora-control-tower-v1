"""Deterministic rules and bounded snapshots for Phase 1A load passports."""
import hashlib, json
from datetime import datetime, timezone
from typing import Any, Mapping
from app.schemas.passports import CheckpointType

REQUIRED_CHECKPOINT_TYPES = tuple(item.value for item in CheckpointType)
MATERIAL_LOAD_FIELDS = frozenset({"rate","miles","pickup_address","pickup_city","pickup_state","pickup_zip","pickup_appt","delivery_address","delivery_city","delivery_state","delivery_zip","delivery_appt","broker","customer","commodity","weight","equipment_type","driver_id","truck_id","rate_con_number"})
CHECKPOINT_ROLES = {"load_details":{"operations","dispatcher"},"rate_confirmation":{"operations","dispatcher"},"broker_identity":{"operations","dispatcher"},"shipper_identity":{"operations","dispatcher"},"appointment_feasibility":{"operations","dispatcher"},"pickup_instructions":{"operations","dispatcher"},"driver_eligibility":{"safety","compliance"},"truck_eligibility":{"safety","compliance"},"trailer_eligibility":{"safety","compliance"},"profitability":{"finance"}}
PRE_PICKUP_STAGES = frozenset({"Booked","Assigned","Dispatched"})
CHANGE_CHECKPOINTS = {
    "load_details": {"load_details"},
    "profitability": {"load_details", "profitability"},
    "rate_confirmation": {"rate_confirmation"},
    "party_identity": {"load_details", "broker_identity", "shipper_identity"},
    "appointment": {"load_details", "appointment_feasibility"},
    "assignment": {"load_details", "driver_eligibility", "truck_eligibility"},
    "trailer": {"load_details", "trailer_eligibility"},
    "party_verification": {"broker_identity", "shipper_identity", "pickup_instructions"},
    "pickup_instructions": {"pickup_instructions"},
    "insurance": set(),
}
def utc_now(): return datetime.now(timezone.utc).isoformat()
def bounded_load_snapshot(load: Mapping[str,Any]):
    fields=("id","customer","broker","rate_con_number","pickup_address","pickup_city","pickup_state","pickup_zip","pickup_appt","delivery_address","delivery_city","delivery_state","delivery_zip","delivery_appt","commodity","weight","equipment_type","miles","deadhead_miles","rate","stage")
    return {k:load.get(k) for k in fields if k in load}
def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,default=str).encode()).hexdigest()
def build_preinvalidation(passport, categories, actor_id, timestamp):
    """Build a tenant-independent conditional mutation plan from an observed passport.

    Tenant authority comes from the already tenant-owned observed passport;
    callers re-assert the authenticated tenant predicate before execution.
    """
    authorization=dict(passport.get("pickup_authorization") or {})
    active_authorization=authorization.get("status")=="active"
    required=passport.get("status") in {"approved","pickup_authorized"} or active_authorization
    if not required: return {"required":False,"query":{},"update":{},"reset_checkpoint_types":[]}
    reset=sorted(set().union(*(CHANGE_CHECKPOINTS.get(category,{"load_details"}) for category in categories)))
    checkpoints=[dict(item) for item in passport.get("checkpoints",[])]
    for checkpoint in checkpoints:
        if checkpoint.get("type") in reset:
            checkpoint.update({"status":"pending","checked_at":None,"checked_by":None,"checked_by_role":None,"reason_code":"","notes":"","evidence_document_ids":[],"expires_at":None,"source":"system"})
    if active_authorization:
        authorization.update({"status":"revoked","revoked_at":timestamp,"revoked_by":actor_id,"revocation_reason":"material_change_requires_reapproval"})
    query={"tenant_id":passport["tenant_id"],"id":passport["id"],"status":passport["status"],"version":passport["version"]}
    if active_authorization: query["pickup_authorization.status"]="active"
    update={"status":"review_pending","version":passport["version"]+1,"updated_at":timestamp,"updated_by":actor_id,"approved_at":None,"approved_by":None,"approved_version":None,"pickup_authorization":authorization or None,"blocking_reasons":sorted(set(passport.get("blocking_reasons",[]))|{"material_change_requires_reapproval"}),"last_material_change_at":timestamp,"checkpoints":checkpoints}
    return {"required":True,"query":query,"update":update,"reset_checkpoint_types":reset,"authorization_revoked":active_authorization,"new_version":update["version"]}
def material_categories(fields):
    fields=set(fields); categories={"load_details"}
    if fields & {"rate","miles","deadhead_miles"}: categories.add("profitability")
    if fields & {"broker","customer"}: categories.add("party_identity")
    if fields & {"pickup_address","pickup_city","pickup_state","pickup_zip","pickup_appt","delivery_address","delivery_city","delivery_state","delivery_zip","delivery_appt"}: categories.add("appointment")
    if fields & {"driver_id","truck_id"}: categories.add("assignment")
    if "rate_con_number" in fields: categories.add("rate_confirmation")
    if fields & {"equipment_type","commodity","weight","pickup_address","pickup_city","pickup_state","pickup_zip","pickup_appt","driver_id","truck_id"}: categories.add("pickup_instructions")
    return sorted(categories)
def material_drift(passport, load):
    snap=passport.get("load_snapshot",{}); drift=[f for f in MATERIAL_LOAD_FIELDS-{"driver_id","truck_id"} if snap.get(f)!=load.get(f) and (f in snap or f in load)]
    assignment=passport.get("assignment_snapshot",{})
    if assignment.get("driver_id")!=load.get("driver_id"): drift.append("driver_id")
    if assignment.get("truck_id")!=load.get("truck_id"): drift.append("truck_id")
    return sorted(set(drift))
def evaluate_readiness(passport, load):
    blockers=set(passport.get("blocking_reasons",[])); unsatisfied=[]; cps={c.get("type"):c for c in passport.get("checkpoints",[])}
    for kind in passport.get("required_checkpoint_types",REQUIRED_CHECKPOINT_TYPES):
        cp=cps.get(kind)
        if not cp or (cp.get("blocking",True) and cp.get("status") not in {"pass","waived"}): unsatisfied.append(kind)
    if unsatisfied: blockers.add("required_checkpoints_unsatisfied")
    if not passport.get("profitability_snapshot"): blockers.add("profitability_snapshot_missing")
    if load is None: blockers.add("load_not_found")
    else:
        if material_drift(passport,load): blockers.add("material_snapshot_drift")
        a=passport.get("assignment_snapshot",{})
        if not a.get("driver_id") or not a.get("truck_id"): blockers.add("assignment_incomplete")
    status=passport.get("status"); clear=not blockers; active=(passport.get("pickup_authorization") or {}).get("status")=="active"
    basic_blockers={"load_not_found","assignment_incomplete","profitability_snapshot_missing","material_snapshot_drift"}
    return {"ready_for_review":status in {"draft","blocked","revoked"} and not (blockers & basic_blockers),"ready_for_approval":status=="review_pending" and clear,"ready_for_pickup_authorization":status=="approved" and clear and load is not None and load.get("stage") in PRE_PICKUP_STAGES and not active and passport.get("approved_version")==passport.get("version"),"blocking_reasons":sorted(blockers),"unsatisfied_checkpoint_types":sorted(unsatisfied)}
def calculate_profitability(load, a):
    rate=float(load.get("rate",0)); loaded=float(load.get("miles",0)); dead=float(load.get("deadhead_miles",0)); total=loaded+dead; mpg=float(a.get("mpg",7) or 7)
    fuel=round(total/mpg*float(a.get("fuel_price",3.75)),2); driver=round(total*float(a.get("driver_pay_solo_cpm",.6)),2); insurance=round(float(a.get("insurance_per_week",0))/5,2); rental=round(float(a.get("rental_per_week",0))/5,2); factoring=round(rate*float(a.get("factoring_fee_pct",0))/100,2); toll=round(float(load.get("tolls",a.get("default_toll",0)) or 0),2); cost=round(fuel+driver+insurance+rental+factoring+toll,2); net=round(rate-cost,2)
    return {"rate":rate,"loaded_miles":loaded,"deadhead_miles":dead,"total_miles":total,"rpm":round(rate/total,2) if total else 0,"fuel_estimate":fuel,"driver_cost":driver,"insurance_allocation":insurance,"rental_allocation":rental,"factoring_cost":factoring,"toll_estimate":toll,"total_estimated_cost":cost,"estimated_net_profit":net,"estimated_margin_percentage":round(net/rate*100,1) if rate else 0,"calculated_at":utc_now(),"assumption_record_id":a.get("id","default")}
