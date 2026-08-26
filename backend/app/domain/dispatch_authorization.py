"""Pure canonical dispatch-authorization evaluator.

Shadow-evaluates two independent decision points - passport pickup
authorization and boundary stage transitions - through one deterministic,
tri-state evaluator. This module performs no I/O: callers gather evidence
(a Verify response, passport/readiness state, stage-transition inputs)
and this module turns it into bounded reason codes and a decision.

Precedence is fixed and non-negotiable: an explicit negative signal always
wins and produces BLOCKED, regardless of how many unknowns are also
present. Only when there are no explicit negatives do unknown, missing,
insufficient, malformed, stale, timed-out, or unavailable evidence signals
fall the decision back to REVIEW_REQUIRED rather than the extremes on
either side. With neither present, the decision is AUTHORIZED.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

EVALUATOR_VERSION = "1"


class DispatchDecision(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class NegativeReasonCode(str, Enum):
    """Explicit negative evidence. Any one of these forces BLOCKED."""
    VERIFY_BROKER_MC_NOT_FOUND = "verify_broker_mc_not_found"
    VERIFY_BROKER_AUTHORITY_INACTIVE = "verify_broker_authority_inactive"
    VERIFY_BOND_INSURANCE_ABSENT = "verify_bond_insurance_absent"
    VERIFY_FRAUD_RISK_RED = "verify_fraud_risk_red"
    VERIFY_SHARED_CONTACT_REVOKED_ENTITY = "verify_shared_contact_revoked_entity"
    STAGE_TRANSITION_NOT_ALLOWED = "stage_transition_not_allowed"
    PASSPORT_NOT_APPROVED = "passport_not_approved"
    PASSPORT_READINESS_BLOCKED = "passport_readiness_blocked"


class ReviewReasonCode(str, Enum):
    """UNKNOWN/missing/insufficient/malformed/stale/timed-out/unavailable
    evidence. Any one of these (absent a negative) forces REVIEW_REQUIRED."""
    VERIFY_UNAVAILABLE = "verify_unavailable"
    VERIFY_NOT_ATTEMPTED = "verify_not_attempted"
    VERIFY_BROKER_AUTHORITY_UNKNOWN = "verify_broker_authority_unknown"
    VERIFY_BOND_INSURANCE_UNKNOWN = "verify_bond_insurance_unknown"
    VERIFY_FRAUD_RISK_YELLOW = "verify_fraud_risk_yellow"
    EVIDENCE_MISSING = "evidence_missing"
    EVIDENCE_MALFORMED = "evidence_malformed"
    EVIDENCE_STALE = "evidence_stale"
    EVIDENCE_TIMED_OUT = "evidence_timed_out"
    PASSPORT_VERSION_MISMATCH = "passport_version_mismatch"


@dataclass(frozen=True)
class DispatchOutcome:
    decision: DispatchDecision
    reason_codes: tuple[str, ...]
    evaluator_version: str = EVALUATOR_VERSION


def evaluate(negative_reason_codes, review_reason_codes) -> DispatchOutcome:
    """The canonical tri-state evaluator. Pure and deterministic: the same
    two reason-code sets always produce the same outcome."""
    negatives = sorted({NegativeReasonCode(code).value for code in negative_reason_codes})
    if negatives:
        return DispatchOutcome(DispatchDecision.BLOCKED, tuple(negatives))
    reviews = sorted({ReviewReasonCode(code).value for code in review_reason_codes})
    if reviews:
        return DispatchOutcome(DispatchDecision.REVIEW_REQUIRED, tuple(reviews))
    return DispatchOutcome(DispatchDecision.AUTHORIZED, tuple())


def verify_reason_codes(verify_result: dict | None) -> tuple[set[str], set[str]]:
    """Map a Verify response (see app.infrastructure.party_verification_client)
    to bounded negative/review reason codes, using the same status
    vocabulary and blocking/non-blocking classification as
    app.domain.party_verification.evaluate() - the integration is reused,
    not reimplemented."""
    negatives: set[str] = set()
    reviews: set[str] = set()
    if verify_result is None:
        reviews.add(ReviewReasonCode.VERIFY_NOT_ATTEMPTED.value)
        return negatives, reviews
    status = verify_result.get("status")
    if status == "unavailable":
        reviews.add(ReviewReasonCode.VERIFY_UNAVAILABLE.value)
        return negatives, reviews
    if status == "not_found":
        negatives.add(NegativeReasonCode.VERIFY_BROKER_MC_NOT_FOUND.value)
        return negatives, reviews
    if status != "ok":
        reviews.add(ReviewReasonCode.EVIDENCE_MALFORMED.value)
        return negatives, reviews
    authority = verify_result.get("broker_authority_status")
    if authority in (None, "", "UNKNOWN"):
        reviews.add(ReviewReasonCode.VERIFY_BROKER_AUTHORITY_UNKNOWN.value)
    elif authority != "ACTIVE":
        negatives.add(NegativeReasonCode.VERIFY_BROKER_AUTHORITY_INACTIVE.value)
    required = verify_result.get("bond_insurance_required")
    on_file = verify_result.get("bond_insurance_on_file")
    if required == "REQUIRED":
        if on_file == "ABSENT":
            negatives.add(NegativeReasonCode.VERIFY_BOND_INSURANCE_ABSENT.value)
        elif on_file != "PRESENT":
            reviews.add(ReviewReasonCode.VERIFY_BOND_INSURANCE_UNKNOWN.value)
    risk = verify_result.get("risk_level")
    if risk == "Red":
        negatives.add(NegativeReasonCode.VERIFY_FRAUD_RISK_RED.value)
    elif risk == "Yellow":
        reviews.add(ReviewReasonCode.VERIFY_FRAUD_RISK_YELLOW.value)
    for flag in verify_result.get("flags") or []:
        if flag.get("code") == "SHARED_CONTACT_REVOKED_ENTITY":
            negatives.add(NegativeReasonCode.VERIFY_SHARED_CONTACT_REVOKED_ENTITY.value)
    return negatives, reviews


def passport_authorization_reason_codes(passport: dict | None, readiness: dict | None) -> tuple[set[str], set[str]]:
    negatives: set[str] = set()
    reviews: set[str] = set()
    if passport is None:
        reviews.add(ReviewReasonCode.EVIDENCE_MISSING.value)
        return negatives, reviews
    if passport.get("status") != "approved":
        negatives.add(NegativeReasonCode.PASSPORT_NOT_APPROVED.value)
    elif readiness is not None and not readiness.get("ready_for_pickup_authorization", False):
        negatives.add(NegativeReasonCode.PASSPORT_READINESS_BLOCKED.value)
    approved_version = passport.get("approved_version")
    version = passport.get("version")
    if approved_version is not None and version is not None and approved_version != version:
        reviews.add(ReviewReasonCode.PASSPORT_VERSION_MISMATCH.value)
    return negatives, reviews


def boundary_stage_transition_reason_codes(current_stage: str | None, requested_stage: str | None,
                                            transition_is_allowed: bool | None) -> tuple[set[str], set[str]]:
    negatives: set[str] = set()
    reviews: set[str] = set()
    if current_stage is None or requested_stage is None or transition_is_allowed is None:
        reviews.add(ReviewReasonCode.EVIDENCE_MISSING.value)
        return negatives, reviews
    if not transition_is_allowed:
        negatives.add(NegativeReasonCode.STAGE_TRANSITION_NOT_ALLOWED.value)
    return negatives, reviews


def freshness_reason_codes(evidence_freshness: str) -> tuple[set[str], set[str]]:
    """evidence_freshness values come from
    app.schemas.dispatch_authorization.EvidenceFreshness."""
    reviews: set[str] = set()
    if evidence_freshness == "missing":
        reviews.add(ReviewReasonCode.EVIDENCE_MISSING.value)
    elif evidence_freshness == "unavailable":
        reviews.add(ReviewReasonCode.VERIFY_UNAVAILABLE.value)
    return set(), reviews


def evaluate_passport_authorization(*, verify_result: dict | None, passport: dict | None,
                                    readiness: dict | None) -> DispatchOutcome:
    negatives: set[str] = set()
    reviews: set[str] = set()
    for neg, rev in (verify_reason_codes(verify_result), passport_authorization_reason_codes(passport, readiness)):
        negatives |= neg
        reviews |= rev
    return evaluate(negatives, reviews)


def evaluate_boundary_stage_transition(*, verify_result: dict | None, current_stage: str | None,
                                       requested_stage: str | None,
                                       transition_is_allowed: bool | None) -> DispatchOutcome:
    negatives: set[str] = set()
    reviews: set[str] = set()
    for neg, rev in (verify_reason_codes(verify_result),
                     boundary_stage_transition_reason_codes(current_stage, requested_stage, transition_is_allowed)):
        negatives |= neg
        reviews |= rev
    return evaluate(negatives, reviews)
