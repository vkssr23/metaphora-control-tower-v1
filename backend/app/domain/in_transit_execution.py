"""Pure Phase 1F execution policy. No external-data claims are made here."""
from datetime import datetime, timezone

TRANSITIONS={
 "pending_start":{"active"},"active":{"paused","delivery_arrived","exception"},
 "paused":{"active","exception"},"exception":{"active","paused","delivery_arrived"},
 "delivery_arrived":{"delivery_confirmed","exception"},
 "delivery_confirmed":{"completed","exception"},"completed":set(),"cancelled":set(),
}
TERMINAL={"completed","cancelled"}
EXECUTION_SESSION_STATUSES=frozenset(TRANSITIONS)
CURRENT_EXECUTION_SESSION_STATUSES=EXECUTION_SESSION_STATUSES-frozenset(TERMINAL)
MATERIAL_CONTROL_ACTIVE={"active","paused","exception","delivery_arrived"}
FUTURE_SOURCES={"system","future_driver_app","future_telematics","future_eld","future_broker_tracking","future_shipper_tracking","future_weather","future_maps"}
MATERIAL_FIELD_DOMAINS={"driver_id":"assignment","truck_id":"assignment","trailer_identifier":"assignment","delivery_address":"delivery","delivery_city":"delivery","delivery_state":"delivery","delivery_zip":"delivery","delivery_appt":"delivery","pickup_address":"appointment","pickup_city":"appointment","pickup_state":"appointment","pickup_zip":"appointment","pickup_appt":"appointment","equipment_type":"equipment","commodity":"commodity","weight":"cargo","miles":"mileage","deadhead_miles":"mileage","est_drive_hours":"mileage","stage":"stage"}
MATERIAL_FIELDS={field:(field+"_changed" if field in {"driver_id","truck_id","trailer_identifier"} else domain+"_changed") for field,domain in MATERIAL_FIELD_DOMAINS.items()}
SEVERITY_HEALTH={"critical":"critical","high":"at_risk","warning":"watch","info":"healthy"}

def parse_time(value):
    if not value:return None
    try:return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(timezone.utc)
    except (ValueError,TypeError):return None

def eta_evaluation(planned_arrival,manual_eta,evaluated_at):
    planned=parse_time(planned_arrival); current=parse_time(manual_eta); now=parse_time(evaluated_at)
    out={"planned_arrival":planned_arrival or None,"current_eta":manual_eta or None,"eta_source":"manual" if current else "unknown","variance_minutes":None,"status":"unknown","evaluated_at":evaluated_at}
    if not planned or not current or not now:return out
    variance=round((current-planned).total_seconds()/60)
    out["variance_minutes"]=variance
    out["status"]="on_time" if variance<=15 else "at_risk" if variance<=30 else "late"
    return out

def delay_evaluation(appointment,current_eta,reported_delay=0,arrived=False,detention=False,as_of=None):
    eta=eta_evaluation(appointment,current_eta,as_of)
    minutes=max(0,reported_delay or 0,eta.get("variance_minutes") or 0)
    reason="detention" if detention else "driver_reported_delay" if reported_delay else "eta_variance" if minutes else None
    severity="high" if minutes>30 else "warning" if minutes>15 else "info"
    return {"delay_state":"arrived" if arrived else "delayed" if minutes else "none","delay_minutes":minutes,"severity":severity,"reason_code":reason,"exception_required":minutes>15 or detention}

def sla_state(due_at,now):
    due=parse_time(due_at); current=parse_time(now)
    if not due or not current:return "unknown"
    delta=(due-current).total_seconds()/60
    return "overdue" if delta<0 else "due_soon" if delta<=30 else "within_sla"

def execution_health(exceptions,now):
    open_items=[x for x in exceptions if x.get("status") not in {"resolved","waived","closed"}]
    if not open_items:return "healthy"
    health=max((SEVERITY_HEALTH.get(x.get("severity"),"healthy") for x in open_items),key=lambda x:{"healthy":0,"watch":1,"at_risk":2,"critical":3}[x])
    if any(sla_state(x.get("sla_due_at"),now)=="overdue" for x in open_items) and health=="healthy":return "watch"
    return health

def detention_minutes(start,end):
    a=parse_time(start); b=parse_time(end)
    if not a or not b or b<a: raise ValueError("Invalid detention timestamps")
    return int((b-a).total_seconds()//60)

def route_status(requested,source="manual"):
    if requested=="confirmed_deviation" and source=="manual": raise ValueError("Manual evidence cannot confirm route deviation")
    return requested

def material_changes(old,new):
    return sorted({kind for field,kind in MATERIAL_FIELDS.items() if field in new and old.get(field)!=new.get(field)})

def detect_material_load_change(observed,proposed,session=None,planned_snapshot=None):
    """Return a deterministic value-aware control plan without mutating inputs."""
    changed=sorted(field for field in MATERIAL_FIELD_DOMAINS if field in proposed and observed.get(field)!=proposed.get(field))
    domains=sorted({MATERIAL_FIELD_DOMAINS[field] for field in changed})
    severity="high" if set(domains)&{"assignment","delivery","appointment","equipment","commodity","cargo","stage"} else "warning"
    material=bool(changed) and bool(session and session.get("status") in MATERIAL_CONTROL_ACTIVE)
    return {"is_material":material,"changed_field_names":changed,"affected_execution_domains":domains,"exception_required":material,"plan_amendment_required":material,"health_impact":"at_risk" if material else "none","exception_severity":severity if material else None,"event_type":"material_change_detected" if material else None,"reason_code":"execution_plan_material_change" if material else "no_active_material_change","preserve_planned_snapshot":True}

def completion_readiness(session,exceptions,pod_present):
    reasons=[]
    if session.get("status")!="delivery_confirmed":reasons.append("delivery_confirmation_required")
    if not pod_present:reasons.append("pod_required")
    if any(x.get("status") not in {"resolved","waived","closed"} and (x.get("blocking") or x.get("severity")=="critical") for x in exceptions):reasons.append("blocking_exception")
    if session.get("custody_state") not in {"delivery_confirmed","completed"}:reasons.append("custody_state_invalid")
    return {"ready":not reasons,"reasons":reasons}

def select_current_pickup_release(cases):
    """Select the deterministic current Phase 1E case or return a fail-closed reason."""
    if not cases:return None,"pickup_confirmation_required"
    ranked=sorted(cases,key=lambda c:(str(c.get("updated_at") or c.get("created_at") or ""),int(c.get("version") or 0),str(c.get("id") or "")),reverse=True)
    newest=ranked[0];rank=lambda c:(str(c.get("updated_at") or c.get("created_at") or ""),int(c.get("version") or 0))
    if len(ranked)>1 and rank(ranked[0])==rank(ranked[1]):return None,"pickup_release_ambiguous"
    if newest.get("status")!="pickup_confirmed":return None,"pickup_release_not_current"
    return newest,None

def owner_role_allowed(category,role):
    if role in {"owner","admin"}:return True
    allowed={"timing":{"operations","dispatcher"},"detention":{"operations","dispatcher"},"communication":{"operations","dispatcher"},"delivery":{"operations","dispatcher"},"driver":{"safety","compliance"},"compliance":{"safety","compliance"},"truck":{"operations","dispatcher","fleet"},"trailer":{"operations","dispatcher","fleet"},"assignment":{"operations","dispatcher"},"route":{"operations","dispatcher"},"custody":{"operations","dispatcher","safety","compliance"},"document":{"operations","dispatcher","finance"},"other":{"operations","dispatcher"}}
    return role in allowed.get(category,set())
