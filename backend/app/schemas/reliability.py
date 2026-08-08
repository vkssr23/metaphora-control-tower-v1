"""Strict persisted-record schemas for Phase 2B reliability infrastructure."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class OperationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=64)
    status: Literal["pending", "started", "completed", "failed", "skipped"]
    started_at: str | None = None
    completed_at: str | None = None
    failure_code: str | None = Field(default=None, max_length=64)


class OperationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str; tenant_id: str; operation_type: str; target_type: str; target_id: str
    idempotency_key: str | None = None; request_id: str; actor_user_id: str; actor_role: str
    audit_operation_id: str; execution_mode: Literal["transactional", "durable_saga"]
    status: Literal["planned", "started", "committing", "succeeded", "failed", "partial", "reconciliation_required"]
    created_at: str; started_at: str; completed_at: str | None; failed_at: str | None; updated_at: str
    version: int = Field(ge=1); current_step: str; steps: list[OperationStep] = Field(max_length=16)
    result_reference: dict[str, str] | None; failure_code: str | None; failure_summary: str | None
    reconciliation_required: bool


class OutboxEventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str; tenant_id: str; operation_id: str; event_type: str; aggregate_type: str; aggregate_id: str
    payload_version: int = 1; payload: dict[str, Any]; created_at: str; available_at: str
    status: Literal["pending", "processing", "retryable", "delivered", "dead_letter"]
    attempt_count: int; last_attempt_at: str | None; next_attempt_at: str | None
    claim_owner: str | None; claim_token: str | None; claim_expires_at: str | None
    delivered_at: str | None; dead_lettered_at: str | None; last_error_code: str | None
    last_error_summary: str | None; version: int


class ReconciliationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str; tenant_id: str; operation_id: str; domain: str; entity_type: str; entity_id: str
    reason_code: str; severity: Literal["critical", "high", "medium", "low"]
    status: Literal["open", "acknowledged", "resolved", "dismissed"]
    owner_role: str; summary: str; created_at: str; updated_at: str; resolved_at: str | None
    version: int; resolution_code: str | None; resolution_summary: str | None

