from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import StreamingResponse
import os, logging, uuid, bcrypt, random, math, asyncio, re
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from app.config import force_seed_allowed
from app.permissions import require_capability, require_owner, require_audit_reader
from app.audit import begin_audit
from app.domain.audit_events import incomplete_operations
from app.schemas.audit import AuditEntityType, AuditOutcome, AuditSource
from app.security import create_token, public_user
from app.tenant import new_tenant_id, tenant_document, tenant_filter, require_tenant_id, require_tenant_reference
from app.production_integrity import evaluate_environment, evaluate_production_readiness
from app.domain.load_transitions import transition_allowed
from app.domain.load_passports import MATERIAL_LOAD_FIELDS, bounded_load_snapshot, build_preinvalidation, material_categories, utc_now
from app.invoice_readiness_invalidation import invalidate_invoice_readiness
from app.domain.invoice_readiness import BILLING_DOCUMENT_TYPES
from app.pickup_release_invalidation import preinvalidate_pickup_release, preinvalidate_pickup_for_execution_snapshot
from app.domain.party_verification import build_case_preinvalidation, build_passport_preinvalidation, is_insurance_document
from app.execution_invalidation import preinvalidate_for_load, preinvalidate_for_snapshot
from app.execution_material_change import control_material_load_change
from app.domain.mutation_impact import MutationType, SourceEntityType, TargetDomain, impact_for, has_impact, plan_mutation
from app.domain.invoice_authority import InvoiceAuthority, classify_invoice_authority, is_modern_invoice, legacy_write_allowed
from app.domain.execution_eligibility import DRIVER_MATERIAL_FIELDS, TRUCK_MATERIAL_FIELDS
from app.schemas import (
    AiChatRequest, AssumptionUpdate, DocumentCreate, DriverAlertRequest, DriverCreate,
    DriverUpdate, InvoiceCreate, InvoiceUpdate, LoadAnalysisRequest, LoadCreate,
    LoadIdRequest, LoadStage, LoadUpdate, RouteCalculationRequest,
    SamsaraVehicleRequest, StageChange as SafeStageChange, TruckCreate, TruckUpdate,
    WeatherCheckRequest,
)
from app.runtime import db, settings, now_iso, new_id, clean_doc, safe_db, audited_db
from app.application.invoice_authority_query import invoice_authority_for_load


