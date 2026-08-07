"""Pure, fail-closed Phase 1E secure pickup release policy."""
import hashlib,json,re
from datetime import datetime,timezone
from app.domain.load_passports import canonical_hash

STATUSES=("draft","review_pending","review_required","release_ready","released","pickup_confirmed","exception","blocked","revoked","expired")
TRANSITIONS={"draft":{"review_pending"},"review_pending":{"release_ready","review_required","blocked"},"review_required":{"review_pending","release_ready","blocked"},"release_ready":{"released","blocked"},"released":{"pickup_confirmed","exception","revoked"},"pickup_confirmed":{"exception"},"blocked":{"review_pending"},"revoked":{"review_pending"},"expired":{"review_pending"}}
EDITABLE={"draft","review_pending","review_required","blocked","revoked","expired"}
CHECKLIST_TYPES=("load_passport_current","rate_confirmation_current","party_verification_current","execution_eligibility_current","driver_assignment_current","truck_assignment_current","trailer_identifier_current","pickup_facility_current","pickup_address_current","pickup_date_current","pickup_time_current","pickup_reference_current","pickup_contact_current","equipment_current","commodity_current","no_unresolved_blocking_findings","no_last_minute_material_change","pickup_authorization_not_already_active","release_snapshot_current")
MATERIAL_FIELDS=("pickup_facility","pickup_address","pickup_date","pickup_time","pickup_reference","pickup_contact","driver_id","truck_id","trailer_identifier","equipment","commodity","weight","rate_confirmation_id","party_verification_id","execution_eligibility_id","passport_version")
MANDATORY_FINDINGS={"load_passport_not_current","rate_confirmation_not_current","party_verification_not_current","execution_eligibility_not_current","driver_assignment_changed","truck_assignment_changed","trailer_identifier_changed","pickup_address_mismatch","release_snapshot_stale","duplicate_active_authorization"}
def utc_now(): return datetime.now(timezone.utc).isoformat()
def norm(v): return re.sub(r"\s+"," ",str(v or "").strip().lower())
def phone(v): return re.sub(r"\D","",str(v or ""))[-10:]
def contact_snapshot(party):
    c=(party or {}).get("contact_validation_snapshot") or {}; b=(party or {}).get("broker_snapshot") or {}
    return {"name":b.get("broker_contact_name") or b.get("contact_name") or "","email":c.get("normalized_email") or "","phone":c.get("normalized_phone") or "","source":"internal_records"}
def bounded_snapshot(load,passport,rate,party,execution):
    fields=(rate or {}).get("accepted_snapshot",{}).get("extracted_fields",{})
    trailer=(execution or {}).get("trailer_snapshot",{}).get("identifier","")
    return {"load":{"id":load.get("id"),"reference":load.get("rate_con_number"),"pickup_facility":load.get("pickup_facility") or load.get("customer"),"pickup_address":load.get("pickup_address"),"pickup_city":load.get("pickup_city"),"pickup_state":load.get("pickup_state"),"pickup_zip":load.get("pickup_zip"),"pickup_appt":load.get("pickup_appt"),"equipment":load.get("equipment_type"),"commodity":load.get("commodity"),"weight":load.get("weight"),"driver_id":load.get("driver_id"),"truck_id":load.get("truck_id"),"trailer_identifier":trailer},"passport":{"id":passport.get("id"),"version":passport.get("version"),"status":passport.get("status"),"authorization_state":(passport.get("pickup_authorization") or {}).get("status")},"rate_confirmation":{"id":rate.get("id"),"version":rate.get("version"),"revision":rate.get("revision"),"document_id":rate.get("document_id"),"pickup_name":fields.get("pickup_name"),"pickup_address":fields.get("pickup_address"),"pickup_date":fields.get("pickup_date"),"pickup_time":fields.get("pickup_time_start"),"pickup_reference":fields.get("pickup_number"),"equipment":fields.get("equipment_type"),"commodity":fields.get("commodity")},"party_verification":{"id":party.get("id"),"version":party.get("version"),"status":party.get("status"),"shipper":party.get("shipper_snapshot",{}),"contact":contact_snapshot(party)},"execution_eligibility":{"id":execution.get("id"),"version":execution.get("version"),"status":execution.get("status"),"driver_id":(execution.get("driver_snapshot") or {}).get("id"),"truck_id":(execution.get("truck_snapshot") or {}).get("id"),"trailer_identifier":trailer}}
