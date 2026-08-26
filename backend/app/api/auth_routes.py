from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import StreamingResponse
import os, logging, uuid, secrets, bcrypt, random, math, asyncio, re
from pymongo.errors import DuplicateKeyError
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
from app.constants import DEFAULT_ASSUMPTIONS
from app.schemas.tenants import TenantRecord, TenantStatus
from app.infrastructure import verify_sso_client


def register_auth_routes(public_api, api, get_current_user):
    # ============ AUTH ============
    class LoginIn(BaseModel):
        email: EmailStr
        password: str

        @field_validator("email")
        @classmethod
        def normalize_email(cls, value):
            return str(value).strip().lower()

    class SignupIn(BaseModel):
        model_config = {"extra": "forbid"}
        email: EmailStr
        password: str
        name: str
        role: str = "viewer"

        @field_validator("email")
        @classmethod
        def normalize_email(cls, value):
            return str(value).strip().lower()

        @field_validator("password")
        @classmethod
        def strong_password(cls, value):
            if len(value) < 12:
                raise ValueError("Password must be at least 12 characters")
            return value

    async def find_user_by_email(email: str):
        """Find normalized users first, then safely support legacy mixed-case records.

        A later migration should add email_normalized, backfill historical users,
        and create a unique index on that normalized field.
        """
        normalized = email.strip().lower()
        user = await db.users.find_one({"email": normalized})
        if user:
            return user
        legacy_pattern = re.compile(rf"^{re.escape(normalized)}$", re.IGNORECASE)
        return await db.users.find_one({"email": legacy_pattern})


    @public_api.post("/auth/signup")
    async def signup(data: SignupIn):
        if data.role.strip().lower() != "viewer":
            raise HTTPException(403, "Public signup can only create viewer users")
        existing = await find_user_by_email(str(data.email))
        if existing:
            raise HTTPException(400, "Email exists")
        timestamp = now_iso()
        # exclude_none: an unlinked tenant must have metaphora_org_id genuinely
        # MISSING, not present-as-null — $exists:true (the partial-index guard
        # for uq_tenants_metaphora_org_id) matches null just as much as a real
        # value, so writing null here would make every ordinary signup tenant
        # collide under that unique index.
        tenant = TenantRecord(id=new_tenant_id(), name=f"{data.name.strip() or 'New'} Workspace", status=TenantStatus.ACTIVE, created_at=timestamp, updated_at=timestamp).model_dump(mode="json", exclude_none=True)
        await safe_db(db.tenants.insert_one(tenant), "tenant create")
        user = {
            "id": new_id("U"), "email": str(data.email), "name": data.name, "role": "viewer",
            "tenant_id": tenant["id"],
            "password": bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(),
            "created_at": now_iso()
        }
        try:
            await safe_db(db.users.insert_one(user), "user create")
        except HTTPException:
            try:
                await db.tenants.delete_one({"id": tenant["id"]})
            except Exception:
                logging.error("Signup tenant cleanup failed")
            raise
        try:
            defaults = tenant_document(user, DEFAULT_ASSUMPTIONS)
            await safe_db(db.assumptions.insert_one(defaults), "tenant defaults create")
        except HTTPException:
            logging.error("Signup assumptions initialization failed")
        try:
            signup_audit = await begin_audit(db.audit_events, user, "tenant.signup_created", AuditEntityType.TENANT,
                                             tenant["id"], changed_fields=[], source=AuditSource.SIGNUP)
            await signup_audit.succeeded({"id": tenant["id"]})
        except HTTPException:
            logging.warning("Signup audit event could not be recorded")
        safe_user = public_user(user)
        return {"token": create_token(safe_user, settings.jwt_secret), "user": safe_user}

    @public_api.post("/auth/login")
    async def login(data: LoginIn):
        user = await find_user_by_email(str(data.email))
        stored_password = user.get("password") if user else None
        password_valid = False
        if isinstance(stored_password, str):
            try:
                password_valid = bcrypt.checkpw(data.password.encode(), stored_password.encode())
            except (TypeError, ValueError):
                password_valid = False
        if not user or not password_valid:
            raise HTTPException(401, "Invalid credentials")
        safe_user = public_user(user)
        return {"token": create_token(safe_user, settings.jwt_secret), "user": safe_user}

    class MetaphoraExchangeIn(BaseModel):
        model_config = {"extra": "forbid"}
        code: str

    @public_api.post("/auth/metaphora/exchange")
    async def metaphora_exchange(data: MetaphoraExchangeIn):
        if not verify_sso_client.is_configured(settings):
            raise HTTPException(503, "Metaphora Secure sign-in is not configured")
        result = await verify_sso_client.redeem_sso_code(settings, data.code)
        if result is None or result.get("status") != "ok":
            raise HTTPException(400, "Sign-in link is invalid or has expired")

        verify_org_id = str(result["org_id"]).strip()
        if not verify_org_id:
            logging.error("Metaphora SSO exchange returned a blank org_id")
            raise HTTPException(502, "Metaphora Secure returned an invalid organization identity")
        timestamp = now_iso()
        email = result["email"].strip().lower()

        tenant = await db.tenants.find_one({"metaphora_org_id": verify_org_id})
        # users.email is a GLOBAL unique index (not tenant-scoped). Check for
        # a pre-existing Control-Tower-native account under an unrelated
        # tenant BEFORE creating anything, so a collision never leaves an
        # orphan tenant behind (a tenant is only ever created once we know
        # this exchange will actually succeed).
        existing_user = await db.users.find_one({"email": email})
        if existing_user and (not tenant or existing_user.get("tenant_id") != tenant["id"]):
            raise HTTPException(409, "An account with that email already exists under a different Metaphora Secure organization")

        is_first_user_in_tenant = False
        if not tenant:
            candidate = TenantRecord(
                id=new_tenant_id(), name=(result.get("org_name") or "Metaphora Workspace"),
                status=TenantStatus.ACTIVE, created_at=timestamp, updated_at=timestamp,
            ).model_dump(mode="json")
            candidate["metaphora_org_id"] = verify_org_id
            try:
                await db.tenants.insert_one(candidate)
            except DuplicateKeyError:
                # Lost a race with a concurrent first-time SSO login for the
                # same Verify org — use the tenant that won instead of
                # erroring or creating a duplicate.
                tenant = await db.tenants.find_one({"metaphora_org_id": verify_org_id})
                if not tenant:
                    raise HTTPException(500, "Tenant provisioning failed")
            except Exception:
                logging.error("Tenant create (metaphora sso) failed")
                raise HTTPException(500, "Database operation failed")
            else:
                tenant = candidate
                is_first_user_in_tenant = True
                try:
                    defaults = tenant_document({"tenant_id": tenant["id"]}, DEFAULT_ASSUMPTIONS)
                    await safe_db(db.assumptions.insert_one(defaults), "tenant defaults create")
                except HTTPException:
                    logging.error("Metaphora SSO tenant defaults initialization failed")

        user = existing_user
        if not user:
            display_name = email.split("@")[0] if "@" in email else email
            user = {
                "id": new_id("U"), "email": email, "name": display_name,
                "role": "owner" if is_first_user_in_tenant else "viewer",
                "tenant_id": tenant["id"],
                "password": bcrypt.hashpw(secrets.token_urlsafe(32).encode(), bcrypt.gensalt()).decode(),
                "created_at": now_iso(),
            }
            await safe_db(db.users.insert_one(user), "user create (metaphora sso)")
            try:
                audit = await begin_audit(db.audit_events, user, "tenant.metaphora_sso_user_created",
                                           AuditEntityType.TENANT, tenant["id"], changed_fields=[],
                                           source=AuditSource.SIGNUP)
                await audit.succeeded({"id": user["id"]})
            except HTTPException:
                logging.warning("Metaphora SSO audit event could not be recorded")

        safe_user = public_user(user)
        return {"token": create_token(safe_user, settings.jwt_secret), "user": safe_user}

    @api.get("/auth/me")
    async def me(user=Depends(get_current_user)):
        return user

