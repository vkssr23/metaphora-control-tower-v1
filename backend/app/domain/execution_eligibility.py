"""Pure deterministic internal administrative execution-eligibility policy."""
from datetime import datetime, timezone, date
from app.domain.rate_confirmations import norm, EQUIPMENT_TYPES

REQUIRED_CHECK_TYPES=("driver_assignment","driver_operational_status","cdl_administrative_status","medical_card_administrative_status","mvr_administrative_status","clearinghouse_administrative_status","employment_verification_status","truck_assignment","truck_operational_status","truck_maintenance_condition","truck_insurance_evidence","truck_equipment_compatibility","trailer_identifier","trailer_equipment_compatibility","load_weight_fit","commodity_equipment_fit","appointment_feasibility","hos_readiness","pickup_readiness","required_party_clearance","required_rate_confirmation","required_load_passport_state")
MATERIAL_LOAD_FIELDS=frozenset({"driver_id","truck_id","equipment_type","commodity","weight","pickup_appt","delivery_appt","miles","est_drive_hours"})
EXECUTION_CHECKPOINTS=frozenset({"driver_eligibility","truck_eligibility","trailer_eligibility","appointment_feasibility"})
EDITABLE_STATUSES=frozenset({"draft","review_pending","review_required","blocked","expired","revoked"})
REFRESH_STATUSES=frozenset({"draft","review_pending","review_required","blocked"})
FINDING_MUTATION_STATUSES=frozenset({"review_pending","review_required"})
DRIVER_MATERIAL_FIELDS=frozenset({"name","status","cdl_number","cdl_state","cdl_expiry","medical_expiry","mvr_status","clearinghouse_status","employment_verification","assigned_truck_id"})
TRUCK_MATERIAL_FIELDS=frozenset({"truck_number","vin","status","assigned_driver_id","maintenance_status","insurance_expiry","registration_expiry","annual_inspection_expiry"})
TRANSITIONS={"draft":{"review_pending"},"review_pending":{"eligible","review_required","blocked"},"review_required":{"review_pending","eligible","blocked"},"blocked":{"review_pending"},"eligible":{"blocked","expired","revoked"},"expired":{"review_pending"},"revoked":{"review_pending"}}
PARTY_VERIFICATION_REQUIRED=True
RATE_CONFIRMATION_REQUIRED=True
def utc_now(): return datetime.now(timezone.utc).isoformat()
def expiration(value,today=None,soon_days=30):
    if not value: return "missing"
    try: d=date.fromisoformat(str(value)[:10])
    except ValueError: return "missing"
    delta=(d-(today or datetime.now(timezone.utc).date())).days
    return "expired" if delta<0 else "expires_soon" if delta<=soon_days else "current"
def expiry_result(value,today=None): return {"current":"pass","expires_soon":"warning","expired":"expired","missing":"insufficient_data"}[expiration(value,today)]
def administrative_result(kind,value):
    maps={"mvr":{"Clear":"pass","Review":"warning","Expired":"expired"},"clearinghouse":{"Clear":"pass","Pending":"warning","Issue":"fail"},"employment":{"Complete":"pass","Pending":"warning"},"maintenance":{"Good":"pass","Warn":"warning","Bad":"fail"}}
    return maps[kind].get(value,"insufficient_data")
def driver_operational(value): return "pass" if value in {"Available","Assigned","Driving"} else "warning" if value in {"Off Duty","Home Time","Missing Update"} else "fail"
def truck_operational(value): return "pass" if value in {"Available","Assigned","In Transit","At Pickup","At Delivery","Idle"} else "fail"
def equipment_compatibility(required,actual):
    r,a=norm(required),norm(actual)
    if not r or not a: return "insufficient_data"
    if r not in EQUIPMENT_TYPES or a not in EQUIPMENT_TYPES: return "warning"
    if r==a: return "pass"
    if r=="reefer" and a!="reefer": return "fail"
    if r in {"flatbed","step deck","lowboy","tanker","container"}: return "fail"
    return "warning"
