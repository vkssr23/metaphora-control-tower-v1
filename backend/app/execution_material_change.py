"""Conservative Phase 1F control performed before canonical load mutation."""
import secrets
from datetime import datetime,timezone,timedelta
from fastapi import HTTPException
from app.audit import begin_audit
from app.schemas.audit import AuditEntityType
from app.tenant import tenant_document,tenant_filter
from app.domain.in_transit_execution import MATERIAL_CONTROL_ACTIVE,detect_material_load_change

def utc_now(): return datetime.now(timezone.utc).isoformat()

async def control_material_load_change(db,user,load,updates):
    sessions=getattr(db,"execution_sessions",None)
    if sessions is None:return None
    candidates=await sessions.find(tenant_filter(user,{"load_id":load["id"]}),{"_id":0}).sort([("updated_at",-1),("id",-1)]).to_list(20)
    session=next((s for s in candidates if s.get("status") in MATERIAL_CONTROL_ACTIVE),None)
    plan=detect_material_load_change(load,updates,session,(session or {}).get("planned_snapshot"))
    if not plan["is_material"]:return plan
    stamp=utc_now();sid=session["id"];changed=plan["changed_field_names"];eid="exc_"+secrets.token_hex(12);event_id="exe_"+secrets.token_hex(12)
    audit=await begin_audit(db.audit_events,user,"execution_session.material_change_detected",AuditEntityType.EXECUTION_SESSION,sid,changed_fields=changed+["version","execution_health"],previous=session)
    update={"status":"exception","execution_health":"at_risk","open_exception_count":session.get("open_exception_count",0)+1,"version":session["version"]+1,"updated_at":stamp,"updated_by":user["id"],"last_material_change_at":stamp}
    try:controlled=await sessions.update_one(tenant_filter(user,{"id":sid,"status":session["status"],"version":session["version"]}),{"$set":update})
    except Exception:await audit.failed("session_control_failed");raise HTTPException(503,"Execution material-change control unavailable")
    if not controlled.matched_count:await audit.rejected("version_conflict");raise HTTPException(409,"Execution session changed concurrently; load was not updated")
    event=tenant_document(user,{"id":event_id,"execution_session_id":sid,"load_id":load["id"],"type":"material_change_detected","occurred_at":stamp,"recorded_at":stamp,"actor_id":user["id"],"actor_role":user["role"],"source":"system","summary":"Canonical load material change requires execution plan review","structured_data":{"changed_field_names":changed,"affected_execution_domains":plan["affected_execution_domains"],"reason_code":plan["reason_code"]},"related_exception_id":eid,"related_document_ids":[],"session_version":session["version"]+1,"previous_state":session.get("execution_state"),"resulting_state":session.get("execution_state")})
    role=user.get("role") if user.get("role") in {"operations","dispatcher","owner","admin"} else "operations"
    exception=tenant_document(user,{"id":eid,"execution_session_id":sid,"load_id":load["id"],"type":"execution_plan_material_change","category":"assignment" if "assignment" in plan["affected_execution_domains"] else "delivery" if "delivery" in plan["affected_execution_domains"] else "other","severity":plan["exception_severity"],"status":"open","blocking":True,"title":"Execution plan material change","summary":"Review required for changed canonical fields: "+", ".join(changed),"changed_field_names":changed,"detected_at":stamp,"detected_by":user["id"],"source":"system","owner_user_id":user["id"],"owner_role":role,"assigned_at":stamp,"acknowledged_at":None,"acknowledged_by":None,"resolved_at":None,"resolved_by":None,"resolution":"","resolution_reason":"","sla_due_at":(datetime.now(timezone.utc)+timedelta(hours=4 if plan["exception_severity"]=="high" else 12)).isoformat(),"escalated_at":None,"escalation_level":0,"related_event_ids":[event_id],"related_document_ids":[],"version":1})
    try:await db.execution_events.insert_one(event);await db.execution_exceptions.insert_one(exception)
    except Exception:await audit.failed("evidence_write_failed");raise HTTPException(503,"Execution material-change evidence could not be recorded")
    await audit.succeeded({"id":sid,"status":"exception","version":session["version"]+1,"changed_field_names":changed})
    return {**plan,"session_id":sid,"event_id":event_id,"exception_id":eid}
