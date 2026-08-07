import secrets
from datetime import datetime,timezone,timedelta
from fastapi import Depends,HTTPException,Query,status
from app.audit import begin_audit
from app.schemas.audit import AuditEntityType
from app.schemas.in_transit_execution import *
from app.tenant import tenant_document,tenant_filter,require_tenant_id
from app.domain.in_transit_execution import TRANSITIONS,TERMINAL,eta_evaluation,delay_evaluation,detention_minutes,execution_health,completion_readiness,select_current_pickup_release,owner_role_allowed

ADMIN={"owner","admin"}; OPS=ADMIN|{"operations","dispatcher"}; REVIEW=OPS|{"safety","compliance"}
def now(): return datetime.now(timezone.utc).isoformat()
def clean(x):
    if x:x.pop("_id",None)
    return x
def permit(user,roles):
    require_tenant_id(user)
    if user.get("role") not in roles:raise HTTPException(403,"Insufficient permission")
async def get_one(col,user,rid,label):
    item=await col.find_one(tenant_filter(user,{"id":rid}),{"_id":0})
    if not item:raise HTTPException(404,f"{label} not found")
    return clean(item)
async def append_event(db,user,s,event_type,summary,data=None,previous=None,resulting=None,related_exception_id=None,source="system",at=None):
    stamp=at or now();event=tenant_document(user,{"id":"exe_"+secrets.token_hex(12),"execution_session_id":s["id"],"load_id":s["load_id"],"type":event_type,"occurred_at":stamp,"recorded_at":stamp,"actor_id":user["id"],"actor_role":user["role"],"source":source,"summary":summary[:500],"structured_data":data or {},"related_exception_id":related_exception_id,"related_document_ids":[],"session_version":s["version"]+1,"previous_state":previous or s.get("execution_state"),"resulting_state":resulting or s.get("execution_state")})
    await db.execution_events.insert_one(event); return clean(event)
async def save(db,user,s,updates,audit,at=None):
    stamp=at or now(); updates={**updates,"version":s["version"]+1,"updated_at":stamp,"updated_by":user["id"],"last_material_change_at":stamp}
    try:r=await db.execution_sessions.update_one(tenant_filter(user,{"id":s["id"],"status":s["status"],"version":s["version"]}),{"$set":updates})
    except Exception:await audit.failed();raise HTTPException(500,"Database operation failed")
    if not r.matched_count:await audit.rejected("version_conflict");raise HTTPException(409,"Execution session changed concurrently")
    await audit.succeeded({"id":s["id"],"status":updates.get("status",s["status"]),"version":updates["version"]})
    return await get_one(db.execution_sessions,user,s["id"],"Execution session")
def planned(load,passport,release):
    return {"load_id":load["id"],"pickup":{"address":load.get("pickup_address"),"city":load.get("pickup_city"),"state":load.get("pickup_state"),"appointment":load.get("pickup_appt")},"delivery":{"address":load.get("delivery_address"),"city":load.get("delivery_city"),"state":load.get("delivery_state"),"appointment":load.get("delivery_appt")},"pickup_confirmed_at":release.get("pickup_confirmed_at"),"loaded_miles":load.get("miles"),"deadhead_miles":load.get("deadhead_miles"),"driver_id":load.get("driver_id"),"truck_id":load.get("truck_id"),"trailer_identifier":(release.get("assignment_snapshot") or {}).get("trailer_identifier"),"equipment":load.get("equipment_type"),"commodity":load.get("commodity"),"weight":load.get("weight"),"release_case_id":release["id"],"release_case_version":release["version"],"passport_id":passport["id"],"passport_version":passport["version"],"custody_state":release.get("custody_state")}

