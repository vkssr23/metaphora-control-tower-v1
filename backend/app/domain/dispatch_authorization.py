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
    PARTY_VERIFICATION_AMBIGUOUS = "party_verification_ambiguous"
    EXECUTION_ELIGIBILITY_MISSING = "execution_eligibility_missing"
    EXECUTION_ELIGIBILITY_NOT_ELIGIBLE = "execution_eligibility_not_eligible"
    EXECUTION_ELIGIBILITY_AMBIGUOUS = "execution_eligibility_ambiguous"


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


# Verify's own documented canonical vocabulary (see
# app.infrastructure.party_verification_client and
# app.domain.party_verification's evaluate()). Anything outside these
# known sets - including a value outside {ACTIVE}+_AUTHORITY_NEGATIVE, or
# a risk_level outside {Green,Yellow,Red} - is treated as malformed
# evidence, never silently ignored and never treated as if it were the
# documented UNKNOWN/undisclosed state.
_AUTHORITY_NEGATIVE = {"INACTIVE", "OUT_OF_SERVICE", "NOT_AUTHORIZED"}
_UNDISCLOSED = (None, "", "UNKNOWN")


def verify_reason_codes(verify_result: dict | None) -> tuple[set[str], set[str]]:
    """Map a Verify response to bounded negative/review reason codes.
    Every canonical field required for AUTHORIZED - broker authority,
    bond requirement/on-file, risk level - is validated strictly against
    Verify's documented vocabulary: the expected positive value is clean,
    a documented negative value blocks, the documented UNKNOWN/undisclosed
    state is a review, and any other unexpected value is malformed (also a
    review) rather than being coerced into either extreme. "timed_out" is
    produced only by the shadow caller's own bounded wait
    (app.dispatch_authorization_shadow), not by the client itself."""
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
    if authority == "ACTIVE":
        pass
    elif authority in _AUTHORITY_NEGATIVE:
        negatives.add(NegativeReasonCode.VERIFY_BROKER_AUTHORITY_INACTIVE.value)
    elif authority in _UNDISCLOSED:
        reviews.add(ReviewReasonCode.VERIFY_BROKER_AUTHORITY_UNKNOWN.value)
    else:
        reviews.add(ReviewReasonCode.EVIDENCE_MALFORMED.value)

    required = verify_result.get("bond_insurance_required")
    on_file = verify_result.get("bond_insurance_on_file")
    if required == "NOT_REQUIRED":
        pass
    elif required == "REQUIRED":
        if on_file == "PRESENT":
            pass
        elif on_file == "ABSENT":
            negatives.add(NegativeReasonCode.VERIFY_BOND_INSURANCE_ABSENT.value)
        elif on_file in _UNDISCLOSED:
            reviews.add(ReviewReasonCode.VERIFY_BOND_INSURANCE_ON_FILE_UNKNOWN.value)
        else:
            reviews.add(ReviewReasonCode.EVIDENCE_MALFORMED.value)
    elif required in _UNDISCLOSED:
        reviews.add(ReviewReasonCode.VERIFY_BOND_INSURANCE_REQUIREMENT_UNKNOWN.value)
    else:
        reviews.add(ReviewReasonCode.EVIDENCE_MALFORMED.value)

    risk = verify_result.get("risk_level")
    if risk == "Green":
        pass
    elif risk == "Yellow":
        reviews.add(ReviewReasonCode.VERIFY_FRAUD_RISK_YELLOW.value)
    elif risk == "Red":
        negatives.add(NegativeReasonCode.VERIFY_FRAUD_RISK_RED.value)
    else:
        reviews.add(ReviewReasonCode.EVIDENCE_MALFORMED.value)

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


def _party_verification_has_blocking_evidence(case: dict) -> bool:
    """Checks the case's actual evidence, not just its top-level status:
    unresolved/open blocking findings, a nonzero blocking-signal count, or
    populated current blocking reasons (see app.domain.party_verification.
    evaluate(): blocking_reasons/risk_summary.blocking_signal_count are
    computed from exactly these open+blocking findings)."""
    if case.get("blocking_reasons"):
        return True
    if (case.get("risk_summary") or {}).get("blocking_signal_count"):
        return True
    if any(f.get("status") == "open" and f.get("blocking") for f in case.get("findings") or []):
        return True
    return False