def finding(kind,domain,summary,blocking=True,severity="high"):
    return {"id":"prf_"+hashlib.sha256(kind.encode()).hexdigest()[:16],"type":kind,"domain":domain,"severity":severity,"status":"open","blocking":blocking,"summary":summary,"observed_value_summary":"","expected_value_summary":"","resolution":None,"resolution_reason":"","source":"internal_deterministic_comparison"}
def evaluate(load,passport,rate,party,execution,case,evaluation_context):
    """Pure readiness evaluation. All ambient time is supplied by the caller."""
    as_of=evaluation_context["as_of"]
    fs=[]; checks={}; load_id=load.get("id") if load else None
    def ck(k,result): checks[k]={"type":k,"result":result,"source":"system","reason":""}
    passport_ok=bool(passport and passport.get("load_id")==load_id and passport.get("status") in {"approved","pickup_authorized"})
    rate_ok=bool(rate and rate.get("load_id")==load_id and rate.get("status")=="accepted" and (passport or {}).get("rate_confirmation",{}).get("extraction_id") in {None,rate.get("id")})
    party_ok=bool(party and party.get("load_id")==load_id and party.get("status")=="cleared" and party.get("passport_id")==passport.get("id")) if passport else False
    execution_ok=bool(execution and execution.get("load_id")==load_id and execution.get("status")=="eligible" and execution.get("passport_id")==passport.get("id") and execution.get("passport_version")==passport.get("version")) if passport else False
    for ok,k,t in ((passport_ok,"load_passport_current","load_passport_not_current"),(rate_ok,"rate_confirmation_current","rate_confirmation_not_current"),(party_ok,"party_verification_current","party_verification_not_current"),(execution_ok,"execution_eligibility_current","execution_eligibility_not_current")):
        ck(k,"pass" if ok else "fail")
        if not ok: fs.append(finding(t,"prerequisite",t.replace("_"," ")))
    snap=case.get("release_snapshot") or {}; frozen=snap.get("load",{}); ex=snap.get("execution_eligibility",{}); bound=case.get("prerequisite_snapshot") or {}
    current_bindings={
      "passport":bool(passport and bound.get("passport_id")==passport.get("id") and bound.get("passport_version")==passport.get("version")),
      "rate":bool(rate and bound.get("rate_confirmation_id")==rate.get("id") and bound.get("rate_confirmation_version")==rate.get("version") and bound.get("rate_confirmation_revision")==rate.get("revision") and bound.get("rate_confirmation_document_id")==rate.get("document_id") and rate.get("status")=="accepted" and rate.get("load_id")==load_id),
      "party":bool(party and bound.get("party_verification_id")==party.get("id") and bound.get("party_verification_version")==party.get("version") and party.get("status")=="cleared" and party.get("load_id")==load_id and party.get("passport_id")==case.get("passport_id")),
      "execution":bool(execution and bound.get("execution_eligibility_id")==execution.get("id") and bound.get("execution_eligibility_version")==execution.get("version") and execution.get("status")=="eligible" and execution.get("load_id")==load_id and execution.get("passport_id")==case.get("passport_id")),
    }
    if bound and not all(current_bindings.values()): fs.append(finding("prerequisite_version_changed","prerequisite","frozen prerequisite identity or version changed"))
    assignment=(execution or {})
    values=((load.get("driver_id"), (assignment.get("driver_snapshot") or {}).get("id"), frozen.get("driver_id"),"driver_assignment_current","driver_assignment_changed"),(load.get("truck_id"),(assignment.get("truck_snapshot") or {}).get("id"),frozen.get("truck_id"),"truck_assignment_current","truck_assignment_changed"),((assignment.get("trailer_snapshot") or {}).get("identifier"),ex.get("trailer_identifier"),frozen.get("trailer_identifier"),"trailer_identifier_current","trailer_identifier_changed"))
    for current,eligible,fz,k,t in values:
        ok=bool(current and current==eligible and current==fz); ck(k,"pass" if ok else "fail")
        if not ok: fs.append(finding(t,"assignment",t.replace("_"," ")))
    rf=(rate or {}).get("accepted_snapshot",{}).get("extracted_fields",{})
    comparisons=(("pickup_address",load.get("pickup_address"),rf.get("pickup_address"),"pickup_address_current","pickup_address_mismatch",True),("pickup_date",str(load.get("pickup_appt") or "")[:10],rf.get("pickup_date"),"pickup_date_current","pickup_date_mismatch",True),("pickup_time",str(load.get("pickup_appt") or "")[11:16],str(rf.get("pickup_time_start") or "")[:5],"pickup_time_current","pickup_time_mismatch",True),("pickup_reference",load.get("rate_con_number"),rf.get("pickup_number"),"pickup_reference_current","pickup_reference_mismatch",True),("equipment",load.get("equipment_type"),rf.get("equipment_type"),"equipment_current","equipment_mismatch",True),("commodity",load.get("commodity"),rf.get("commodity"),"commodity_current","commodity_mismatch",True))
    for _,a,b,k,t,required in comparisons:
        ok=bool(a and b and norm(a)==norm(b)); ck(k,"pass" if ok else "fail")
        if not ok: fs.append(finding(t,"pickup",t.replace("_"," ")))
    facility=rf.get("pickup_name") or (party or {}).get("shipper_snapshot",{}).get("pickup_facility"); ok=bool(facility and norm(facility)==norm(load.get("pickup_facility") or load.get("customer"))); ck("pickup_facility_current","pass" if ok else "fail")
    if not ok: fs.append(finding("pickup_facility_mismatch","pickup","pickup facility mismatch"))
    current_contact=contact_snapshot(party); expected=(case.get("contact_snapshot") or {}); contact_ok=bool(expected and ((expected.get("email") and norm(expected.get("email"))==norm(current_contact.get("email"))) or (expected.get("phone") and phone(expected.get("phone"))==phone(current_contact.get("phone"))) or (expected.get("name") and norm(expected.get("name"))==norm(current_contact.get("name"))))); ck("pickup_contact_current","pass" if contact_ok else "insufficient_data")
    if not contact_ok: fs.append(finding("pickup_contact_mismatch","pickup","pickup contact is missing or changed",False,"warning"))
    active=(passport.get("pickup_authorization") or {}).get("status")=="active" if passport else False; ck("pickup_authorization_not_already_active","fail" if active else "pass")
    if active: fs.append(finding("duplicate_active_authorization","release_integrity","active pickup authorization already exists"))
    snapshot_ok=bool(passport and snap and snap.get("passport",{}).get("version")==passport.get("version")); ck("release_snapshot_current","pass" if snapshot_ok else "fail")
    if not snapshot_ok: fs.append(finding("release_snapshot_stale","release_integrity","release snapshot is stale"))
    ck("no_last_minute_material_change","pass" if snapshot_ok else "fail")
    previous={f.get("type"):f for f in case.get("findings",[]) if f.get("status") in {"resolved","waived"}}
    for f in fs:
        if f["type"] in previous and f["type"] not in MANDATORY_FINDINGS: f.update(previous[f["type"]])
    blocking=sorted({f["type"] for f in fs if f["blocking"] and f["status"]=="open"}); warnings=sorted({f["type"] for f in fs if not f["blocking"] and f["status"]=="open"}); ck("no_unresolved_blocking_findings","fail" if blocking else "pass")
    verdict="blocked" if blocking else "review_required" if warnings else "release_ready"
    return {"as_of":as_of,"verdict":verdict,"blocking_reasons":blocking,"warning_reasons":warnings,"unresolved_finding_ids":sorted(f["id"] for f in fs if f["status"]=="open"),"satisfied_checklist_items":sorted(k for k,v in checks.items() if v["result"] in {"pass","waived"}),"unsatisfied_checklist_items":sorted(k for k,v in checks.items() if v["result"] not in {"pass","waived"}),"requires_human_review":verdict!="release_ready","prerequisite_currentness":current_bindings,"checklist_items":[checks[k] for k in CHECKLIST_TYPES if k in checks],"findings":sorted(fs,key=lambda x:(x["domain"],x["type"]))}
