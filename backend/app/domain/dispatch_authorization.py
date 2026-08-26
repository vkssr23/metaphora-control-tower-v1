"""Pure canonical dispatch-authorization evaluator.

Shadow-evaluates two independent decision points - passport pickup
authorization and the dispatch boundary stage transition - through one
deterministic, tri-state evaluator. This module performs no I/O: callers
gather evidence (a Verify response, passport/readiness state, the latest
Party Verification and Execution Eligibility cases, stage-transition
inputs) and this module turns it into bounded reason codes and a
decision.

Precedence is fixed and non-negotiable: an explicit negative signal always
wins and produces BLOCKED, regardless of how many unknowns are also
present. Only when there are no explicit negatives do unknown, missing,
insufficient, malformed, or unavailable/timed-out evidence signals fall
the decision back to REVIEW_REQUIRED rather than either extreme.
AUTHORIZED requires every required authority to be affirmatively
positive - a missing, pending, or ambiguous authority is never treated as
clean.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.schemas.loads import LoadStage

EVALUATOR_VERSION = "2"

# The dispatch boundary is exactly the Assigned -> Dispatched edge: the
# moment a load becomes actively dispatched. Every other stage transition
# - including ordinary invalid transitions, exception entry from
# Dispatched, and exception recovery back into Dispatched - is outside
# this boundary and must never trigger a shadow evaluation or a Verify
# call.
DISPATCH_BOUNDARY_TRANSITION = (LoadStage.ASSIGNED, LoadStage.DISPATCHED)


def is_dispatch_boundary_transition(current_stage, requested_stage) -> bool:
    return (current_stage, requested_stage) == DISPATCH_BOUNDARY_TRANSITION


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
    PASSPORT_BLOCKED = "passport_blocked"
    PASSPORT_REVOKED = "passport_revoked"
    PARTY_VERIFICATION_BLOCKED = "party_verification_blocked"
    EXECUTION_ELIGIBILITY_BLOCKED = "execution_eligibility_blocked"


class ReviewReasonCode(str, Enum):
    """UNKNOWN/missing/insufficient/malformed/unavailable/timed-out
    evidence. Any one of these (absent a negative) forces REVIEW_REQUIRED."""
    VERIFY_UNAVAILABLE = "verify_unavailable"
    VERIFY_NOT_ATTEMPTED = "verify_not_attempted"
    VERIFY_TIMED_OUT = "verify_timed_out"
    VERIFY_BROKER_AUTHORITY_UNKNOWN = "verify_broker_authority_unknown"
    VERIFY_BOND_INSURANCE_REQUIREMENT_UNKNOWN = "verify_bond_insurance_requirement_unknown"
    VERIFY_BOND_INSURANCE_ON_FILE_UNKNOWN = "verify_bond_insurance_on_file_unknown"
    VERIFY_FRAUD_RISK_YELLOW = "verify_fraud_risk_yellow"
    EVIDENCE_MISSING = "evidence_missing"
    EVIDENCE_MALFORMED = "evidence_malformed"
    PASSPORT_NOT_YET_APPROVED = "passport_not_yet_approved"
    PASSPORT_READINESS_INCOMPLETE = "passport_readiness_incomplete"
    PASSPORT_VERSION_MISMATCH = "passport_version_mismatch"
    PARTY_VERIFICATION_MISSING = "party_verification_missing"
    PARTY_VERIFICATION_NOT_CLEARED = "party_verification_not_cleared"
    EXECUTION_ELIGIBILITY_MISSING = "execution_eligibility_missing"
    EXECUTION_ELIGIBILITY_NOT_ELIGIBLE = "execution_eligibility_not_eligible"


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
    not reimplemented. "timed_out" is produced only by the shadow caller's
    own bounded wait (app.dispatch_authorization_shadow), not by the
    client itself."""
    negatives: set[str] = set()
    reviews: set[str] = set()
    if verify_result is None:
        reviews.add(ReviewReasonCode.VERIFY_NOT_ATTEMPTED.value)
        return negatives, reviews
    status = verify_result.get("status")
    if status == "timed_out":
        reviews.add(ReviewReasonCode.VERIFY_TIMED_OUT.value)
        return negatives, reviews
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
    if required in (None, "", "UNKNOWN"):
        reviews.add(ReviewReasonCode.VERIFY_BOND_INSURANCE_REQUIREMENT_UNKNOWN.value)
    elif required == "REQUIRED":
        if on_file == "ABSENT":
            negatives.add(NegativeReasonCode.VERIFY_BOND_INSURANCE_ABSENT.value)
        elif on_file != "PRESENT":
            reviews.add(ReviewReasonCode.VERIFY_BOND_INSURANCE_ON_FILE_UNKNOWN.value)
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
    """status=="blocked"/"revoked" is an explicit human decision (via the
    reject/revoke actions, both of which require a reason) and is treated
    as a negative. Every other non-approved status (draft, review_pending)
    and a False readiness boolean are pending/insufficient states, not
    denials, so they fall to REVIEW_REQUIRED rather than being collapsed
    into a blocking signal."""
    negatives: set[str] = set()
    reviews: set[str] = set()
    if passport is None:
        reviews.add(ReviewReasonCode.EVIDENCE_MISSING.value)
        return negatives, reviews
    status = passport.get("status")
    if status == "blocked":
        negatives.add(NegativeReasonCode.PASSPORT_BLOCKED.value)
    elif status == "revoked":
        negatives.add(NegativeReasonCode.PASSPORT_REVOKED.value)
    elif status != "approved":
        reviews.add(ReviewReasonCode.PASSPORT_NOT_YET_APPROVED.value)
    elif readiness is not None and not readiness.get("ready_for_pickup_authorization", False):
        reviews.add(ReviewReasonCode.PASSPORT_READINESS_INCOMPLETE.value)
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


