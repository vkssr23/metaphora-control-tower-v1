"""Bounded, append-only record of a dispatch-authorization shadow evaluation.

Mirrors the app.domain.audit_events discipline: a persisted evaluation
never stores evidence contents or secrets, only the decision, bounded
reason codes, source identifiers/versions, evidence freshness, and
timing metadata.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class EvaluationSubject(str, Enum):
    PASSPORT_AUTHORIZATION = "passport_authorization"
    BOUNDARY_STAGE_TRANSITION = "boundary_stage_transition"


class DispatchDecision(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class EvidenceFreshness(str, Enum):
    CURRENT = "current"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"
    MISSING = "missing"


class EvaluationMode(str, Enum):
    """PR1 only ever writes SHADOW: no flag anywhere reads this value to
    change behavior. A later change introduces an ENFORCED mode plus the
    logic that actually gates on it."""
    SHADOW = "SHADOW"


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(max_length=64)
    id: str = Field(default="", max_length=128)
    version: str = Field(default="", max_length=64)


class DispatchAuthorizationEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    tenant_id: str
    load_id: str
    subject: EvaluationSubject
    decision: DispatchDecision
    evaluator_version: str = Field(max_length=16)
    load_version: str = Field(default="", max_length=64)
    reason_codes: list[str] = Field(default_factory=list, max_length=16)
    sources: list[SourceReference] = Field(default_factory=list, max_length=8)
    evidence_freshness: EvidenceFreshness
    mode: EvaluationMode = EvaluationMode.SHADOW
    evaluated_at: str
    input_hash: str = Field(max_length=64)
