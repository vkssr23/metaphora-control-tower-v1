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


def register_activity_audit_routes(api, get_current_user, audit_reader):
    # ============ LEGACY ACTIVITY COMPATIBILITY ============
    @api.get("/activity")
    async def list_activity(load_id: Optional[str] = None, user=Depends(get_current_user)):
        q = tenant_filter(user, {"load_id": load_id} if load_id else None)
        legacy = await db.activity.find(q, {"_id": 0}).sort("timestamp", -1).to_list(500)
        aq = tenant_filter(user, {"phase": "succeeded"})
        events = await db.audit_events.find(aq, {"_id": 0}).sort("occurred_at", -1).to_list(500)
        action_names = {
            "load.created": "Load Created", "load.stage_changed": "Stage Change",
            "load.exception_entered": "Stage Change", "load.exception_recovered": "Stage Change",
            "document.created": "Document Uploaded", "alert.generated": "Driver Alert Generated",
        }
        mapped = []
        for event in events:
            previous, new = event.get("previous_state_summary", {}), event.get("new_state_summary", {})
            compatible_load_id = event["entity_id"] if event.get("entity_type") == "load" else (new.get("load_id") or previous.get("load_id"))
            if event.get("action") not in action_names or not compatible_load_id or (load_id and compatible_load_id != load_id): continue
            mapped.append({"id": event["id"], "tenant_id": event["tenant_id"], "load_id": compatible_load_id,
                           "action": action_names.get(event["action"], event["action"]),
                           "old_status": previous.get("stage", ""), "new_status": new.get("stage", ""),
                           "updated_by": event.get("actor_email") or event.get("actor_id", ""),
                           "timestamp": event["occurred_at"], "notes": event.get("message", "")})
        return sorted(mapped + legacy, key=lambda item: (item.get("timestamp", ""), item.get("id", "")), reverse=True)[:500]


    # ============ APPEND-ONLY AUDIT LEDGER ============
    @api.get("/audit-events/incomplete")
    async def list_incomplete_audit_events(older_than_seconds: int = Query(300, ge=60, le=86400),
                                           limit: int = Query(50, ge=1, le=100),
                                           user=Depends(audit_reader)):
        return await incomplete_operations(db.audit_events, require_tenant_id(user), older_than_seconds, limit)


    @api.get("/audit-events")
    async def list_audit_events(request: Request, entity_type: Optional[AuditEntityType] = None,
                                entity_id: Optional[str] = Query(None, max_length=128),
                                action: Optional[str] = Query(None, max_length=64),
                                outcome: Optional[AuditOutcome] = None,
                                operation_id: Optional[str] = Query(None, max_length=128),
                                actor_id: Optional[str] = Query(None, max_length=128),
                                date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
                                before: Optional[datetime] = None, limit: int = Query(50, ge=1, le=100),
                                user=Depends(audit_reader)):
        allowed = {"entity_type", "entity_id", "action", "outcome", "operation_id", "actor_id",
                   "date_from", "date_to", "before", "limit"}
        unknown = set(request.query_params) - allowed
        if unknown: raise HTTPException(422, "Unknown audit filter")
        q = tenant_filter(user)
        for key, value in (("entity_type", entity_type.value if entity_type else None), ("entity_id", entity_id),
                           ("action", action), ("outcome", outcome.value if outcome else None),
                           ("operation_id", operation_id), ("actor_id", actor_id)):
            if value is not None: q[key] = value
        occurred = {}
        if date_from: occurred["$gte"] = date_from.astimezone(timezone.utc).isoformat()
        upper = before or date_to
        if upper: occurred["$lt" if before else "$lte"] = upper.astimezone(timezone.utc).isoformat()
        if occurred: q["occurred_at"] = occurred
        return await db.audit_events.find(q, {"_id": 0}).sort([("occurred_at", -1), ("id", -1)]).to_list(limit)

