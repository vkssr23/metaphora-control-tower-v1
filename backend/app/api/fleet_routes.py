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


def register_fleet_routes(api, get_current_user, safety_write):
    # ============ TRUCKS ============
    @api.get("/trucks")
    async def list_trucks(user=Depends(get_current_user)):
        docs = await db.trucks.find(tenant_filter(user), {"_id": 0}).to_list(1000)
        return docs

    @api.post("/trucks")
    async def create_truck(t: TruckCreate, user=Depends(safety_write)):
        await require_tenant_reference(db.drivers, user, t.assigned_driver_id, "assigned driver")
        d = tenant_document(user, {"id": new_id("T"), **t.model_dump(mode="json"), "profit_per_mile": 0, "created_at": now_iso()})
        audit = await begin_audit(db.audit_events, user, "truck.created", AuditEntityType.TRUCK, d["id"], changed_fields=list(t.model_fields_set))
        await audited_db(audit, db.trucks.insert_one(d), "truck create")
        clean_doc(d); await audit.succeeded(d)
        return d

    @api.put("/trucks/{tid}")
    async def update_truck(tid: str, data: TruckUpdate, user=Depends(safety_write)):
        previous = await safe_db(db.trucks.find_one(tenant_filter(user, {"id": tid}), {"_id": 0}), "truck lookup")
        if not previous: raise HTTPException(404, "Not found")
        updates = data.model_dump(mode="json", exclude_unset=True)
        if "assigned_driver_id" in updates: await require_tenant_reference(db.drivers, user, updates["assigned_driver_id"], "assigned driver")
        updates["updated_at"] = now_iso()
        audit = await begin_audit(db.audit_events, user, "truck.updated", AuditEntityType.TRUCK, tid, changed_fields=list(updates), previous=previous)
        if set(updates) & TRUCK_MATERIAL_FIELDS:
            await preinvalidate_pickup_for_execution_snapshot(db,user,"truck_snapshot",tid,["truck"])
            await preinvalidate_for_snapshot(db, user, "truck_snapshot", tid, ["truck"] + (["equipment"] if "equipment_type" in updates else []))
        result = await audited_db(audit, db.trucks.update_one(tenant_filter(user, {"id": tid}), {"$set": updates}), "truck update")
        if not result.matched_count: await audit.rejected("not_found"); raise HTTPException(404, "Not found")
        await audit.succeeded(updates)
        return {"ok": True}

    @api.delete("/trucks/{tid}")
    async def delete_truck(tid: str, user=Depends(safety_write)):
        previous = await safe_db(db.trucks.find_one(tenant_filter(user, {"id": tid}), {"_id": 0}), "truck lookup")
        if not previous: raise HTTPException(404, "Not found")
        audit = await begin_audit(db.audit_events, user, "truck.deleted", AuditEntityType.TRUCK, tid, previous=previous)
        result = await audited_db(audit, db.trucks.delete_one(tenant_filter(user, {"id": tid})), "truck delete")
        if not result.deleted_count: await audit.rejected("not_found"); raise HTTPException(404, "Not found")
        await audit.succeeded()
        return {"ok": True}

    # ============ DRIVERS ============
    @api.get("/drivers")
    async def list_drivers(user=Depends(get_current_user)):
        return await db.drivers.find(tenant_filter(user), {"_id": 0}).to_list(1000)

    @api.post("/drivers")
    async def create_driver(d: DriverCreate, user=Depends(safety_write)):
        await require_tenant_reference(db.trucks, user, d.assigned_truck_id, "assigned truck")
        doc = tenant_document(user, {"id": new_id("D"), **d.model_dump(mode="json"), "created_at": now_iso()})
        audit = await begin_audit(db.audit_events, user, "driver.created", AuditEntityType.DRIVER, doc["id"], changed_fields=list(d.model_fields_set))
        await audited_db(audit, db.drivers.insert_one(doc), "driver create"); clean_doc(doc); await audit.succeeded(doc)
        return doc

    @api.put("/drivers/{did}")
    async def update_driver(did: str, data: DriverUpdate, user=Depends(safety_write)):
        previous = await safe_db(db.drivers.find_one(tenant_filter(user, {"id": did}), {"_id": 0}), "driver lookup")
        if not previous: raise HTTPException(404, "Not found")
        updates = data.model_dump(mode="json", exclude_unset=True); updates["updated_at"] = now_iso()
        if "assigned_truck_id" in updates: await require_tenant_reference(db.trucks, user, updates["assigned_truck_id"], "assigned truck")
        audit = await begin_audit(db.audit_events, user, "driver.updated", AuditEntityType.DRIVER, did, changed_fields=list(updates), previous=previous)
        if set(updates) & DRIVER_MATERIAL_FIELDS:
            await preinvalidate_pickup_for_execution_snapshot(db,user,"driver_snapshot",did,["driver"])
            await preinvalidate_for_snapshot(db, user, "driver_snapshot", did, ["driver"])
        result = await audited_db(audit, db.drivers.update_one(tenant_filter(user, {"id": did}), {"$set": updates}), "driver update")
        if not result.matched_count: await audit.rejected("not_found"); raise HTTPException(404, "Not found")
        await audit.succeeded(updates)
        return {"ok": True}

    @api.delete("/drivers/{did}")
    async def delete_driver(did: str, user=Depends(safety_write)):
        previous = await safe_db(db.drivers.find_one(tenant_filter(user, {"id": did}), {"_id": 0}), "driver lookup")
        if not previous: raise HTTPException(404, "Not found")
        audit = await begin_audit(db.audit_events, user, "driver.deleted", AuditEntityType.DRIVER, did, previous=previous)
        result = await audited_db(audit, db.drivers.delete_one(tenant_filter(user, {"id": did})), "driver delete")
        if not result.deleted_count: await audit.rejected("not_found"); raise HTTPException(404, "Not found")
        await audit.succeeded()
        return {"ok": True}

