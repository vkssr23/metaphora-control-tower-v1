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


def register_legacy_invoice_routes(api, get_current_user, finance_write):
    class InternalSeedInvoice(BaseModel):
        id: str = Field(default_factory=lambda: new_id("INV"))
        load_id: str
        customer: str = ""
        amount: float = 0
        status: str = "Not Ready"
        due_date: str = ""
        paid_date: str = ""
        dispute: bool = False
        notes: str = ""
        created_at: str = Field(default_factory=now_iso)

    @api.get("/invoices")
    async def list_invoices(user=Depends(get_current_user)):
        return await db.invoices.find(tenant_filter(user), {"_id": 0}).to_list(1000)

    @api.post("/invoices")
    async def create_invoice(inv: InvoiceCreate, user=Depends(finance_write)):
        await require_tenant_reference(db.loads, user, inv.load_id, "load")
        doc = tenant_document(user, {"id": new_id("INV"), **inv.model_dump(mode="json"), "created_at": now_iso()})
        audit = await begin_audit(db.audit_events, user, "invoice.created", AuditEntityType.INVOICE, doc["id"], changed_fields=list(inv.model_fields_set))
        existing=await db.invoices.find(tenant_filter(user,{"load_id":inv.load_id})).to_list(50)
        authority=await invoice_authority_for_load(user,inv.load_id,existing)
        if not legacy_write_allowed(authority):
            await audit.rejected("canonical_invoice_authority_required")
            raise HTTPException(409,"Modern or ambiguous invoice authority requires the Invoice Readiness package workflow")
        await audited_db(audit, db.invoices.insert_one(doc), "invoice create"); clean_doc(doc); await audit.succeeded(doc)
        return doc

    @api.put("/invoices/{iid}")
    async def update_invoice(iid: str, data: InvoiceUpdate, user=Depends(finance_write)):
        previous = await safe_db(db.invoices.find_one(tenant_filter(user, {"id": iid}), {"_id": 0}), "invoice lookup")
        if not previous: raise HTTPException(404, "Not found")
        updates = data.model_dump(mode="json", exclude_unset=True); updates["updated_at"] = now_iso()
        audit = await begin_audit(db.audit_events, user, "invoice.updated", AuditEntityType.INVOICE, iid, changed_fields=list(updates), previous=previous)
        if is_modern_invoice(previous):
            await audit.rejected("canonical_invoice_immutable_on_legacy_route")
            raise HTTPException(409,"Modern invoice amount and status are controlled by the Invoice Readiness workflow")
        if previous.get("load_id"):
            siblings=await db.invoices.find(tenant_filter(user,{"load_id":previous["load_id"]})).to_list(50)
            authority=await invoice_authority_for_load(user,previous["load_id"],siblings)
            if authority != InvoiceAuthority.LEGACY:
                await audit.rejected("nonlegacy_invoice_authority")
                raise HTTPException(409,"Modern, incomplete, or ambiguous invoice authority requires reconciliation")
        result = await audited_db(audit, db.invoices.update_one(tenant_filter(user, {"id": iid}), {"$set": updates}), "invoice update")
        if not result.matched_count: await audit.rejected("not_found"); raise HTTPException(404, "Not found")
        await audit.succeeded(updates)
        return {"ok": True}

