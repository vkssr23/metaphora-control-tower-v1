"""Public, immutable audit-ledger schema and controlled vocabulary."""
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditPhase(str, Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class AuditOutcome(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    REJECTED = "rejected"
    FAILURE = "failure"


class AuditSource(str, Enum):
    API = "api"
    SIGNUP = "signup"
    SEED = "seed"
    SYSTEM = "system"


class AuditEntityType(str, Enum):
    TRUCK = "truck"
    DRIVER = "driver"
    LOAD = "load"
    DOCUMENT = "document"
    INVOICE = "invoice"
    ASSUMPTIONS = "assumptions"
    ALERT = "alert"
    TENANT = "tenant"
    SEED = "seed"
    LOAD_PASSPORT = "load_passport"
    PICKUP_AUTHORIZATION = "pickup_authorization"
    RATE_CONFIRMATION_EXTRACTION = "rate_confirmation_extraction"
    PARTY_VERIFICATION_CASE = "party_verification_case"
    EXECUTION_ELIGIBILITY_CASE = "execution_eligibility_case"
    PICKUP_RELEASE_CASE = "pickup_release_case"
    EXECUTION_SESSION = "execution_session"
    EXECUTION_EXCEPTION = "execution_exception"
    INVOICE_READINESS_CASE = "invoice_readiness_case"
    ACCESSORIAL = "accessorial"
    INVOICE_PACKAGE = "invoice_package"


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    operation_id: str
    tenant_id: str
    occurred_at: str
    schema_version: int = 1
    phase: AuditPhase
    outcome: AuditOutcome
    action: str
    entity_type: AuditEntityType
    entity_id: str
    actor_id: str
    actor_email: str = ""
    actor_role: str
    source: AuditSource
    correlation_id: str
    changed_fields: list[str] = Field(default_factory=list)
    previous_state_summary: dict[str, Any] = Field(default_factory=dict)
    new_state_summary: dict[str, Any] = Field(default_factory=dict)
    reason_code: str = ""
    message: str = ""
    integrity_hash: str