def party_verification_reason_codes(case: dict | None) -> tuple[set[str], set[str]]:
    """"cleared" is the only affirmatively positive status. "blocked" is
    the only explicit negative (reached only via an admin's reasoned block
    action). Every other status - draft, review_pending, findings_open,
    expired, revoked, or a missing case entirely - is pending/ambiguous
    evidence, not a denial."""
    if case is None:
        return set(), {ReviewReasonCode.PARTY_VERIFICATION_MISSING.value}
    status = case.get("status")
    if status == "blocked":
        return {NegativeReasonCode.PARTY_VERIFICATION_BLOCKED.value}, set()
    if status != "cleared":
        return set(), {ReviewReasonCode.PARTY_VERIFICATION_NOT_CLEARED.value}
    return set(), set()


def execution_eligibility_reason_codes(case: dict | None) -> tuple[set[str], set[str]]:
    """Same shape as party_verification_reason_codes: "eligible" is the
    only affirmatively positive status, "blocked" the only explicit
    negative."""
    if case is None:
        return set(), {ReviewReasonCode.EXECUTION_ELIGIBILITY_MISSING.value}
    status = case.get("status")
    if status == "blocked":
        return {NegativeReasonCode.EXECUTION_ELIGIBILITY_BLOCKED.value}, set()
    if status != "eligible":
        return set(), {ReviewReasonCode.EXECUTION_ELIGIBILITY_NOT_ELIGIBLE.value}
    return set(), set()


def evaluate_passport_authorization(*, verify_result: dict | None, passport: dict | None,
                                    readiness: dict | None, party_verification_case: dict | None) -> DispatchOutcome:
    negatives: set[str] = set()
    reviews: set[str] = set()
    for neg, rev in (
        verify_reason_codes(verify_result),
        passport_authorization_reason_codes(passport, readiness),
        party_verification_reason_codes(party_verification_case),
    ):
        negatives |= neg
        reviews |= rev
    return evaluate(negatives, reviews)


def evaluate_boundary_stage_transition(*, verify_result: dict | None, current_stage: str | None,
                                       requested_stage: str | None, transition_is_allowed: bool | None,
                                       party_verification_case: dict | None,
                                       execution_eligibility_case: dict | None) -> DispatchOutcome:
    negatives: set[str] = set()
    reviews: set[str] = set()
    for neg, rev in (
        verify_reason_codes(verify_result),
        boundary_stage_transition_reason_codes(current_stage, requested_stage, transition_is_allowed),
        party_verification_reason_codes(party_verification_case),
        execution_eligibility_reason_codes(execution_eligibility_case),
    ):
        negatives |= neg
        reviews |= rev
    return evaluate(negatives, reviews)
