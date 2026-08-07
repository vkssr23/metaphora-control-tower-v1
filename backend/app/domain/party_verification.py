"""Pure Phase 1C internal administrative comparison and risk rules."""
import re, uuid
from datetime import datetime, timezone

DOMAINS=("broker_identity","shipper_identity","carrier_authority","insurance_evidence","contact_validation","pickup_instructions","fraud_risk")
WEIGHTS={"info":2,"warning":10,"high":25,"critical":50}
FREE_DOMAINS={"gmail.com","yahoo.com","hotmail.com","outlook.com","aol.com","icloud.com"}
INSURANCE_DOCUMENT_TYPES=frozenset({"insurance"})
MUTABLE_STATUSES={
    "update":frozenset({"draft","review_pending","findings_open","blocked","expired","revoked"}),
    "refresh":frozenset({"draft","review_pending","findings_open"}),
    "evaluate":frozenset({"draft","review_pending","findings_open"}),
    "review":frozenset({"draft","review_pending","findings_open"}),
    "finding":frozenset({"review_pending","findings_open"}),
    "evidence":frozenset({"draft","review_pending","findings_open","blocked"}),
}
MATERIAL_CHANGES={
 "broker":{"domains":{"broker_identity","contact_validation","fraud_risk"},"checkpoints":{"broker_identity"},"revoke_pickup":True},
 "customer":{"domains":{"shipper_identity","pickup_instructions","fraud_risk"},"checkpoints":{"shipper_identity","pickup_instructions"},"revoke_pickup":True},
 "pickup_address":{"domains":{"shipper_identity","pickup_instructions","fraud_risk"},"checkpoints":{"shipper_identity","pickup_instructions"},"revoke_pickup":True},
 "pickup_city":{"domains":{"pickup_instructions"},"checkpoints":{"pickup_instructions"},"revoke_pickup":True},
 "pickup_state":{"domains":{"pickup_instructions"},"checkpoints":{"pickup_instructions"},"revoke_pickup":True},
 "pickup_zip":{"domains":{"pickup_instructions"},"checkpoints":{"pickup_instructions"},"revoke_pickup":True},
 "pickup_appt":{"domains":{"pickup_instructions","fraud_risk"},"checkpoints":{"pickup_instructions"},"revoke_pickup":True},
 "rate_con_number":{"domains":{"broker_identity","pickup_instructions","fraud_risk"},"checkpoints":{"rate_confirmation","pickup_instructions"},"revoke_pickup":True},
 "equipment_type":{"domains":{"pickup_instructions","fraud_risk"},"checkpoints":{"pickup_instructions"},"revoke_pickup":True},
 "commodity":{"domains":{"pickup_instructions","fraud_risk"},"checkpoints":{"pickup_instructions"},"revoke_pickup":True},
 "weight":{"domains":{"pickup_instructions"},"checkpoints":{"pickup_instructions"},"revoke_pickup":True},
 "driver_id":{"domains":{"pickup_instructions"},"checkpoints":{"pickup_instructions"},"revoke_pickup":True},
 "truck_id":{"domains":{"pickup_instructions"},"checkpoints":{"pickup_instructions"},"revoke_pickup":True},
 "insurance_evidence":{"domains":{"insurance_evidence","fraud_risk"},"checkpoints":set(),"revoke_pickup":False},
 "rate_confirmation":{"domains":{"broker_identity","shipper_identity","contact_validation","pickup_instructions","fraud_risk"},"checkpoints":{"rate_confirmation","broker_identity","shipper_identity","pickup_instructions"},"revoke_pickup":True},
 "pickup_instruction_evidence":{"domains":{"pickup_instructions","contact_validation","fraud_risk"},"checkpoints":{"pickup_instructions"},"revoke_pickup":True},
}

def now(): return datetime.now(timezone.utc).isoformat()
def norm(v): return re.sub(r"\s+"," ",str(v or "").strip()).casefold()
def phone(v): return re.sub(r"\D","",str(v or ""))
def is_insurance_document(doc): return doc.get("doc_type") in INSURANCE_DOCUMENT_TYPES
def qualified_insurance_documents(documents): return [d for d in documents if is_insurance_document(d)]
def material_effects(changes):
    entries=[MATERIAL_CHANGES[x] for x in changes if x in MATERIAL_CHANGES]
    return {"domains":sorted(set().union(*(e["domains"] for e in entries)) if entries else set()),"checkpoints":sorted(set().union(*(e["checkpoints"] for e in entries)) if entries else set()),"revoke_pickup":any(e["revoke_pickup"] for e in entries)}
