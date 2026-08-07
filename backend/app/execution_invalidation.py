"""Shared audit-first application of the pure Phase 1D invalidation plan."""
from fastapi import HTTPException
from app.audit import begin_audit
from app.schemas.audit import AuditEntityType
from app.tenant import tenant_filter
from app.domain.execution_eligibility import build_invalidation_plan,utc_now

MASTER_DATA_SYNC_CEILING=100
async def eligible_cases(db,user,query,ceiling=None):
    collection=getattr(db,"execution_eligibility_cases",None)
    if collection is None: return []
    limit=(ceiling+1) if ceiling is not None else 201
    cases=await collection.find(tenant_filter(user,{**query,"status":"eligible"}),{"_id":0}).sort([("updated_at",1),("id",1)]).to_list(limit)
    if ceiling is not None and len(cases)>ceiling: raise HTTPException(409,"Too many affected eligible cases for synchronous safe invalidation")
    return cases

async def preinvalidate_case(db,user,case,change_types):
    passport=await db.load_passports.find_one(tenant_filter(user,{"id":case["passport_id"]}),{"_id":0})
    if not passport: raise HTTPException(409,"Execution eligibility passport is unavailable")
    plan=build_invalidation_plan(case,passport,change_types,user["id"],utc_now())
    audit=await begin_audit(db.audit_events,user,"execution_eligibility.material_change_invalidated",AuditEntityType.EXECUTION_ELIGIBILITY_CASE,case["id"],changed_fields=plan["affected_check_types"]+["status","verdict","version"],previous=case)
    passport_audit=await begin_audit(db.audit_events,user,"execution_eligibility.passport_synchronized",AuditEntityType.LOAD_PASSPORT,passport["id"],changed_fields=plan["affected_passport_checkpoint_types"]+["version"],previous=passport)
    try: presult=await db.load_passports.update_one(plan["passport_query"],{"$set":plan["passport_update"]})
    except Exception: await passport_audit.failed(); await audit.failed("passport_update_failed"); raise HTTPException(500,"Database operation failed")
    if not presult.matched_count: await passport_audit.rejected("version_conflict"); await audit.rejected("passport_version_conflict"); raise HTTPException(409,"Passport changed concurrently; canonical mutation was not applied")
    await passport_audit.succeeded({"id":passport["id"],"version":plan["passport_next_version"]})
    try: result=await db.execution_eligibility_cases.update_one(plan["eligibility_case_query"],{"$set":plan["eligibility_case_update"]})
    except Exception: await audit.failed(); raise HTTPException(500,"Database operation failed")
    if not result.matched_count: await audit.rejected("version_conflict"); raise HTTPException(409,"Execution eligibility changed concurrently")
    await audit.succeeded({"id":case["id"],"status":"review_pending","version":plan["case_next_version"]})
    return plan

async def preinvalidate_for_load(db,user,load_id,change_types):
    cases=await eligible_cases(db,user,{"load_id":load_id})
    for case in cases: await preinvalidate_case(db,user,case,change_types)
    return cases

async def preinvalidate_for_snapshot(db,user,snapshot_field,entity_id,change_types):
    cases=await eligible_cases(db,user,{f"{snapshot_field}.id":entity_id},MASTER_DATA_SYNC_CEILING)
    for case in cases: await preinvalidate_case(db,user,case,change_types)
    return cases
