"""Pure, read-only production integrity and readiness evaluation."""
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from app.infrastructure.index_manifest import expected_indexes
from app.tenant import TENANT_ID_PATTERN

SEVERITIES=("critical","high","medium","low","info")
TENANT_SCOPED=frozenset({"users","loads","drivers","trucks","documents","audit_events","load_passports","rate_confirmation_extractions","party_verification_cases","execution_eligibility_cases","pickup_release_cases","execution_sessions","execution_events","execution_exceptions","invoice_readiness_cases","invoice_packages","invoices","assumptions"})
SUPPORTED_DOCUMENT_TYPES=frozenset({"rate_con","bol","pod","lumper","scale","invoice","other","insurance"})
REQUIRED_VERSION=frozenset({"load_passports","rate_confirmation_extractions","party_verification_cases","execution_eligibility_cases","pickup_release_cases","execution_sessions","execution_exceptions","invoice_readiness_cases"})
PARENTS={
 "documents":(("load_id","loads"),), "load_passports":(("load_id","loads"),),
 "rate_confirmation_extractions":(("load_id","loads"),("document_id","documents")),
 "party_verification_cases":(("load_id","loads"),("passport_id","load_passports")),
 "execution_eligibility_cases":(("load_id","loads"),("passport_id","load_passports")),
 "pickup_release_cases":(("load_id","loads"),("passport_id","load_passports"),("execution_eligibility_case_id","execution_eligibility_cases")),
 "execution_sessions":(("load_id","loads"),("pickup_release_case_id","pickup_release_cases")),
 "execution_events":(("execution_session_id","execution_sessions"),), "execution_exceptions":(("execution_session_id","execution_sessions"),("load_id","loads")),
 "invoice_readiness_cases":(("load_id","loads"),("execution_session_id","execution_sessions")),
 "invoice_packages":(("readiness_case_id","invoice_readiness_cases"),),
 "invoices":(("load_id","loads"),("readiness_case_id","invoice_readiness_cases"),("package_id","invoice_packages")),
}

@dataclass(frozen=True)
class Finding:
    code:str; severity:str; collection:str; description:str; count:int=1
    entity_id:str|None=None; tenant_id:str|None=None; recommended_action:str="Review before pilot rollout"

def _safe(value: Any, maximum=100) -> str|None:
    return value[:maximum] if isinstance(value,str) else None

def _finding(code,severity,collection,description,doc=None,count=1,action="Review before pilot rollout"):
    return Finding(code,severity,collection,description,count,_safe((doc or {}).get("id")),_safe((doc or {}).get("tenant_id")),action)

def _matches(doc, predicate):
    for key,expected in (predicate or {}).items():
        if isinstance(expected,dict) and "$in" in expected and doc.get(key) not in expected["$in"]: return False
        if isinstance(expected,dict) and "$exists" in expected and (key in doc)!=expected["$exists"]: return False
        if not isinstance(expected,dict) and doc.get(key)!=expected:return False
    return True