def build_case_preinvalidation(case,changes,actor_id,timestamp):
    effects=material_effects(changes)
    if case.get("status")!="cleared" or not effects["domains"]: return {"required":False,"effects":effects}
    reviews={k:dict(v) for k,v in case.get("reviews",{}).items()}
    for domain in effects["domains"]:
        reviews[domain]={"domain":domain,"result":"pending","source":"system","reason":"material change requires re-verification","evidence_document_ids":[],"reviewed_at":None,"reviewed_by":None,"reviewed_by_role":None}
    update={"status":"review_pending","version":case["version"]+1,"updated_at":timestamp,"updated_by":actor_id,"cleared_at":None,"cleared_by":None,"last_material_change_at":timestamp,"blocking_reasons":["material_change_requires_reverification"],"reviews":reviews}
    return {"required":True,"query":{"id":case["id"],"status":"cleared","version":case["version"]},"update":update,"effects":effects}
def build_passport_preinvalidation(passport,effects,actor_id,timestamp):
    checkpoints=[dict(x) for x in passport.get("checkpoints",[])]
    for cp in checkpoints:
        if cp.get("type") in effects["checkpoints"]: cp.update({"status":"pending","checked_at":None,"checked_by":None,"checked_by_role":None,"reason_code":"party_verification_requires_review","notes":"Party verification material change","evidence_document_ids":[],"expires_at":None,"source":"system"})
    auth=dict(passport.get("pickup_authorization") or {})
    if effects["revoke_pickup"] and auth.get("status")=="active": auth.update({"status":"revoked","revoked_at":timestamp,"revoked_by":actor_id,"revocation_reason":"party_verification_requires_review"})
    update={"version":passport["version"]+1,"updated_at":timestamp,"updated_by":actor_id,"status":"review_pending","approved_at":None,"approved_by":None,"approved_version":None,"checkpoints":checkpoints,"pickup_authorization":auth or None,"blocking_reasons":sorted(set(passport.get("blocking_reasons",[]))|{"party_verification_requires_review"}),"last_material_change_at":timestamp}
    return {"query":{"id":passport["id"],"status":passport["status"],"version":passport["version"]},"update":update}
def assert_mutable(status,operation): return status in MUTABLE_STATUSES[operation]
def rate_confirmation_required(documents): return any(d.get("doc_type")=="rate_con" for d in documents)
def finding(kind,domain,severity,blocking,summary,observed="",expected=""):
    return {"id":f"pvf_{uuid.uuid4().hex}","domain":domain,"type":kind,"severity":severity,"status":"open","blocking":blocking,"summary":summary[:300],"observed_value_summary":str(observed)[:200],"expected_value_summary":str(expected)[:200],"evidence_document_ids":[],"resolution":None,"resolution_reason":"","resolved_at":None,"resolved_by":None,"resolved_by_role":None,"source":"system"}
def snapshots(load,passport,rate,documents,tenant):
    fields=(rate or {}).get("accepted_snapshot",{}).get("extracted_fields",{})
    broker={"name":load.get("broker","")} | {k:fields.get(k) for k in ("broker_mc","broker_contact_name","broker_contact_email","broker_contact_phone") if fields.get(k)}
    shipper={"name":load.get("customer",""),"pickup_facility":fields.get("pickup_name",load.get("pickup_address","")),"pickup_address":load.get("pickup_address","")} | {k:fields.get(k) for k in ("pickup_number",) if fields.get(k)}
    carrier={k:tenant.get(k) for k in ("name","legal_name","dba","usdot","mc","phone","email") if tenant.get(k)}
    insurance=[{"document_id":d["id"],"filename":d.get("filename","")[:255],"document_type":d.get("doc_type",""),"stated_effective_date":d.get("stated_effective_date","")[:64],"stated_expiration_date":d.get("stated_expiration_date","")[:64],"named_insured":d.get("named_insured","")[:200],"uploaded_at":d.get("uploaded_at"),"uploaded_by":d.get("uploaded_by")} for d in qualified_insurance_documents(documents)]
    pickup={k:load.get(k) for k in ("pickup_address","pickup_city","pickup_state","pickup_zip","pickup_appt","equipment_type","commodity","rate_con_number") if k in load}
    return broker,shipper,carrier,insurance,{"normalized_email":norm(broker.get("broker_contact_email")),"normalized_phone":phone(broker.get("broker_contact_phone")),"external_validation_performed":False},pickup