def material_changes(snapshot,current):
    before=(snapshot or {}).get("load",{}); changed=sorted(k for k in ("pickup_address","pickup_facility","pickup_appt","reference","driver_id","truck_id","trailer_identifier","equipment","commodity","weight") if norm(before.get(k))!=norm(current.get(k)))
    return {"changed_fields":changed,"affected_checklist_items":changed,"severity":"critical" if changed else "info","blocking":bool(changed),"authorization_revocation_required":bool(changed),"requires_re_review":bool(changed)}
def authorization(case,passport,user,at=None):
    ts=at or utc_now(); snap=case["release_snapshot"]; aid="pua_"+hashlib.sha256(f'{case["id"]}:{case["version"]}:{passport["version"]}'.encode()).hexdigest()[:20]
    evidence={"authorization_id":aid,"tenant_id":case["tenant_id"],"load_id":case["load_id"],"passport_id":passport["id"],"passport_version":passport["version"]+1,"release_case_id":case["id"],"release_case_version":case["version"]+1,"execution_eligibility_case_id":case["execution_eligibility_case_id"],"party_verification_case_id":case["party_verification_case_id"],"rate_confirmation_extraction_id":case["rate_confirmation_extraction_id"],"driver_id":snap["load"].get("driver_id"),"truck_id":snap["load"].get("truck_id"),"trailer_identifier":snap["load"].get("trailer_identifier"),"issued_at":ts,"issued_by":user["id"],"state":"active","status":"active","source":"internal_human_release"}
    evidence["evidence_hash"]=canonical_hash(evidence); return evidence