def scan_integrity(records: Mapping[str,Sequence[Mapping[str,Any]]], *, environment="unknown", generated_at=None, max_findings=500):
    """Scan plain records. Input values are copied/read only; output is bounded and secret-free."""
    findings=[]
    def add(f): findings.append(f)
    tenants={x.get("id") for x in records.get("tenants",())}
    lookup={(c,x.get("tenant_id"),x.get("id")):x for c,docs in records.items() for x in docs if x.get("id")}
    for collection in sorted(TENANT_SCOPED):
        for doc in records.get(collection,()):
            tid=doc.get("tenant_id")
            if not tid: add(_finding("TENANT_MISSING","critical",collection,"Tenant-scoped record has no tenant_id",doc))
            elif not isinstance(tid,str) or not TENANT_ID_PATTERN.fullmatch(tid): add(_finding("TENANT_ID_MALFORMED","critical",collection,"Record tenant_id is not canonical",doc))
            elif tid not in tenants: add(_finding("TENANT_REFERENCE_MISSING","critical",collection,"Record references a nonexistent tenant",doc))
            if collection=="users" and not doc.get("email"): add(_finding("USER_EMAIL_MISSING","critical",collection,"User email is null or missing",doc,action="Restore a canonical login identity before unique-index rollout"))
            if collection in REQUIRED_VERSION and not isinstance(doc.get("version"),int): add(_finding("VERSION_MISSING","medium",collection,"Lifecycle record lacks integer version",doc))
    canonical_emails=defaultdict(list)
    for user in records.get("users",()):
        email=user.get("email")
        if not isinstance(email,str) or not email.strip(): continue
        canonical=email.strip().lower()
        canonical_emails[canonical].append(user)
        if email!=canonical:add(_finding("USER_EMAIL_NOT_NORMALIZED","high","users","Stored email is not in the canonical trimmed lowercase form",user,action="Normalize through a reviewed migration before index rollout"))
    for users in canonical_emails.values():
        if len(users)>1:add(_finding("USER_EMAIL_CANONICAL_COLLISION","critical","users","Stored emails collide after application canonicalization",users[0],len(users),"Resolve canonical email ownership before unique-index rollout"))
    for child,links in PARENTS.items():
        for doc in records.get(child,()):
            for field,parent_collection in links:
                parent_id=doc.get(field)
                if not parent_id: continue # optional/snapshot-era references are handled by domain checks
                same=lookup.get((parent_collection,doc.get("tenant_id"),parent_id))
                if same: continue
                elsewhere=any(x.get("id")==parent_id for x in records.get(parent_collection,()))
                code="CROSS_TENANT_REFERENCE" if elsewhere else "ORPHAN_REFERENCE"
                sev="critical" if elsewhere or child in {"invoice_packages","invoices","execution_events"} else "high"
                add(_finding(code,sev,child,f"{field} does not resolve within the record tenant",doc))
    # Every manifest unique index is also the collision preflight, including identical partial semantics.
    for index in expected_indexes():
        if not index.unique: continue
        groups=defaultdict(list)
        for doc in records.get(index.collection,()):
            if not _matches(doc,index.partial_filter): continue
            components=[]; uncertain=[]
            for field,_ in index.fields:
                if field not in doc: components.append(None); uncertain.append(f"{field}:missing")
                elif doc.get(field) is None: components.append(None); uncertain.append(f"{field}:null")
                else: components.append(doc[field])
            if uncertain and index.priority=="P0":
                add(_finding("INDEX_NULL_OR_MISSING_KEY","critical",index.collection,f"{index.name} has required null/missing components ({', '.join(uncertain)})",doc,action="Resolve required unique-key components and verify in disposable Mongo before rollout"))
            groups[tuple(components)].append(doc)
        for key,docs in groups.items():
            if len(docs)>1:
                add(_finding("INDEX_COLLISION","critical",index.collection,f"{index.name} would collide",docs[0],len(docs),"Resolve duplicates before creating this unique index"))
    docs=records.get("documents",())
    for doc in docs:
        if doc.get("doc_type") not in SUPPORTED_DOCUMENT_TYPES:add(_finding("DOCUMENT_TYPE_UNSUPPORTED","high","documents","Document type is unknown",doc))
        if not doc.get("filename") or not doc.get("url"):add(_finding("DOCUMENT_METADATA_MISSING","medium","documents","Document lacks filename or URL metadata",doc))
        url=str(doc.get("url","")).lower()
        if url.startswith(("mock://","fake://","placeholder://")) or "example.invalid" in url:add(_finding("DOCUMENT_STORAGE_SIMULATED","critical","documents","Document uses simulated or placeholder storage",doc,action="Move evidence to pilot-approved storage before pilot"))
    loads={(x.get("tenant_id"),x.get("id")):x for x in records.get("loads",())}
    sessions=records.get("execution_sessions",())
    for s in sessions:
        load=loads.get((s.get("tenant_id"),s.get("load_id")))
        delivered=s.get("execution_state")=="delivery_confirmed" or s.get("status")=="delivery_confirmed" or s.get("custody_state")=="delivered"
        if delivered and load and load.get("stage")!="Delivered":add(_finding("DELIVERY_LOAD_STATE_DISAGREEMENT","high","execution_sessions","Delivery-confirmed execution has a non-Delivered load",s))
        if s.get("status") not in {"completed","cancelled"} and load and load.get("stage") in {"Closed","Cancelled","Deleted"}:add(_finding("ACTIVE_EXECUTION_TERMINAL_LOAD","high","execution_sessions","Non-terminal execution belongs to terminal load",s))
    readiness=records.get("invoice_readiness_cases",()); invoices=records.get("invoices",()); packages=records.get("invoice_packages",())
    for load in records.get("loads",()):
        if load.get("stage")!="Delivered":continue
        related=[s for s in sessions if s.get("tenant_id")==load.get("tenant_id") and s.get("load_id")==load.get("id")]
        modern=bool(related) or any(r.get("tenant_id")==load.get("tenant_id") and r.get("load_id")==load.get("id") and r.get("execution_session_id") for r in readiness)
        confirmed=any(s.get("execution_state")=="delivery_confirmed" or s.get("custody_state") in {"delivered","delivery_confirmed","completed"} for s in related)
        if modern and not confirmed:add(_finding("MODERN_DELIVERY_EVIDENCE_MISSING","high","loads","Execution-managed Delivered load lacks required delivery-confirmed evidence",load))
        elif not modern:add(_finding("LEGACY_DELIVERY_EVIDENCE_UNVERIFIABLE","medium","loads","Delivered load has no evidence proving it used the Phase 1F lifecycle",load,action="Classify legacy provenance before pilot; do not infer modern corruption"))
    invoice_by_id={x.get("id"):x for x in invoices if x.get("id")}; package_by_id={x.get("id"):x for x in packages if x.get("id")}
    readiness_by_id={x.get("id"):x for x in readiness if x.get("id")}
    for case in readiness:
        invoice_id=case.get("invoice_id"); package_id=case.get("invoice_package_id")
        inv=invoice_by_id.get(invoice_id) if invoice_id else None; package=package_by_id.get(package_id) if package_id else None
        if case.get("status")=="invoiced" and not invoice_id:add(_finding("INVOICED_READINESS_INVOICE_ID_MISSING","critical","invoice_readiness_cases","Invoiced readiness lacks its exact modern invoice_id",case))
        if invoice_id and not inv:add(_finding("READINESS_INVOICE_MISSING","critical","invoice_readiness_cases","readiness.invoice_id does not resolve",case))
        if inv:
            if inv.get("tenant_id")!=case.get("tenant_id") or inv.get("load_id")!=case.get("load_id"):add(_finding("READINESS_INVOICE_SCOPE_MISMATCH","critical","invoice_readiness_cases","Referenced invoice has different tenant or load",case))
            if inv.get("readiness_case_id")!=case.get("id"):add(_finding("READINESS_INVOICE_RECIPROCITY_MISMATCH","critical","invoice_readiness_cases","Invoice does not point back to readiness",case))
        if package_id and not package:add(_finding("READINESS_PACKAGE_MISSING","critical","invoice_readiness_cases","Readiness references a missing package",case))
        if package:
            if package.get("tenant_id")!=case.get("tenant_id") or package.get("load_id")!=case.get("load_id"):add(_finding("READINESS_PACKAGE_SCOPE_MISMATCH","critical","invoice_readiness_cases","Referenced package has different tenant or load",case))
            if package.get("readiness_case_id")!=case.get("id"):add(_finding("PACKAGE_READINESS_RECIPROCITY_MISMATCH","critical","invoice_packages","Package does not point back to readiness",package))
            if invoice_id and package.get("invoice_id")!=invoice_id:add(_finding("PACKAGE_INVOICE_RECIPROCITY_MISMATCH","critical","invoice_packages","Package invoice_id does not match readiness invoice_id",package))
        if inv and package_id and inv.get("package_id")!=package_id:add(_finding("INVOICE_PACKAGE_RECIPROCITY_MISMATCH","critical","invoices","Invoice package_id does not match readiness package",inv))
        if inv and package:
            values=[case.get("financial_basis_fingerprint"),package.get("financial_basis_fingerprint"),inv.get("financial_basis_fingerprint")]
            comparable=[v for v in values if isinstance(v,str) and v]
            if len(comparable)>=2 and len(set(comparable))>1:add(_finding("FINANCIAL_BASIS_FINGERPRINT_MISMATCH","critical","invoice_readiness_cases","Comparable Phase 1G financial basis fingerprints disagree",case))
            elif len(comparable)<3:add(_finding("FINANCIAL_BASIS_NOT_COMPARABLE","medium","invoice_readiness_cases","One or more modern authority records lacks a comparable financial basis fingerprint",case))
    for inv in invoices:
        if not inv.get("readiness_case_id"):add(_finding("LEGACY_INVOICE_AUTHORITY","high","invoices","Invoice lacks Phase 1G readiness authority",inv))
        else:
            case=readiness_by_id.get(inv.get("readiness_case_id"))
            if not case:add(_finding("INVOICE_READINESS_MISSING","critical","invoices","Modern invoice readiness_case_id does not resolve",inv))
            elif case.get("tenant_id")!=inv.get("tenant_id") or case.get("load_id")!=inv.get("load_id"):add(_finding("INVOICE_READINESS_SCOPE_MISMATCH","critical","invoices","Invoice and readiness differ by tenant or load",inv))
        if inv.get("package_id"):
            package=package_by_id.get(inv.get("package_id"))
            if not package:add(_finding("INVOICE_PACKAGE_MISSING","critical","invoices","Invoice package_id does not resolve",inv))
            elif package.get("invoice_id")!=inv.get("id"):add(_finding("PACKAGE_INVOICE_RECIPROCITY_MISMATCH","critical","invoice_packages","Package does not point back to invoice",package))
        load=loads.get((inv.get("tenant_id"),inv.get("load_id")))
        if load and load.get("invoice_status") and inv.get("status") and load.get("invoice_status")!=inv.get("status"):add(_finding("INVOICE_STATUS_DISAGREEMENT","high","invoices","Legacy load invoice status disagrees with invoice",inv))
    for tenant_load in {(x.get("tenant_id"),x.get("load_id")) for x in invoices}:
        same=[x for x in invoices if (x.get("tenant_id"),x.get("load_id"))==tenant_load]
        if any(x.get("readiness_case_id") for x in same) and any(not x.get("readiness_case_id") for x in same):add(_finding("LEGACY_MODERN_INVOICE_AUTHORITY_CONFLICT","critical","invoices","Load has both legacy and modern invoice authority",same[0],len(same),"Resolve canonical invoice authority in Phase 2C"))
    findings.sort(key=lambda x:(SEVERITIES.index(x.severity),x.code,x.collection,x.tenant_id or "",x.entity_id or ""))
    counts=Counter(x.severity for x in findings); total=sum(len(v) for v in records.values())
    timestamp=generated_at or datetime.now(timezone.utc).isoformat()
    fingerprint=json.dumps({k:[dict(x) for x in v] for k,v in sorted(records.items())},sort_keys=True,default=str)
    detected=len(findings); retained=findings[:max_findings]
    summary={s:counts[s] for s in SEVERITIES};summary.update({"total_detected_findings":detected,"returned_findings":len(retained),"total_findings":detected,"severity_counts_scope":"all_detected","records_scanned":total,"truncated":detected>max_findings})
    migration={"tenant_backfill_required":sum(x.code=="TENANT_MISSING" for x in findings),"duplicate_cleanup_required":sum(x.code=="INDEX_COLLISION" for x in findings),"orphan_cleanup_required":sum(x.code in {"ORPHAN_REFERENCE","CROSS_TENANT_REFERENCE"} for x in findings),"unsupported_document_types":sum(x.code=="DOCUMENT_TYPE_UNSUPPORTED" for x in findings),"version_lifecycle_gaps":sum(x.code=="VERSION_MISSING" for x in findings),"legacy_invoice_authority":sum(x.code=="LEGACY_INVOICE_AUTHORITY" for x in findings),"active_case_duplicates":sum(x.code=="INDEX_COLLISION" and x.collection.endswith(("cases","sessions","passports")) for x in findings),"index_collisions":sum(x.code=="INDEX_COLLISION" for x in findings)}
    return {"report_id":"pir_"+hashlib.sha256(fingerprint.encode()).hexdigest()[:16],"generated_at":timestamp,"environment":environment,"checks_run":["tenant_integrity","relationships","index_collisions","legacy_versions","invoice_authority","execution_delivery","documents"],"summary":summary,"migration_readiness":migration,"findings":[asdict(x) for x in retained]}