def evaluate(case,load,rate):
    b=case.get("broker_snapshot",{}); s=case.get("shipper_snapshot",{}); c=case.get("carrier_snapshot",{}); ins=case.get("insurance_evidence_snapshot",[]); p=case.get("pickup_instruction_snapshot",{}); fields=(rate or {}).get("accepted_snapshot",{}).get("extracted_fields",{})
    fs=[]
    if not b.get("name"): fs.append(finding("missing_broker_identifier","broker_identity","high",True,"Broker identity data is incomplete"))
    if not b.get("broker_mc"): fs.append(finding("missing_broker_identifier","broker_identity","warning",False,"Broker authority identifier is not present"))
    if fields.get("broker_name") and norm(fields["broker_name"])!=norm(b.get("name")): fs.append(finding("broker_name_mismatch","broker_identity","high",True,"Broker names do not internally match",b.get("name"),fields["broker_name"]))
    if not s.get("name"): fs.append(finding("missing_shipper_contact","shipper_identity","warning",False,"Shipper identity data is incomplete"))
    if not c.get("usdot"): fs.append(finding("missing_carrier_usdot","carrier_authority","high",True,"Carrier USDOT is not present in canonical tenant data"))
    if not c.get("mc"): fs.append(finding("missing_carrier_mc","carrier_authority","warning",False,"Carrier MC is not present in canonical tenant data"))
    if not ins: fs.append(finding("insurance_document_missing","insurance_evidence","high",True,"Insurance evidence metadata is not present"))
    for item in ins:
        stated=item.get("stated_expiration_date")
        if stated:
            try: expired=datetime.fromisoformat(stated.replace("Z","+00:00")).date()<datetime.now(timezone.utc).date()
            except ValueError: expired=False
            if expired: fs.append(finding("insurance_document_expired_by_stated_date","insurance_evidence","high",True,"Insurance evidence is expired by its stated document date",stated,"current date"))
    email=b.get("broker_contact_email",""); domain=email.rsplit("@",1)[-1].lower() if "@" in email else ""
    if domain in FREE_DOMAINS: fs.append(finding("conflicting_contact_information","contact_validation","info",False,"A free-email-domain indicator requires internal review"))
    for lf,rf,kind in (("pickup_address","pickup_address","pickup_address_mismatch"),("rate_con_number","pickup_number","pickup_number_mismatch"),("equipment_type","equipment_type","equipment_mismatch"),("commodity","commodity","commodity_mismatch")):
        if fields.get(rf) and norm(p.get(lf))!=norm(fields.get(rf)): fs.append(finding(kind,"pickup_instructions","high",True,f"{lf.replace('_',' ').title()} does not internally match",p.get(lf),fields.get(rf)))
    if not p.get("rate_con_number") and not fields.get("pickup_number"): fs.append(finding("missing_pickup_reference","pickup_instructions","warning",False,"Pickup reference is missing"))
    resolved={(x.get("type"),x.get("domain")):x for x in case.get("findings",[]) if x.get("status") in {"resolved","waived"}}
    for f in fs:
        prior=resolved.get((f["type"],f["domain"]))
        if prior: f.update({k:prior.get(k) for k in ("status","resolution","resolution_reason","resolved_at","resolved_by","resolved_by_role","evidence_document_ids")})
    score=min(100,sum(WEIGHTS[f["severity"]] for f in fs if f["status"]=="open")); critical=sum(f["severity"]=="critical" and f["status"]=="open" for f in fs); blocking=sum(f["blocking"] and f["status"]=="open" for f in fs)
    level="critical" if critical or score>=75 else "high" if score>=50 else "moderate" if score>=20 else "low"
    signals=[{"type":f["type"],"severity":f["severity"],"blocking":f["blocking"],"domain":f["domain"]} for f in fs if f["status"]=="open"]
    risk={"risk_level":level,"risk_score":score,"signal_count":len(signals),"blocking_signal_count":blocking,"critical_signal_count":critical,"signals":signals,"blocking_reasons":sorted({f["type"] for f in fs if f["blocking"] and f["status"]=="open"}),"recommended_action":"blocked pending review" if blocking or critical else "continue internal review","evaluated_at":now(),"notice":"Internal workflow indicator; not a fraud probability."}
    return fs,risk