def revoke_authorization(auth,user,reason,at=None):
    out=dict(auth or {}); out.update({"state":"revoked","status":"revoked","revoked_at":at or utc_now(),"revoked_by":user["id"],"revocation_reason":reason}); return out
def authorization_binding(case,passport,load,tenant_id):
    auth=(passport or {}).get("pickup_authorization") or {}; snap=case.get("assignment_snapshot") or {}
    valid=bool(passport and case.get("tenant_id")==tenant_id and passport.get("tenant_id")==tenant_id and auth.get("tenant_id")==tenant_id and passport.get("id")==case.get("passport_id") and passport.get("load_id")==case.get("load_id") and auth.get("authorization_id")==case.get("pickup_authorization_id") and auth.get("load_id")==case.get("load_id") and auth.get("passport_id")==case.get("passport_id") and auth.get("release_case_id")==case.get("id") and auth.get("release_case_version")==case.get("version") and auth.get("state","active")=="active" and auth.get("status","active")=="active" and not auth.get("revoked_at") and not auth.get("expired_at") and not auth.get("consumed_at") and load and load.get("id")==case.get("load_id") and auth.get("driver_id")==load.get("driver_id")==snap.get("driver_id") and auth.get("truck_id")==load.get("truck_id")==snap.get("truck_id") and auth.get("trailer_identifier")==snap.get("trailer_identifier"))
    return {"valid":valid,"reason":"" if valid else "pickup_authorization_binding_mismatch"}