SIMULATED_CAPABILITIES=(
 {"id":"routing","source":"/api/routing/calc","classification":"pilot_blocker","reachable_by_default":True,"runtime_gate":None},
 {"id":"weather","source":"/api/weather/check","classification":"pilot_blocker","reachable_by_default":True,"runtime_gate":None},
 {"id":"road_traffic","source":"/api/roads/check","classification":"pilot_blocker","reachable_by_default":True,"runtime_gate":None},
 {"id":"telematics_samsara","source":"/api/samsara/vehicle","classification":"pilot_blocker","reachable_by_default":True,"runtime_gate":None},
 {"id":"fuel_truck_stop","source":"/api/fuel/plan and /api/truckstops/plan","classification":"pilot_blocker","reachable_by_default":True,"runtime_gate":None},
 {"id":"random_dashboard","source":"dashboard/demo calculations","classification":"development_only","reachable_by_default":True,"runtime_gate":None},
 {"id":"mock_document_storage","source":"DocumentCreate mock:// support","classification":"pilot_blocker","reachable_by_default":True,"runtime_gate":None},
 {"id":"seed_data","source":"POST /api/seed","classification":"development_only","reachable_by_default":False,"runtime_gate":"ALLOW_SEED_ENDPOINT"},)

def evaluate_environment(config: Mapping[str,Any]):
    env=str(config.get("APP_ENV","")).lower(); prod=env in {"production","staging","pilot"}; findings=[]
    def item(code,state,description,severity="high"): findings.append({"code":code,"state":state,"severity":severity,"description":description})
    item("APP_ENV","configured" if env else "missing","Explicit environment name")
    secret=str(config.get("JWT_SECRET","")).strip(); item("JWT_SECRET","configured" if len(secret)>=32 else "missing","Strong JWT secret configured", "critical")
    item("MONGO_CONFIG","configured" if config.get("MONGO_URL") and config.get("DB_NAME") else "missing","Mongo connection configuration present","critical")
    cors=str(config.get("CORS_ORIGINS","")).strip(); item("CORS","unsafe" if not cors or "*" in cors else "configured","Explicit CORS origins","critical")
    seed=str(config.get("ALLOW_SEED_ENDPOINT","false")).lower() in {"1","true","yes","on"}; item("SEED_ENDPOINT","unsafe" if prod and seed else "configured","Seed endpoint disabled for production-like environments","critical")
    frontend=str(config.get("FRONTEND_BACKEND_URL","")).strip(); item("FRONTEND_BACKEND_URL","configured" if frontend else "missing","Frontend backend URL explicit","medium")
    capabilities=[]
    for cap in SIMULATED_CAPABILITIES:
        gate=cap["runtime_gate"]
        reachable=cap["reachable_by_default"] if gate is None else str(config.get(gate,"false")).lower() in {"1","true","yes","on"}
        capabilities.append({**cap,"reachable":reachable,"pilot_impact":"blocks_pilot" if reachable and cap["classification"]=="pilot_blocker" else "explicit_demo_behavior"})
        if prod and reachable and cap["classification"]=="pilot_blocker":item("SIMULATED_CAPABILITY_REACHABLE","unsafe",f'{cap["id"]} simulation is reachable at {cap["source"]}',"critical")
    return {"environment":env or "unknown","settings":findings,"simulated_capabilities":capabilities}

def evaluate_production_readiness(environment_report, integrity_report=None, index_report=None):
    critical=sum(x["severity"]=="critical" and x["state"] in {"missing","unsafe"} for x in environment_report["settings"])
    critical+=int((integrity_report or {}).get("summary",{}).get("critical",0))
    unknown=index_report is None
    if index_report: critical+=sum(x.get("priority")=="P0" for x in index_report.get("missing",()))+len(index_report.get("mismatched",()))
    status="FAIL" if critical else "WARN" if unknown or any(x["state"]!="configured" for x in environment_report["settings"]) else "PASS"
    return {"status":status,"critical_blockers":critical,"index_verification":"UNKNOWN" if unknown else "VERIFIED" if not index_report.get("missing") and not index_report.get("mismatched") else "DIFFERENT","production_certified":False}