def appointment_result(pickup,delivery):
    if not pickup or not delivery: return "insufficient_data"
    try: p=datetime.fromisoformat(pickup.replace("Z","+00:00")); d=datetime.fromisoformat(delivery.replace("Z","+00:00"))
    except ValueError: return "insufficient_data"
    return "fail" if d<=p else "pass"
def hos_result(hos):
    if not hos or not hos.get("reviewed_for_load"): return "insufficient_data"
    required=float(hos.get("required_trip_hours",hos.get("planned_drive_hours",0)))
    if hos.get("rest_required_before_pickup"): return "warning"
    return "pass" if float(hos.get("available_drive_hours",0))>=required else "fail"
def verdict(checks):
    values=[c.get("result","pending") for c in checks]
    if any(x in {"fail","expired"} for x in values): return "blocked"
    if any(x in {"warning","insufficient_data","pending"} for x in values): return "review_required"
    return "eligible"
def evaluate_prerequisites(load,passport,party,rate):
    """Fail-closed Phase 1D prerequisite policy; requiredness is not data-derived."""
    load_id=load.get("id") if load else None; passport_id=passport.get("id") if passport else None
    party_current=bool(party and party.get("load_id")==load_id and party.get("passport_id")==passport_id and party.get("status")=="cleared" and party.get("passport_version")==passport.get("version"))
    passport_rate=(passport.get("rate_confirmation") or {}) if passport else {}
    rate_current=bool(rate and rate.get("load_id")==load_id and rate.get("status")=="accepted" and rate.get("document_id") and rate.get("document_id")==passport_rate.get("document_id") and (not passport_rate.get("extraction_id") or passport_rate.get("extraction_id")==rate.get("id")))
    blockers=[]
    if not party_current: blockers.append("party_verification_required")
    if not rate_current: blockers.append("accepted_rate_confirmation_required")
    return {"party_required":PARTY_VERIFICATION_REQUIRED,"party_current":party_current,"rate_confirmation_required":RATE_CONFIRMATION_REQUIRED,"rate_confirmation_current":rate_current,"blockers":blockers,"warnings":[],"prerequisite_check_results":{"required_party_clearance":"pass" if party_current else "fail","required_rate_confirmation":"pass" if rate_current else "fail"}}