def register_in_transit_execution_routes(api,db,get_current_user):
 @api.get("/execution-sessions")
 async def listing(load_id:str|None=None,limit:int=Query(100,ge=1,le=200),user=Depends(get_current_user)):
  return await db.execution_sessions.find(tenant_filter(user,{"load_id":load_id} if load_id else {}),{"_id":0}).sort([("updated_at",-1),("id",-1)]).to_list(limit)
 @api.get("/execution-sessions/{sid}")
 async def get(sid:str,user=Depends(get_current_user)):return await get_one(db.execution_sessions,user,sid,"Execution session")
 @api.get("/loads/{lid}/execution-session")
 async def by_load(lid:str,user=Depends(get_current_user)):
  if not await db.loads.find_one(tenant_filter(user,{"id":lid}),{"_id":0}):raise HTTPException(404,"Load not found")
  s=await db.execution_sessions.find_one(tenant_filter(user,{"load_id":lid,"status":{"$nin":["completed","cancelled"]}}),{"_id":0})
  if not s:raise HTTPException(404,"Execution session not found")
  return clean(s)
 @api.post("/loads/{lid}/execution-session/start",status_code=status.HTTP_201_CREATED)
 async def start(lid:str,data:StartAction,user=Depends(get_current_user)):
  permit(user,OPS); load=await db.loads.find_one(tenant_filter(user,{"id":lid}),{"_id":0})
  if not load:raise HTTPException(404,"Load not found")
  existing=await db.execution_sessions.find(tenant_filter(user,{"load_id":lid}),{"_id":0}).sort([("updated_at",-1),("id",-1)]).to_list(20)
  if any(x.get("status") not in TERMINAL for x in existing):raise HTTPException(409,"An active execution session already exists")
  release_cases=await db.pickup_release_cases.find(tenant_filter(user,{"load_id":lid}),{"_id":0}).sort([("updated_at",-1),("id",-1)]).to_list(20)
  release,release_reason=select_current_pickup_release(release_cases)
  if not release:raise HTTPException(409,release_reason)
  passport=await db.load_passports.find_one(tenant_filter(user,{"id":release.get("passport_id")}),{"_id":0})
  if not passport:raise HTTPException(409,"pickup_release_not_current")
  if release.get("custody_state")!="pickup_confirmed" or (passport.get("pickup_authorization") or {}).get("status")!="consumed":raise HTTPException(409,"custody_state_invalid")
  snap=release.get("assignment_snapshot") or {}
  if snap.get("driver_id")!=load.get("driver_id") or snap.get("truck_id")!=load.get("truck_id"):raise HTTPException(409,"assignment_changed_after_pickup")
  if load.get("stage") not in {"Loaded","In Transit"}:raise HTTPException(409,"load_stage_not_ready")
  stamp=now(); sid="exs_"+secrets.token_hex(12); p=planned(load,passport,release)
  doc=tenant_document(user,{"id":sid,"load_id":lid,"passport_id":passport["id"],"pickup_release_case_id":release["id"],"execution_eligibility_case_id":release.get("execution_eligibility_case_id"),"version":1,"status":"active","execution_state":"pickup_confirmed","created_at":stamp,"created_by":user["id"],"started_at":stamp,"started_by":user["id"],"updated_at":stamp,"updated_by":user["id"],"completed_at":None,"completed_by":None,"current_checkpoint":"pickup_confirmed","current_stop_index":0,"total_stops":2,"stops":[{"stop_index":0,"stop_type":"pickup","planned_location":p["pickup"],"planned_arrival":p["pickup"].get("appointment"),"planned_departure":None,"actual_arrival":release.get("pickup_confirmed_at"),"actual_departure":None,"status":"arrived","detention_state":"none","reference":""},{"stop_index":1,"stop_type":"delivery","planned_location":p["delivery"],"planned_arrival":p["delivery"].get("appointment"),"planned_departure":None,"actual_arrival":None,"actual_departure":None,"status":"pending","detention_state":"none","reference":""}],"planned_snapshot":p,"planning_history":[],"actual_snapshot":{},"eta_snapshot":{"status":"unknown","eta_source":"unknown"},"detention_snapshot":{"state":"none"},"route_progress_snapshot":{"route_status":"unknown","source":"manual"},"latest_event_at":stamp,"latest_event_id":None,"open_exception_count":0,"critical_exception_count":0,"execution_health":"healthy","custody_state":"pickup_confirmed","source_state":"manual","last_material_change_at":stamp})
  a=await begin_audit(db.audit_events,user,"execution_session.started",AuditEntityType.EXECUTION_SESSION,sid,changed_fields=["id","status","version","planned_snapshot"])
  try:await db.execution_sessions.insert_one(doc); ev=await append_event(db,user,{**doc,"version":0},"session_started","Execution session started",resulting="pickup_confirmed")
  except Exception:await a.failed();raise HTTPException(500,"Database operation failed")
  await db.execution_sessions.update_one(tenant_filter(user,{"id":sid,"version":1}),{"$set":{"latest_event_id":ev["id"]}});await a.succeeded(doc);return clean(doc)
 @api.post("/execution-sessions/{sid}/progress")
 async def progress(sid:str,data:Progress,user=Depends(get_current_user)):
  permit(user,OPS);s=await get_one(db.execution_sessions,user,sid,"Execution session")
  if s["version"]!=data.version:raise HTTPException(409,"Execution session changed concurrently")
  if s["status"] in TERMINAL:raise HTTPException(409,"Terminal session rejects progress")
  stamp=now(); actual={"current_location_text":data.current_location_text,"current_state_region":data.current_state_region,"remaining_miles_estimate":data.remaining_miles_estimate,"driver_reported_eta":data.driver_reported_eta or None,"delay_minutes_estimate":data.delay_minutes_estimate,"status_note":data.status_note,"source":"manual","reported_at":stamp,"verification":"operations_reported_not_gps_verified"}; route={"route_status":data.route_status,"source":"manual","verification":"not_route_verified"}; eta=eta_evaluation((s.get("planned_snapshot",{}).get("delivery") or {}).get("appointment"),data.driver_reported_eta,stamp)
  a=await begin_audit(db.audit_events,user,"execution_session.progress_reported",AuditEntityType.EXECUTION_SESSION,sid,changed_fields=["actual_snapshot","eta_snapshot","route_progress_snapshot","version"],previous=s); await append_event(db,user,s,"progress_reported","Manual operations progress reported",actual,source="manual")
  return await save(db,user,s,{"actual_snapshot":actual,"eta_snapshot":eta,"route_progress_snapshot":route,"latest_event_at":stamp,"execution_state":"in_transit"},a)
 async def simple_transition(sid,data,user,target,event,action,state=None):
  permit(user,OPS);s=await get_one(db.execution_sessions,user,sid,"Execution session")
  if s["version"]!=data.version:raise HTTPException(409,"Execution session changed concurrently")
  if target not in TRANSITIONS.get(s["status"],set()):raise HTTPException(409,"Invalid execution lifecycle transition")
  a=await begin_audit(db.audit_events,user,action,AuditEntityType.EXECUTION_SESSION,sid,changed_fields=["status","execution_state","version"],previous=s);await append_event(db,user,s,event,event.replace("_"," ").title(),previous=s["execution_state"],resulting=state or s["execution_state"])
  return await save(db,user,s,{"status":target,"execution_state":state or s["execution_state"]},a)
 @api.post("/execution-sessions/{sid}/pause")
 async def pause(sid:str,data:EmptyAction,user=Depends(get_current_user)):return await simple_transition(sid,data,user,"paused","session_paused","execution_session.paused")
 @api.post("/execution-sessions/{sid}/resume")
 async def resume(sid:str,data:EmptyAction,user=Depends(get_current_user)):return await simple_transition(sid,data,user,"active","session_resumed","execution_session.resumed")
 async def stop_action(sid,index,data,user,depart=False):
  permit(user,OPS);s=await get_one(db.execution_sessions,user,sid,"Execution session")
  if s["version"]!=data.version:raise HTTPException(409,"Execution session changed concurrently")
  stops=[dict(x) for x in s["stops"]]
  if index>=len(stops):raise HTTPException(404,"Stop not found")
  stop=stops[index];stamp=now()
  if depart:
   if stop["status"]!="arrived":raise HTTPException(409,"Stop must be arrived before departure")
   stop.update({"actual_departure":stamp,"status":"completed" if stop["stop_type"]=="delivery" else "departed","reference":data.reference})
  else:
   if index!=s["current_stop_index"] and not (index==1 and s["current_stop_index"]==0 and stops[0]["status"] in {"departed","completed"}):raise HTTPException(409,"Invalid stop order")
   if stop["status"]!="pending":raise HTTPException(409,"Stop cannot be arrived")
   stop.update({"actual_arrival":stamp,"status":"arrived","reference":data.reference})
  action="stop_departed" if depart else "stop_arrived";a=await begin_audit(db.audit_events,user,"execution_session."+action,AuditEntityType.EXECUTION_SESSION,sid,changed_fields=["stops","current_stop_index","version"],previous=s);await append_event(db,user,s,action,f"Manual stop {index} {action.split('_')[1]}",{"stop_index":index,"source":"manual","verification":"not_geofence_verified"},source="manual",at=stamp)
  return await save(db,user,s,{"stops":stops,"current_stop_index":min(index+(1 if depart else 0),len(stops)-1),"execution_state":"departed_pickup" if depart and index==0 else "arrived_delivery" if not depart and stop["stop_type"]=="delivery" else s["execution_state"]},a,at=stamp)
 @api.post("/execution-sessions/{sid}/stops/{index}/arrive")
 async def arrive(sid:str,index:int,data:StopAction,user=Depends(get_current_user)):return await stop_action(sid,index,data,user)
 @api.post("/execution-sessions/{sid}/stops/{index}/depart")
 async def depart(sid:str,index:int,data:StopAction,user=Depends(get_current_user)):return await stop_action(sid,index,data,user,True)
 @api.post("/execution-sessions/{sid}/detention/start")
 async def detention_start(sid:str,data:DetentionStart,user=Depends(get_current_user)):
  permit(user,OPS);s=await get_one(db.execution_sessions,user,sid,"Execution session")
  if s["version"]!=data.version:raise HTTPException(409,"Execution session changed concurrently")
  if s.get("detention_snapshot",{}).get("state")=="active":raise HTTPException(409,"Detention is already active")
  for did in data.supporting_document_ids:
   if not await db.documents.find_one(tenant_filter(user,{"id":did,"load_id":s["load_id"]}),{"_id":0}):raise HTTPException(404,"Evidence document not found")
  stamp=now();snap={"state":"active","stop_index":data.stop_index,"start_time":stamp,"end_time":None,"duration_minutes":None,"source":"manual","recorded_by":user["id"],"reason":data.reason,"supporting_document_ids":data.supporting_document_ids};a=await begin_audit(db.audit_events,user,"execution_session.detention_started",AuditEntityType.EXECUTION_SESSION,sid,changed_fields=["detention_snapshot","version"],previous=s);await append_event(db,user,s,"detention_started","Manual detention started",{"stop_index":data.stop_index,"source":"manual","verification":"not_automatically_verified"},source="manual",at=stamp);return await save(db,user,s,{"detention_snapshot":snap},a,at=stamp)
 @api.post("/execution-sessions/{sid}/detention/end")
 async def detention_end(sid:str,data:DetentionEnd,user=Depends(get_current_user)):
  permit(user,OPS);s=await get_one(db.execution_sessions,user,sid,"Execution session");snap=dict(s.get("detention_snapshot") or {})
  if s["version"]!=data.version:raise HTTPException(409,"Execution session changed concurrently")
  if snap.get("state")!="active":raise HTTPException(409,"No active detention")
  end=now()
  try:duration=detention_minutes(snap["start_time"],end)
  except ValueError as e:raise HTTPException(409,str(e))
  snap.update({"state":"ended","end_time":end,"duration_minutes":duration,"end_reason":data.reason});a=await begin_audit(db.audit_events,user,"execution_session.detention_ended",AuditEntityType.EXECUTION_SESSION,sid,changed_fields=["detention_snapshot","version"],previous=s);await append_event(db,user,s,"detention_ended","Manual detention ended",{"duration_minutes":duration,"source":"manual"},source="manual",at=end);return await save(db,user,s,{"detention_snapshot":snap},a,at=end)
 @api.post("/execution-sessions/{sid}/eta/evaluate")
 async def eta(sid:str,data:EtaEvaluate,user=Depends(get_current_user)):
  permit(user,OPS);s=await get_one(db.execution_sessions,user,sid,"Execution session")
  if s["version"]!=data.version:raise HTTPException(409,"Execution session changed concurrently")
  stamp=now();planned=(s.get("planned_snapshot",{}).get("delivery") or {}).get("appointment");result=eta_evaluation(planned,data.manual_eta,stamp);delay=delay_evaluation(planned,data.manual_eta,(s.get("actual_snapshot") or {}).get("delay_minutes_estimate",0),detention=(s.get("detention_snapshot") or {}).get("state")=="active",as_of=stamp);a=await begin_audit(db.audit_events,user,"execution_session.eta_evaluated",AuditEntityType.EXECUTION_SESSION,sid,changed_fields=["eta_snapshot","version"],previous=s);await append_event(db,user,s,"eta_updated","Internal ETA evaluated",{**result,"delay":delay},source="system",at=stamp);return await save(db,user,s,{"eta_snapshot":result,"delay_snapshot":delay},a,at=stamp)
 @api.get("/execution-sessions/{sid}/events")
 async def events(sid:str,limit:int=Query(200,ge=1,le=500),user=Depends(get_current_user)):
  await get_one(db.execution_sessions,user,sid,"Execution session");return await db.execution_events.find(tenant_filter(user,{"execution_session_id":sid}),{"_id":0}).sort([("occurred_at",1),("id",1)]).to_list(limit)
 @api.get("/execution-sessions/{sid}/exceptions")
 async def exceptions(sid:str,limit:int=Query(200,ge=1,le=500),user=Depends(get_current_user)):
  await get_one(db.execution_sessions,user,sid,"Execution session");return await db.execution_exceptions.find(tenant_filter(user,{"execution_session_id":sid}),{"_id":0}).sort([("detected_at",-1),("id",-1)]).to_list(limit)
 @api.post("/execution-sessions/{sid}/exceptions",status_code=201)
 async def create_exception(sid:str,data:ExceptionCreate,user=Depends(get_current_user)):
  permit(user,REVIEW);s=await get_one(db.execution_sessions,user,sid,"Execution session")
  if s["version"]!=data.version:raise HTTPException(409,"Execution session changed concurrently")
  owner=None
  if data.owner_user_id:
   owner=await db.users.find_one(tenant_filter(user,{"id":data.owner_user_id}),{"_id":0})
   if not owner:raise HTTPException(404,"Owner not found")
   if not owner_role_allowed(data.category,owner.get("role")):raise HTTPException(409,"Owner role is not permitted for exception category")
  if data.severity in {"high","critical"} and not owner:raise HTTPException(422,"High and critical exceptions require an owner")
  for did in data.related_document_ids:
   if not await db.documents.find_one(tenant_filter(user,{"id":did,"load_id":s["load_id"]}),{"_id":0}):raise HTTPException(404,"Evidence document not found")
  stamp=now();eid="exc_"+secrets.token_hex(12);sla_hours={"critical":1,"high":4,"warning":12,"info":24}[data.severity];doc=tenant_document(user,{"id":eid,"execution_session_id":sid,"load_id":s["load_id"],"type":data.type,"category":data.category,"severity":data.severity,"status":"open","blocking":data.blocking,"title":data.title,"summary":data.summary,"detected_at":stamp,"detected_by":user["id"],"source":"manual","owner_user_id":data.owner_user_id,"owner_role":owner.get("role") if owner else None,"assigned_at":stamp if data.owner_user_id else None,"acknowledged_at":None,"acknowledged_by":None,"resolved_at":None,"resolved_by":None,"resolution":"","resolution_reason":"","sla_due_at":(datetime.now(timezone.utc)+timedelta(hours=sla_hours)).isoformat(),"escalated_at":None,"escalation_level":0,"related_event_ids":[],"related_document_ids":data.related_document_ids,"version":1})
  a=await begin_audit(db.audit_events,user,"execution_exception.created",AuditEntityType.EXECUTION_EXCEPTION,eid,changed_fields=["id","status","severity","version"]);await db.execution_exceptions.insert_one(doc);ev=await append_event(db,user,s,"exception_opened",data.title,{"severity":data.severity},related_exception_id=eid,source="manual");doc["related_event_ids"]=[ev["id"]];await db.execution_exceptions.update_one(tenant_filter(user,{"id":eid,"version":1}),{"$set":{"related_event_ids":[ev["id"]]}});await db.execution_sessions.update_one(tenant_filter(user,{"id":sid,"version":s["version"]}),{"$set":{"open_exception_count":s.get("open_exception_count",0)+1,"critical_exception_count":s.get("critical_exception_count",0)+(data.severity=="critical"),"execution_health":"critical" if data.severity=="critical" else "at_risk" if data.severity=="high" else "watch","version":s["version"]+1,"updated_at":stamp,"updated_by":user["id"]}});await a.succeeded(doc);return clean(doc)
 async def exception_action(eid,data,user,target,action,event):
  e=await get_one(db.execution_exceptions,user,eid,"Execution exception");s=await get_one(db.execution_sessions,user,e["execution_session_id"],"Execution session")
  if e["version"]!=data.version:raise HTTPException(409,"Exception changed concurrently")
  stamp=now();u={"status":target,"version":e["version"]+1}
  if target=="acknowledged":u.update({"acknowledged_at":stamp,"acknowledged_by":user["id"]})
  if target in {"resolved","waived"}:u.update({"resolved_at":stamp,"resolved_by":user["id"],"resolution":target,"resolution_reason":data.reason})
  a=await begin_audit(db.audit_events,user,action,AuditEntityType.EXECUTION_EXCEPTION,eid,changed_fields=list(u),previous=e);r=await db.execution_exceptions.update_one(tenant_filter(user,{"id":eid,"version":e["version"],"status":e["status"]}),{"$set":u})
  if not r.matched_count:await a.rejected("version_conflict");raise HTTPException(409,"Exception changed concurrently")
  await append_event(db,user,s,event,event.replace("_"," ").title(),related_exception_id=eid);await a.succeeded(u);return await get_one(db.execution_exceptions,user,eid,"Execution exception")
 @api.put("/execution-exceptions/{eid}/acknowledge")
 async def ack(eid:str,data:ExceptionAction,user=Depends(get_current_user)):permit(user,REVIEW);return await exception_action(eid,data,user,"acknowledged","execution_exception.acknowledged","exception_acknowledged")
 @api.put("/execution-exceptions/{eid}/resolve")
 async def resolve(eid:str,data:ExceptionAction,user=Depends(get_current_user)):permit(user,REVIEW);return await exception_action(eid,data,user,"resolved","execution_exception.resolved","exception_resolved")
 @api.put("/execution-exceptions/{eid}/waive")
 async def waive(eid:str,data:ExceptionAction,user=Depends(get_current_user)):
  permit(user,ADMIN)
  if not data.reason:raise HTTPException(422,"Waiver reason is required")
  return await exception_action(eid,data,user,"waived","execution_exception.waived","exception_resolved")
 @api.put("/execution-exceptions/{eid}/assign")
 async def assign(eid:str,data:AssignException,user=Depends(get_current_user)):
  permit(user,REVIEW);e=await get_one(db.execution_exceptions,user,eid,"Execution exception")
  if e["version"]!=data.version:raise HTTPException(409,"Exception changed concurrently")
  owner=await db.users.find_one(tenant_filter(user,{"id":data.owner_user_id}),{"_id":0})
  if not owner:raise HTTPException(404,"Owner not found")
  if not owner_role_allowed(e["category"],owner.get("role")):raise HTTPException(409,"Owner role is not permitted for exception category")
  stamp=now();a=await begin_audit(db.audit_events,user,"execution_exception.assigned",AuditEntityType.EXECUTION_EXCEPTION,eid,changed_fields=["owner_user_id","owner_role","version"],previous=e);r=await db.execution_exceptions.update_one(tenant_filter(user,{"id":eid,"version":e["version"]}),{"$set":{"owner_user_id":data.owner_user_id,"owner_role":owner["role"],"assigned_at":stamp,"version":e["version"]+1}})
  if not r.matched_count:await a.rejected("version_conflict");raise HTTPException(409,"Exception changed concurrently")
  await a.succeeded();return await get_one(db.execution_exceptions,user,eid,"Execution exception")
 @api.put("/execution-exceptions/{eid}/escalate")
 async def escalate(eid:str,data:ExceptionAction,user=Depends(get_current_user)):
  permit(user,REVIEW);e=await get_one(db.execution_exceptions,user,eid,"Execution exception")
  if e["version"]!=data.version:raise HTTPException(409,"Exception changed concurrently")
  stamp=now();a=await begin_audit(db.audit_events,user,"execution_exception.escalated",AuditEntityType.EXECUTION_EXCEPTION,eid,changed_fields=["escalation_level","version"],previous=e);r=await db.execution_exceptions.update_one(tenant_filter(user,{"id":eid,"version":e["version"]}),{"$set":{"escalation_level":e.get("escalation_level",0)+1,"escalated_at":stamp,"version":e["version"]+1}})
  if not r.matched_count:await a.rejected("version_conflict");raise HTTPException(409,"Exception changed concurrently")
  await a.succeeded();return await get_one(db.execution_exceptions,user,eid,"Execution exception")
 @api.post("/execution-sessions/{sid}/delivery-arrive")
 async def delivery_arrive(sid:str,data:StopAction,user=Depends(get_current_user)):
  s=await stop_action(sid,len((await get_one(db.execution_sessions,user,sid,"Execution session"))["stops"])-1,data,user);return await simple_transition(sid,EmptyAction(version=s["version"]),user,"delivery_arrived","delivery_arrived","execution_session.delivery_arrived","arrived_delivery")
 @api.post("/execution-sessions/{sid}/delivery-confirm")
 async def delivery_confirm(sid:str,data:DeliveryConfirm,user=Depends(get_current_user)):
  permit(user,OPS);s=await get_one(db.execution_sessions,user,sid,"Execution session")
  if s["version"]!=data.version:raise HTTPException(409,"Execution session changed concurrently")
  if s["status"]!="delivery_arrived":raise HTTPException(409,"Delivery arrival is required")
  for did in data.evidence_document_ids:
   if not await db.documents.find_one(tenant_filter(user,{"id":did,"load_id":s["load_id"]}),{"_id":0}):raise HTTPException(404,"Evidence document not found")
  load=await db.loads.find_one(tenant_filter(user,{"id":s["load_id"]}),{"_id":0})
  if load.get("stage") not in {"Arrived Delivery","Delivered"}:raise HTTPException(409,"Load stage is not ready for delivery")
  stamp=now();a=await begin_audit(db.audit_events,user,"execution_session.delivery_confirmed",AuditEntityType.EXECUTION_SESSION,sid,changed_fields=["status","execution_state","custody_state","version"],previous=s)
  pod=await db.documents.find_one(tenant_filter(user,{"load_id":s["load_id"],"doc_type":"pod"}),{"_id":0})
  updates={"status":"delivery_confirmed","execution_state":"delivered","custody_state":"delivery_confirmed","actual_snapshot":{**s.get("actual_snapshot",{}),"delivery_confirmed_at":stamp,"delivery_evidence_document_ids":data.evidence_document_ids},"version":s["version"]+1,"updated_at":stamp,"updated_by":user["id"]}
  if not pod:updates.update({"open_exception_count":s.get("open_exception_count",0)+1,"execution_health":"watch"})
  try:controlled=await db.execution_sessions.update_one(tenant_filter(user,{"id":sid,"status":"delivery_arrived","version":s["version"]}),{"$set":updates})
  except Exception:await a.failed("session_control_failed");raise HTTPException(503,"Delivery confirmation control unavailable")
  if not controlled.matched_count:await a.rejected("version_conflict");raise HTTPException(409,"Execution session changed concurrently")
  async def reconcile(reason):
   at=now();await db.execution_sessions.update_one(tenant_filter(user,{"id":sid,"status":"delivery_confirmed","version":s["version"]+1}),{"$set":{"status":"exception","execution_health":"critical","version":s["version"]+2,"updated_at":at,"updated_by":user["id"]}})
   conflict=tenant_document(user,{"id":"exc_"+secrets.token_hex(12),"execution_session_id":sid,"load_id":s["load_id"],"type":"delivery_confirmation_conflict","category":"delivery","severity":"critical","status":"open","blocking":True,"title":"Delivery confirmation requires reconciliation","summary":reason,"detected_at":at,"detected_by":user["id"],"source":"system","owner_user_id":user["id"],"owner_role":user["role"],"assigned_at":at,"acknowledged_at":None,"acknowledged_by":None,"resolved_at":None,"resolved_by":None,"resolution":"","resolution_reason":"","sla_due_at":at,"escalated_at":None,"escalation_level":0,"related_event_ids":[],"related_document_ids":[],"version":1})
   try:await db.execution_exceptions.insert_one(conflict)
   except Exception:pass
  try:await append_event(db,user,s,"delivery_confirmed","Manual delivery confirmed",{"delivery_confirmed_at":stamp,"receiver_name":data.receiver_name,"delivery_reference":data.delivery_reference,"evidence_document_ids":data.evidence_document_ids,"verification":"recipient_identity_and_signature_not_verified"},resulting="delivered",source="manual",at=stamp)
  except Exception:await reconcile("Delivery event storage failed after session control");await a.failed("delivery_event_write_failed");raise HTTPException(503,"Delivery evidence could not be recorded")
  if not pod:
   eid="exc_"+secrets.token_hex(12);due=(datetime.now(timezone.utc)+timedelta(hours=12)).isoformat();missing=tenant_document(user,{"id":eid,"execution_session_id":sid,"load_id":s["load_id"],"type":"pod_missing","category":"document","severity":"warning","status":"open","blocking":False,"title":"POD required for execution completion","summary":"Delivery is confirmed; same-load POD metadata is required before completion","detected_at":now(),"detected_by":user["id"],"source":"system","owner_user_id":user["id"],"owner_role":user["role"],"assigned_at":now(),"acknowledged_at":None,"acknowledged_by":None,"resolved_at":None,"resolved_by":None,"resolution":"","resolution_reason":"","sla_due_at":due,"escalated_at":None,"escalation_level":0,"related_event_ids":[],"related_document_ids":[],"version":1})
   try:await db.execution_exceptions.insert_one(missing)
   except Exception:await reconcile("POD readiness evidence storage failed");await a.failed("pod_exception_write_failed");raise HTTPException(503,"Delivery evidence control unavailable")
  if load.get("stage")!="Delivered":
   try:r=await db.loads.update_one(tenant_filter(user,{"id":s["load_id"],"stage":"Arrived Delivery"}),{"$set":{"stage":"Delivered","pod_status":"Pending","updated_at":stamp}})
   except Exception:await reconcile("Canonical load delivery transition storage failed");await a.failed("load_stage_write_failed");raise HTTPException(503,"Delivery stage synchronization unavailable")
   if not r.matched_count:await reconcile("Canonical load stage changed concurrently");await a.rejected("load_stage_conflict");raise HTTPException(409,"Load stage changed concurrently")
  await a.succeeded({"id":sid,"status":"delivery_confirmed","version":s["version"]+1,"stage":"Delivered"})
  return await get_one(db.execution_sessions,user,sid,"Execution session")
 @api.post("/execution-sessions/{sid}/complete")
 async def complete(sid:str,data:EmptyAction,user=Depends(get_current_user)):
  permit(user,OPS);s=await get_one(db.execution_sessions,user,sid,"Execution session")
  if s["version"]!=data.version:raise HTTPException(409,"Execution session changed concurrently")
  exceptions=await db.execution_exceptions.find(tenant_filter(user,{"execution_session_id":sid}),{"_id":0}).to_list(500);pod=await db.documents.find_one(tenant_filter(user,{"load_id":s["load_id"],"doc_type":"pod"}),{"_id":0});ready=completion_readiness(s,exceptions,bool(pod))
  if not ready["ready"]:raise HTTPException(409,ready)
  load=await db.loads.find_one(tenant_filter(user,{"id":s["load_id"],"stage":"Delivered"}),{"_id":0})
  if not load:raise HTTPException(409,"Load must be Delivered")
  stamp=now();a=await begin_audit(db.audit_events,user,"execution_session.completed",AuditEntityType.EXECUTION_SESSION,sid,changed_fields=["status","execution_state","custody_state","version"],previous=s);await append_event(db,user,s,"session_completed","Execution session completed",resulting="completed");return await save(db,user,s,{"status":"completed","execution_state":"completed","custody_state":"completed","completed_at":stamp,"completed_by":user["id"]},a)
 @api.post("/execution-sessions/{sid}/amend-plan")
 async def amend(sid:str,data:AmendPlan,user=Depends(get_current_user)):
  permit(user,ADMIN);s=await get_one(db.execution_sessions,user,sid,"Execution session")
  if s["version"]!=data.version:raise HTTPException(409,"Execution session changed concurrently")
  old=s["planned_snapshot"];new={**old};delivery={**old.get("delivery",{})}
  if data.delivery_appt is not None:delivery["appointment"]=data.delivery_appt
  if data.delivery_address is not None:delivery["address"]=data.delivery_address
  new["delivery"]=delivery
  if data.driver_id is not None:new["driver_id"]=data.driver_id
  if data.truck_id is not None:new["truck_id"]=data.truck_id
  history=s.get("planning_history",[])+[{"version":s["version"],"snapshot":old,"amended_at":now(),"amended_by":user["id"],"reason":data.reason}]
  a=await begin_audit(db.audit_events,user,"execution_session.plan_amended",AuditEntityType.EXECUTION_SESSION,sid,changed_fields=["planned_snapshot","planning_history","version"],previous=s);await append_event(db,user,s,"plan_amended","Execution plan amended; prior plan preserved",{"reason":data.reason});return await save(db,user,s,{"planned_snapshot":new,"planning_history":history},a)