def register_load_routes(api, get_current_user, operational_write):
    # ============ LOADS ============
    @api.get("/loads")
    async def list_loads(user=Depends(get_current_user)):
        return await db.loads.find(tenant_filter(user), {"_id": 0}).to_list(2000)

    @api.get("/loads/{lid}")
    async def get_load(lid: str, user=Depends(get_current_user)):
        l = await db.loads.find_one(tenant_filter(user, {"id": lid}), {"_id": 0})
        if not l: raise HTTPException(404, "Not found")
        return l

    @api.post("/loads")
    async def create_load(l: LoadCreate, user=Depends(operational_write)):
        await require_tenant_reference(db.drivers, user, l.driver_id, "driver")
        await require_tenant_reference(db.trucks, user, l.truck_id, "truck")
        d = tenant_document(user, {"id": new_id("L"), **l.model_dump(mode="json"), "dispatcher": user.get("name", user["id"]), "stage": "Booked", "bol_status": "Pending", "pod_status": "Pending", "invoice_status": "Not Ready", "payment_status": "Pending", "created_at": now_iso(), "updated_at": now_iso()})
        d["rpm"] = round(d["rate"] / d["miles"], 2) if d["miles"] > 0 and d["rate"] > 0 else 0
        audit = await begin_audit(db.audit_events, user, "load.created", AuditEntityType.LOAD, d["id"], changed_fields=list(l.model_fields_set))
        await audited_db(audit, db.loads.insert_one(d), "load create"); clean_doc(d); await audit.succeeded(d)
        return d

    @api.put("/loads/{lid}")
    async def update_load(lid: str, data: LoadUpdate, user=Depends(operational_write)):
        load = await safe_db(db.loads.find_one(tenant_filter(user, {"id": lid}), {"_id": 0}), "load lookup")
        if not load: raise HTTPException(404, "Not found")
        updates = data.model_dump(mode="json", exclude_unset=True)
        if "driver_id" in updates: await require_tenant_reference(db.drivers, user, updates["driver_id"], "driver")
        if "truck_id" in updates: await require_tenant_reference(db.trucks, user, updates["truck_id"], "truck")
        updates["updated_at"] = now_iso()
        miles, rate = updates.get("miles", load.get("miles", 0)), updates.get("rate", load.get("rate", 0))
        if "miles" in updates or "rate" in updates:
            updates["rpm"] = round(rate / miles, 2) if miles > 0 and rate > 0 else 0
        proposed = {**load, **updates}
        impact_plan = plan_mutation(SourceEntityType.LOAD, lid, MutationType.LOAD_UPDATED,
                                    old_state=load, proposed_state=proposed,
                                    relevant_fields=tuple(data.model_fields_set))
        material_fields = sorted(set(impact_plan.changed_fields) & MATERIAL_LOAD_FIELDS)
        audit = await begin_audit(db.audit_events, user, "load.updated", AuditEntityType.LOAD, lid, changed_fields=list(updates), previous=load)
        readiness_impact=impact_for(impact_plan,TargetDomain.INVOICE_READINESS)
        if readiness_impact:
            await invalidate_invoice_readiness(db,user,lid,readiness_impact.reason_code,list(readiness_impact.change_types))
        if has_impact(impact_plan, TargetDomain.PICKUP_RELEASE): await preinvalidate_pickup_release(db,user,lid,material_fields or impact_plan.unknown_fields)
        passport = None; invalidation_audit = None; invalidation_plan = None
        verification_case = None; verification_audit = None; verification_update = None
        passport_collection = getattr(db, "load_passports", None)
        if has_impact(impact_plan, TargetDomain.LOAD_PASSPORT) and passport_collection is not None:
            passport = await safe_db(passport_collection.find_one(tenant_filter(user, {"load_id": lid}), {"_id": 0}), "passport lookup")
            if passport:
                invalidation_plan = build_preinvalidation(passport, material_categories(material_fields), user["id"], utc_now())
                if invalidation_plan["required"]:
                    invalidation_audit = await begin_audit(db.audit_events, user, "load_passport.material_change_invalidated", AuditEntityType.LOAD_PASSPORT, passport["id"], changed_fields=material_fields + ["status", "version"], previous=passport)
        case_collection = getattr(db, "party_verification_cases", None)
        party_impact = impact_for(impact_plan, TargetDomain.PARTY_VERIFICATION)
        party_fields = set(party_impact.change_types) if party_impact else set()
        if party_impact and case_collection is not None:
            verification_case = await safe_db(case_collection.find_one(tenant_filter(user, {"load_id": lid, "status": "cleared"}), {"_id": 0}), "verification case lookup")
            if verification_case:
                verification_plan = build_case_preinvalidation(verification_case,sorted(set(material_fields)&party_fields),user["id"],utc_now())
                verification_update = verification_plan["update"]
                verification_audit = await begin_audit(db.audit_events, user, "party_verification.material_change_invalidated", AuditEntityType.PARTY_VERIFICATION_CASE, verification_case["id"], changed_fields=material_fields+["status","version"], previous=verification_case)
                if passport:
                    party_passport_plan=build_passport_preinvalidation(passport,verification_plan["effects"],user["id"],utc_now())
                    invalidation_plan={"required":True,"query":party_passport_plan["query"],"update":party_passport_plan["update"],"new_version":party_passport_plan["update"]["version"]}
                    if not invalidation_audit: invalidation_audit=await begin_audit(db.audit_events,user,"load_passport.material_change_invalidated",AuditEntityType.LOAD_PASSPORT,passport["id"],changed_fields=material_fields+["status","version"],previous=passport)
        execution_impact = impact_for(impact_plan, TargetDomain.EXECUTION_ELIGIBILITY)
        execution_changes=list(execution_impact.change_types) if execution_impact else []
        execution_cases=await preinvalidate_for_load(db,user,lid,execution_changes) if execution_changes else []
        if execution_cases and invalidation_plan:
            passport=await passport_collection.find_one(tenant_filter(user,{"id":passport["id"]}),{"_id":0})
            invalidation_plan=build_preinvalidation(passport,material_categories(material_fields),user["id"],utc_now())
            if not invalidation_plan.get("required"): invalidation_plan=None; invalidation_audit=None
        if verification_audit:
            vr = await audited_db(verification_audit, case_collection.update_one(tenant_filter(user,{"id":verification_case["id"],"status":"cleared","version":verification_case["version"]}),{"$set":verification_update}), "verification pre-invalidation")
            if not vr.matched_count:
                await verification_audit.rejected("version_conflict"); await audit.rejected("verification_version_conflict")
                raise HTTPException(409,"Verification case changed concurrently; load was not updated")
            await verification_audit.succeeded({"id":verification_case["id"],"status":"review_pending","version":verification_update["version"]})
        if invalidation_audit:
            invalidated = await audited_db(invalidation_audit, passport_collection.update_one(tenant_filter(user, invalidation_plan["query"]), {"$set": invalidation_plan["update"]}), "passport pre-invalidation")
            if not invalidated.matched_count:
                await invalidation_audit.rejected("version_conflict"); await audit.rejected("passport_version_conflict")
                raise HTTPException(409, "Passport changed concurrently; load was not updated")
            await invalidation_audit.succeeded({"id": passport["id"], "status": "review_pending", "version": invalidation_plan["new_version"]})
        await control_material_load_change(db,user,load,updates)
        result = await audited_db(audit, db.loads.update_one(tenant_filter(user, {"id": lid}), {"$set": updates}), "load update")
        if not result.matched_count: await audit.rejected("not_found"); raise HTTPException(404, "Not found")
        await audit.succeeded(updates)
        if invalidation_audit:
            current = {**load, **updates}
            assignment = dict(passport.get("assignment_snapshot", {})); assignment.update({"driver_id": current.get("driver_id"), "truck_id": current.get("truck_id"), "assignment_timestamp": utc_now()})
            try:
                await passport_collection.update_one(tenant_filter(user, {"id": passport["id"], "version": invalidation_plan["new_version"], "status": "review_pending"}), {"$set": {"load_snapshot": bounded_load_snapshot(current), "assignment_snapshot": assignment}})
            except Exception:
                logging.warning("Passport snapshot synchronization failed after load update")
        return {"ok": True}

    @api.delete("/loads/{lid}")
    async def delete_load(lid: str, user=Depends(operational_write)):
        previous = await safe_db(db.loads.find_one(tenant_filter(user, {"id": lid}), {"_id": 0}), "load lookup")
        if not previous: raise HTTPException(404, "Not found")
        audit = await begin_audit(db.audit_events, user, "load.deleted", AuditEntityType.LOAD, lid, previous=previous)
        result = await audited_db(audit, db.loads.delete_one(tenant_filter(user, {"id": lid})), "load delete")
        if not result.deleted_count: await audit.rejected("not_found"); raise HTTPException(404, "Not found")
        await audit.succeeded()
        return {"ok": True}

    @api.post("/loads/{lid}/stage")
    async def change_stage(lid: str, data: SafeStageChange, user=Depends(operational_write)):
        load = await safe_db(db.loads.find_one(tenant_filter(user, {"id": lid}), {"_id": 0}), "load stage lookup")
        if not load: raise HTTPException(404, "Not found")
        try: old_stage = LoadStage(load.get("stage", ""))
        except ValueError: raise HTTPException(409, "Current load stage is invalid")
        if data.stage == old_stage:
            return {"ok": True, "stage": data.stage.value}
        origin_value = load.get("exception_origin_stage")
        try: exception_origin = LoadStage(origin_value) if origin_value else None
        except ValueError: exception_origin = None
        if not transition_allowed(old_stage, data.stage, exception_origin):
            raise HTTPException(409, f"Transition from {old_stage.value} to {data.stage.value} is not allowed")
        old = old_stage.value
        stage = data.stage.value
        updates = {"stage": stage, "updated_at": now_iso()}
        mongo_update = {"$set": updates}
        if stage == "Exception": updates["exception_origin_stage"] = old
        if old_stage == LoadStage.EXCEPTION:
            mongo_update["$unset"] = {"exception_origin_stage": ""}
        # Legacy compatibility statuses are not an independent modern authority.
        authority=await invoice_authority_for_load(user,lid)
        modern_managed=authority != InvoiceAuthority.LEGACY
        # Auto-update related statuses
        if stage == "Loaded": updates["bol_status"] = "Received"
        if stage == "Delivered": updates["pod_status"] = "Pending"
        if not modern_managed:
            if stage == "Docs Pending": updates["invoice_status"] = "Docs Pending"
            if stage == "Invoice Pending": updates["invoice_status"] = "Ready to Invoice"
            if stage == "Payment Pending": updates["invoice_status"] = "Payment Pending"
            if stage == "Closed": updates["payment_status"] = "Paid"; updates["invoice_status"] = "Paid"
        stage_action = "load.exception_entered" if stage == "Exception" else ("load.exception_recovered" if old_stage == LoadStage.EXCEPTION else "load.stage_changed")
        audit = await begin_audit(db.audit_events, user, stage_action, AuditEntityType.LOAD, lid,
                                  changed_fields=list(updates), previous=load)
        impact_plan = plan_mutation(SourceEntityType.LOAD,lid,MutationType.LOAD_STAGE_CHANGED,old_state={"stage":old},proposed_state={"stage":stage},relevant_fields=["stage"])
        if has_impact(impact_plan,TargetDomain.INVOICE_READINESS):
            await invalidate_invoice_readiness(db,user,lid,"delivery_basis_changed",["load_stage"])
        transition_query = tenant_filter(user, {"id": lid, "stage": old})
        if old_stage == LoadStage.EXCEPTION:
            transition_query["exception_origin_stage"] = origin_value
        result = await audited_db(audit, db.loads.update_one(transition_query, mongo_update), "load stage update")
        if not result.matched_count:
            await audit.rejected("concurrent_stage_change")
            raise HTTPException(409, "Load stage changed concurrently")
        await audit.succeeded(updates)
        return {"ok": True, "stage": stage}