def evaluate(load,driver,truck,case,passport,party,rate):
    manual={c["type"]:c for c in case.get("checks",[]) if c.get("source")=="manual"}
    nonwaivable={"driver_assignment","truck_assignment","required_party_clearance","required_rate_confirmation","required_load_passport_state"}
    def ck(kind,result,reason=""):
        override=manual.get(kind)
        # Deterministic repository/prerequisite results cannot be spoofed by a
        # client check. Only an explicit owner/admin waiver may replace a
        # waivable result; the route records all other reviews as evidence.
        if override and override.get("result")=="waived" and kind not in nonwaivable: return override
        return {"type":kind,"result":result,"source":"system","reason":reason,"checked_at":utc_now(),"checked_by":None}
    assigned_driver=bool(driver and load.get("driver_id")==driver.get("id")); assigned_truck=bool(truck and load.get("truck_id")==truck.get("id"))
    required=load.get("equipment_type",""); trailer_type=case.get("trailer_snapshot",{}).get("declared_equipment_type","")
    trailer_required=norm(required) not in {"","box truck","power only"}
    prerequisites=evaluate_prerequisites(load,passport,party,rate)
    checks=[
      ck("driver_assignment","pass" if assigned_driver else "fail"), ck("driver_operational_status",driver_operational(driver.get("status")) if driver else "fail"),
      ck("cdl_administrative_status",expiry_result(driver.get("cdl_expiry")) if driver else "fail"),ck("medical_card_administrative_status",expiry_result(driver.get("medical_expiry")) if driver else "fail"),
      ck("mvr_administrative_status",administrative_result("mvr",driver.get("mvr_status")) if driver else "fail"),ck("clearinghouse_administrative_status",administrative_result("clearinghouse",driver.get("clearinghouse_status")) if driver else "fail"),ck("employment_verification_status",administrative_result("employment",driver.get("employment_verification")) if driver else "fail"),
      ck("truck_assignment","pass" if assigned_truck else "fail"),ck("truck_operational_status",truck_operational(truck.get("status")) if truck else "fail"),ck("truck_maintenance_condition",administrative_result("maintenance",truck.get("maintenance_status")) if truck else "fail"),ck("truck_insurance_evidence",expiry_result(truck.get("insurance_expiry")) if truck else "fail"),
      ck("truck_equipment_compatibility","insufficient_data"),ck("trailer_identifier","pass" if (not trailer_required or case.get("trailer_snapshot",{}).get("identifier")) else "fail"),ck("trailer_equipment_compatibility",equipment_compatibility(required,trailer_type) if trailer_required else "pass"),
      ck("load_weight_fit","insufficient_data" if not load.get("weight") else "warning"),ck("commodity_equipment_fit","insufficient_data" if not load.get("commodity") else "warning"),ck("appointment_feasibility",appointment_result(load.get("pickup_appt"),load.get("delivery_appt"))),ck("hos_readiness",hos_result(case.get("hos_readiness_snapshot"))),ck("pickup_readiness","pass" if assigned_driver and assigned_truck else "fail"),
      ck("required_party_clearance",prerequisites["prerequisite_check_results"]["required_party_clearance"],"party_verification_required"),ck("required_rate_confirmation",prerequisites["prerequisite_check_results"]["required_rate_confirmation"],"accepted_rate_confirmation_required"),ck("required_load_passport_state","pass" if passport and passport.get("load_id")==load.get("id") else "fail")]
    v=verdict(checks); blocking=sorted(c.get("reason") or c["type"] for c in checks if c["result"] in {"fail","expired"}); warnings=sorted(c["type"] for c in checks if c["result"] in {"warning","insufficient_data","pending"})
    previous={f.get("type"):f for f in case.get("findings",[]) if f.get("type")}
    findings=[]
    for c in checks:
        if c["result"] not in {"fail","expired","warning","insufficient_data"}: continue
        prior=previous.get(c["type"],{}); findings.append({"id":prior.get("id") or "eef_"+__import__("hashlib").sha256(c["type"].encode()).hexdigest()[:16],"type":c["type"],"severity":"blocking" if c["result"] in {"fail","expired"} else "warning","status":prior.get("status","open"),"resolution":prior.get("resolution"),"resolution_reason":prior.get("resolution_reason",""),"evidence_document_ids":prior.get("evidence_document_ids",[]),"resolved_at":prior.get("resolved_at"),"resolved_by":prior.get("resolved_by"),"resolved_by_role":prior.get("resolved_by_role")})
    return {"checks":checks,"findings":findings,"verdict":v,"blocking_reasons":blocking,"warning_reasons":warnings,"prerequisite_policy":prerequisites}
def passport_sync(passport,case,eligible,actor,at=None):
    ts=at or utc_now(); cps=[dict(c) for c in passport.get("checkpoints",[])]
    for cp in cps:
        if cp.get("type") in EXECUTION_CHECKPOINTS: cp.update({"status":"pass" if eligible else "pending","source":"system","checked_at":ts if eligible else None,"checked_by":actor if eligible else None,"checked_by_role":"owner" if eligible else None,"reason_code":"execution_eligibility_case" if eligible else "","notes":"","evidence_document_ids":[]})
    auth=dict(passport.get("pickup_authorization") or {})
    if not eligible and auth.get("status")=="active": auth.update({"status":"revoked","revoked_at":ts,"revoked_by":actor,"revocation_reason":"execution eligibility invalidated"})
    return {"version":passport["version"]+1,"updated_at":ts,"updated_by":actor,"checkpoints":cps,"pickup_authorization":auth or None}

