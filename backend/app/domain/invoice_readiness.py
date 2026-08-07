"""Pure, deterministic Phase 1G invoice-readiness policy and money calculation."""
import hashlib,json
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP

MONEY=Decimal("0.01"); POLICY="invoice-readiness-v1"
REQUIRED_EVIDENCE={"lumper":{"lumper"},"detention":{"other","pod"}}
BILLING_DOCUMENT_TYPES=frozenset({"pod","rate_con","bol","lumper","other","invoice"})
INVALIDATION_REASONS=frozenset({"billing_document_changed","rate_confirmation_changed","delivery_basis_changed","accessorial_changed","deduction_changed","invoice_basis_changed"})

def money(value):
    try:d=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError):raise ValueError("invalid money")
    if not d.is_finite() or d<0:raise ValueError("invalid money")
    return d.quantize(MONEY,rounding=ROUND_HALF_UP)

def base_charge(rate):
    fields=(rate or {}).get("extracted_fields") or {}
    for field in ("total_rate","linehaul_rate"):
        if fields.get(field) is not None:return money(fields[field]),field
    return None,"insufficient_data"

def calculate(base,accessorials=(),deductions=(),currency="USD"):
    if currency!="USD":raise ValueError("unsupported currency")
    approved_a=[x for x in accessorials if x.get("status")=="approved"]
    approved_d=[x for x in deductions if x.get("status")=="approved"]
    for x in approved_a+approved_d:
        if x.get("currency","USD")!=currency:raise ValueError("currency mismatch")
    b=money(base);at=sum((money(x["amount"]) for x in approved_a),Decimal(0));dt=sum((money(x["amount"]) for x in approved_d),Decimal(0));total=(b+at-dt).quantize(MONEY)
    if total<0:raise ValueError("negative billable total")
    return {"base_charge":str(b),"accessorial_total":str(at.quantize(MONEY)),"deductions_total":str(dt.quantize(MONEY)),"billable_total":str(total),"currency":currency,"line_items":[{"id":x["id"],"type":x["type"],"amount":str(money(x["amount"]))} for x in sorted(approved_a,key=lambda z:z["id"])],"calculation_policy":POLICY}

def evidence_ok(accessorial,documents):
    if accessorial["type"] not in REQUIRED_EVIDENCE:return True
    ids=set(accessorial.get("evidence_document_ids") or []);types={d.get("doc_type") for d in documents if d.get("id") in ids}
    return bool(types & REQUIRED_EVIDENCE[accessorial["type"]])

def evaluate(load,session,rate,documents,accessorials=(),deductions=(),exceptions=()):
    docs=sorted(documents,key=lambda d:d.get("id",""));pod=[d for d in docs if d.get("doc_type")=="pod"]
    current_rate=bool(rate and rate.get("status")=="accepted" and not rate.get("superseded_by"))
    base,source=base_charge(rate) if current_rate else (None,"insufficient_data")
    checks={"delivery_confirmed":bool(session and (session.get("execution_state")=="delivery_confirmed" or session.get("status")=="completed")),"load_stage_delivered":load.get("stage")=="Delivered","execution_session_current":bool(session),"pod_present":bool(pod),"rate_confirmation_current":current_rate,"base_charge_resolved":base is not None,"accessorials_resolved":all(x.get("status") in {"approved","rejected","waived"} and (x.get("status")!="approved" or evidence_ok(x,docs)) for x in accessorials),"deductions_resolved":all(x.get("status") in {"approved","rejected","waived"} for x in deductions),"no_blocking_finance_exception":not any(x.get("blocking") and x.get("status") not in {"resolved","waived"} for x in exceptions)}
    blockers=[k for k,v in checks.items() if not v]
    calc=calculate(base,accessorials,deductions) if base is not None else None
    items=[{"type":k,"result":"pass" if v else "fail","blocking":not v} for k,v in checks.items()]
    req=[{"type":"pod","required":True,"status":"present" if pod else "missing","matching_document_ids":[d["id"] for d in pod],"blocking":not bool(pod),"reason":"POD presence required; authenticity is not verified"},{"type":"rate_con","required":True,"status":"present" if current_rate else "missing","matching_document_ids":[rate.get("document_id")] if current_rate and rate.get("document_id") else [],"blocking":not current_rate,"reason":"Current accepted rate confirmation required; authenticity is not verified"}]
    return {"verdict":"blocked" if blockers else "ready","readiness_items":items,"blockers":blockers,"document_requirements":req,"calculation":calc,"base_source":source}

