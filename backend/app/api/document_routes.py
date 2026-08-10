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


def register_document_routes(api, get_current_user, operational_write):
    # ============ DOCUMENTS ============
    @api.get("/documents")
    async def list_docs(load_id: Optional[str] = None, user=Depends(get_current_user)):
        if load_id: await require_tenant_reference(db.loads, user, load_id, "load")
        q = tenant_filter(user, {"load_id": load_id} if load_id else None)
        return await db.documents.find(q, {"_id": 0}).to_list(1000)

    @api.post("/documents")
    async def create_doc(d: DocumentCreate, user=Depends(operational_write)):
        await require_tenant_reference(db.loads, user, d.load_id, "load")
        doc = tenant_document(user, {"id": new_id("DOC"), **d.model_dump(mode="json"), "uploaded_at": now_iso(), "uploaded_by": user.get("name", user["id"])})
        impact_plan=plan_mutation(SourceEntityType.DOCUMENT,doc["id"],MutationType.DOCUMENT_ADDED,context={"document_type":d.doc_type.value})
        audit = await begin_audit(db.audit_events, user, "document.created", AuditEntityType.DOCUMENT, doc["id"], changed_fields=list(d.model_fields_set), previous={"load_id": d.load_id})
        pickup_impact=impact_for(impact_plan,TargetDomain.PICKUP_RELEASE)
        if pickup_impact:
            await preinvalidate_pickup_release(db,user,d.load_id,list(pickup_impact.change_types))
        passport_collection = getattr(db, "load_passports", None)
        passport = None; invalidation_audit = None; invalidation_plan = None
        verification_case = None; verification_plan = None; verification_audit = None
        party_impact=impact_for(impact_plan,TargetDomain.PARTY_VERIFICATION)
        relevant_change=(party_impact.change_types[0] if party_impact else None)
        case_collection=getattr(db,"party_verification_cases",None)
        if relevant_change and case_collection is not None:
            verification_case = await case_collection.find_one(tenant_filter(user,{"load_id":d.load_id,"status":"cleared"}),{"_id":0})
            if verification_case:
                verification_plan=build_case_preinvalidation(verification_case,[relevant_change],user["id"],utc_now())
                verification_audit=await begin_audit(db.audit_events,user,"party_verification.material_change_invalidated",AuditEntityType.PARTY_VERIFICATION_CASE,verification_case["id"],changed_fields=[relevant_change,"status","version"],previous=verification_case)
        if relevant_change and passport_collection is not None:
            passport = await passport_collection.find_one(tenant_filter(user, {"load_id": d.load_id}), {"_id": 0})
            if passport:
                invalidation_plan = build_preinvalidation(passport, ["rate_confirmation" if relevant_change=="rate_confirmation" else "insurance"], user["id"], utc_now())
                if verification_plan:
                    pp=build_passport_preinvalidation(passport,verification_plan["effects"],user["id"],utc_now()); invalidation_plan={"required":True,"query":pp["query"],"update":pp["update"],"new_version":pp["update"]["version"]}
                if invalidation_plan["required"]:
                    invalidation_audit = await begin_audit(db.audit_events, user, "load_passport.material_change_invalidated", AuditEntityType.LOAD_PASSPORT, passport["id"], changed_fields=["rate_confirmation", "status", "version"], previous=passport)
        if has_impact(impact_plan,TargetDomain.INVOICE_READINESS):
            await invalidate_invoice_readiness(db,user,d.load_id,"billing_document_changed",[d.doc_type.value])
        execution_impact=impact_for(impact_plan,TargetDomain.EXECUTION_ELIGIBILITY)
        execution_cases=await preinvalidate_for_load(db,user,d.load_id,list(execution_impact.change_types)) if execution_impact else []
        if execution_cases and passport:
            passport=await passport_collection.find_one(tenant_filter(user,{"id":passport["id"]}),{"_id":0})
            if verification_plan:
                pp=build_passport_preinvalidation(passport,verification_plan["effects"],user["id"],utc_now()); invalidation_plan={"required":True,"query":pp["query"],"update":pp["update"],"new_version":pp["update"]["version"]}
            else:
                invalidation_plan=build_preinvalidation(passport,["rate_confirmation" if relevant_change=="rate_confirmation" else "insurance"],user["id"],utc_now())
        if verification_audit:
            vr=await audited_db(verification_audit,case_collection.update_one(tenant_filter(user,verification_plan["query"]),{"$set":verification_plan["update"]}),"verification pre-invalidation")
            if not vr.matched_count:
                await verification_audit.rejected("version_conflict"); await audit.rejected("verification_version_conflict"); raise HTTPException(409,"Verification case changed concurrently; document was not created")
            await verification_audit.succeeded({"id":verification_case["id"],"load_id":d.load_id,"status":"review_pending","version":verification_plan["update"]["version"]})
        if invalidation_audit:
            invalidated = await audited_db(invalidation_audit, passport_collection.update_one(tenant_filter(user, invalidation_plan["query"]), {"$set": invalidation_plan["update"]}), "passport pre-invalidation")
            if not invalidated.matched_count:
                await invalidation_audit.rejected("version_conflict"); await audit.rejected("passport_version_conflict")
                raise HTTPException(409, "Passport changed concurrently; document was not created")
            await invalidation_audit.succeeded({"id": passport["id"], "status": "review_pending", "version": invalidation_plan["new_version"]})
        await audited_db(audit, db.documents.insert_one(doc), "document create"); clean_doc(doc); await audit.succeeded(doc)
        if invalidation_audit and d.doc_type.value == "rate_con":
            synchronization = {"rate_confirmation": {"document_id": doc["id"], "rate_confirmation_number": "", "filename": doc["filename"], "document_type": "rate_con", "captured_at": utc_now()}, "evidence_document_ids": sorted(set(passport.get("evidence_document_ids", [])) | {doc["id"]})}
            try:
                await passport_collection.update_one(tenant_filter(user, {"id": passport["id"], "version": invalidation_plan["new_version"], "status": "review_pending"}), {"$set": synchronization})
            except Exception:
                logging.warning("Passport evidence synchronization failed after document create")
        return doc