def affected_policy(change_types):
    """Map material change categories to checks and passport checkpoints."""
    changes=set(change_types); checks=set(); checkpoints=set()
    if changes & {"driver","driver_assignment"}: checks|={"driver_assignment","driver_operational_status","cdl_administrative_status","medical_card_administrative_status","mvr_administrative_status","clearinghouse_administrative_status","employment_verification_status","hos_readiness","pickup_readiness"}; checkpoints|={"driver_eligibility"}
    if changes & {"truck","truck_assignment"}: checks|={"truck_assignment","truck_operational_status","truck_maintenance_condition","truck_insurance_evidence","truck_equipment_compatibility","pickup_readiness"}; checkpoints|={"truck_eligibility"}
    if changes & {"trailer","equipment","commodity","weight"}: checks|={"truck_equipment_compatibility","trailer_identifier","trailer_equipment_compatibility","load_weight_fit","commodity_equipment_fit","pickup_readiness"}; checkpoints|={"truck_eligibility","trailer_eligibility"}
    if changes & {"appointment","mileage"}: checks|={"appointment_feasibility","hos_readiness","pickup_readiness"}; checkpoints|={"appointment_feasibility"}
    if "party_verification" in changes: checks.add("required_party_clearance"); checkpoints|=set(EXECUTION_CHECKPOINTS)
    if "rate_confirmation" in changes: checks|={"required_rate_confirmation","appointment_feasibility","hos_readiness","truck_equipment_compatibility","trailer_equipment_compatibility","load_weight_fit","commodity_equipment_fit"}; checkpoints|=set(EXECUTION_CHECKPOINTS)
    return sorted(checks),sorted(checkpoints)

def build_invalidation_plan(case,passport,change_types,actor_id,timestamp=None):
    """Pure conservative cross-collection invalidation plan."""
    if not case.get("tenant_id") or not case.get("id") or not case.get("passport_id"): raise ValueError("Tenant, case, and passport identity are required")
    if not passport or passport.get("tenant_id")!=case["tenant_id"] or passport.get("id")!=case["passport_id"]: raise ValueError("Current tenant-owned passport is required")
    ts=timestamp or utc_now(); affected_checks,affected_cps=affected_policy(change_types)
    checks=[]
    for item in case.get("checks",[]):
        check=dict(item)
        if check.get("type") in affected_checks: check.update({"result":"pending","source":"system","reason":"material_change_requires_review","checked_at":None,"checked_by":None,"checked_by_role":None})
        checks.append(check)
    passport_update=passport_sync(passport,case,False,actor_id,ts)
    for cp in passport_update["checkpoints"]:
        if cp.get("type") in EXECUTION_CHECKPOINTS and cp.get("type") not in affected_cps:
            old=next((x for x in passport.get("checkpoints",[]) if x.get("type")==cp.get("type")),None)
            if old is not None: cp.clear(); cp.update(dict(old))
    reasons=sorted({"execution_eligibility_material_change",*[f"material_change:{x}" for x in sorted(set(change_types))]})
    case_update={"status":"review_pending","verdict":"pending","version":case["version"]+1,"updated_at":ts,"updated_by":actor_id,"approved_at":None,"approved_by":None,"checks":checks,"blocking_reasons":reasons,"warning_reasons":[],"last_material_change_at":ts}
    return {"eligibility_case_query":{"tenant_id":case["tenant_id"],"id":case["id"],"status":"eligible","version":case["version"]},"eligibility_case_update":case_update,"passport_query":{"tenant_id":case["tenant_id"],"id":passport["id"],"version":passport["version"]},"passport_update":passport_update,"affected_check_types":affected_checks,"affected_passport_checkpoint_types":affected_cps,"blocker_reason_codes":reasons,"pickup_authorization_revocation_required":bool((passport.get("pickup_authorization") or {}).get("status")=="active"),"case_next_status":"review_pending","case_next_verdict":"pending","case_next_version":case_update["version"],"passport_next_version":passport_update["version"]}