def select_current_rate(load_id,tenant_id,candidates,documents):
    ordered=sorted(candidates,key=lambda x:(int(x.get("revision") or 0),int(x.get("version") or 0),str(x.get("updated_at") or ""),str(x.get("id") or "")),reverse=True)
    if not ordered:return None,"accepted_rate_confirmation_required"
    current=ordered[0]
    if current.get("tenant_id")!=tenant_id or current.get("load_id")!=load_id:return None,"document_relationship_mismatch"
    if current.get("status")!="accepted" or current.get("superseded_by"):return None,"rate_confirmation_stale"
    doc=next((d for d in documents if d.get("id")==current.get("document_id")),None)
    if not doc:return None,"document_relationship_mismatch"
    if doc.get("tenant_id")!=tenant_id or doc.get("load_id")!=load_id or doc.get("doc_type")!="rate_con":return None,"document_relationship_mismatch"
    return current,None

def basis_payload(load,session,rate,documents,accessorials,deductions,calculation):
    return {"load_id":load.get("id"),"execution":{"id":session.get("id") if session else None,"version":session.get("version") if session else None,"status":session.get("status") if session else None,"state":session.get("execution_state") if session else None},"documents":[{"id":d.get("id"),"type":d.get("doc_type"),"uploaded_at":d.get("uploaded_at")} for d in sorted(documents,key=lambda x:str(x.get("id"))) if d.get("doc_type") in BILLING_DOCUMENT_TYPES],"rate":{"id":rate.get("id"),"version":rate.get("version"),"revision":rate.get("revision"),"document_id":rate.get("document_id")} if rate else None,"accessorials":[{"id":x.get("id"),"version":x.get("version"),"status":x.get("status"),"amount":str(x.get("amount")),"currency":x.get("currency","USD"),"evidence_document_ids":sorted(x.get("evidence_document_ids") or [])} for x in sorted(accessorials,key=lambda x:str(x.get("id")))],"deductions":[{"id":x.get("id"),"version":x.get("version"),"status":x.get("status"),"amount":str(x.get("amount")),"currency":x.get("currency","USD")} for x in sorted(deductions,key=lambda x:str(x.get("id")))],"calculation":calculation}

def basis_fingerprint(load,session,rate,documents,accessorials=(),deductions=(),calculation=None):
    raw=json.dumps(basis_payload(load,session,rate,documents,accessorials,deductions,calculation),sort_keys=True,separators=(",",":"),ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()

def invalidation_plan(case,reason,changed_types,stamp,actor_id):
    if reason not in INVALIDATION_REASONS:raise ValueError("unsupported invalidation reason")
    if case.get("invoice_creation_state")=="creating" or case.get("status")=="invoiced":raise ValueError("invoice creation or issued invoice blocks material mutation")
    if case.get("status") not in {"ready","approved","review_pending","review_required"}:return None
    prior={"case_version":case["version"],"status":case.get("status"),"verdict":case.get("verdict"),"approved_at":case.get("approved_at"),"approved_by":case.get("approved_by"),"calculation_snapshot":case.get("calculation_snapshot"),"financial_basis_fingerprint":case.get("financial_basis_fingerprint"),"invalidated_at":stamp,"reason":reason}
    finding={"id":"irf_calculation_stale_"+str(case["version"]+1),"type":"calculation_stale","status":"open","blocking":True,"summary":"Invoice basis changed and requires fresh evaluation","reason":reason,"changed_types":sorted(set(changed_types))[:20]}
    return {"query":{"id":case["id"],"version":case["version"],"status":case["status"]},"update":{"status":"reopened" if case.get("status")=="approved" else "review_pending","verdict":"pending","version":case["version"]+1,"updated_at":stamp,"updated_by":actor_id,"last_material_change_at":stamp,"invalidation_reason":reason,"readiness_items":[],"findings":[*case.get("findings",[]),finding],"basis_history":[*case.get("basis_history",[]),prior]}}

def canonical_hash(package):
    bounded={k:package.get(k) for k in ("readiness_case_id","readiness_case_version","financial_basis_fingerprint","load_id","invoice_id","rate_snapshot","calculation_snapshot","document_ids")}
    return hashlib.sha256(json.dumps(bounded,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()