def party_verification_reason_codes(case: dict | None, ambiguous: bool = False) -> tuple[set[str], set[str]]:
    """"cleared" with no residual blocking evidence is the only
    affirmatively positive state. status in {"blocked","revoked"}, or any
    unresolved blocking evidence regardless of status (including a stale
    "cleared" case that still carries blocking evidence), is an explicit
    negative. Every other status - draft, review_pending, findings_open,
    expired, a missing case, or more than one matching case for this
    tenant+load (ambiguous) - is pending/ambiguous evidence, not a denial."""
    if ambiguous:
        return set(), {ReviewReasonCode.PARTY_VERIFICATION_AMBIGUOUS.value}
    if case is None:
        return set(), {ReviewReasonCode.PARTY_VERIFICATION_MISSING.value}
    status = case.get("status")
    if status in ("blocked", "revoked") or _party_verification_has_blocking_evidence(case):
        return {NegativeReasonCode.PARTY_VERIFICATION_BLOCKED.value}, set()
    if status != "cleared":
        return set(), {ReviewReasonCode.PARTY_VERIFICATION_NOT_CLEARED.value}
    return set(), set()


def _execution_eligibility_has_blocking_evidence(case: dict) -> bool:
    """Verdict "blocked" is this codebase's actual ineligible verdict (see
    app.domain.execution_eligibility.verdict()); "ineligible" never
    appears as a literal value here. Also checks blocking_reasons and any
    explicit failed/expired required check, not just the top-level
    status/verdict fields."""
    if case.get("verdict") == "blocked":
        return True
    if case.get("blocking_reasons"):
        return True
    if any(c.get("result") in ("fail", "expired") for c in case.get("checks") or []):
        return True
    return False


def execution_eligibility_reason_codes(case: dict | None, ambiguous: bool = False) -> tuple[set[str], set[str]]:
    """Positive only when status=="eligible", verdict=="eligible", and no
    residual blocking evidence remains. status in {"blocked","revoked"} or
    any blocking evidence is an explicit negative regardless of status.
    Everything else pending/insufficient/expired/ambiguous falls to
    review."""
    if ambiguous:
        return set(), {ReviewReasonCode.EXECUTION_ELIGIBILITY_AMBIGUOUS.value}
    if case is None:
        return set(), {ReviewReasonCode.EXECUTION_ELIGIBILITY_MISSING.value}
    status = case.get("status")
    if status in ("blocked", "revoked") or _execution_eligibility_has_blocking_evidence(case):
        return {NegativeReasonCode.EXECUTION_ELIGIBILITY_BLOCKED.value}, set()
    if status != "eligible" or case.get("verdict") != "eligible":
        return set(), {ReviewReasonCode.EXECUTION_ELIGIBILITY_NOT_ELIGIBLE.value}
    return set(), set()


def evaluate_passport_authorization(*, verify_result: dict | None, passport: dict | None,
                                    readiness: dict | None, party_verification_case: dict | None,
                                    party_verification_ambiguous: bool = False) -> DispatchOutcome:
    negatives: set[str] = set()
    reviews: set[str] = set()
    for neg, rev in (
        verify_reason_codes(verify_result),
        passport_authorization_reason_codes(passport, readiness),
        party_verification_reason_codes(party_verification_case, party_verification_ambiguous),
    ):
        negatives |= neg
        reviews |= rev
    return evaluate(negatives, reviews)


def evaluate_boundary_stage_transition(*, verify_result: dict | None, current_stage: str | None,
                                       requested_stage: str | None, transition_is_allowed: bool | None,
                                       party_verification_case: dict | None,
                                       execution_eligibility_case: dict | None,
                                       party_verification_ambiguous: bool = False,
                                       execution_eligibility_ambiguous: bool = False) -> DispatchOutcome:
    negatives: set[str] = set()
    reviews: set[str] = set()
    for neg, rev in (
        verify_reason_codes(verify_result),
        boundary_stage_transition_reason_codes(current_stage, requested_stage, transition_is_allowed),
        party_verification_reason_codes(party_verification_case, party_verification_ambiguous),
        execution_eligibility_reason_codes(execution_eligibility_case, execution_eligibility_ambiguous),
    ):
        negatives |= neg
        reviews |= rev
    return evaluate(negatives, reviews)
