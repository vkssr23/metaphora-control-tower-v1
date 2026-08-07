from enum import Enum
from typing import Optional
from pydantic import Field, model_validator
from .common import StrictMutationModel, StrictUpdateModel

class CaseStatus(str,Enum):
    DRAFT="draft"; REVIEW_PENDING="review_pending"; FINDINGS_OPEN="findings_open"; CLEARED="cleared"; BLOCKED="blocked"; EXPIRED="expired"; REVOKED="revoked"
class ReviewDomain(str,Enum):
    BROKER="broker_identity"; SHIPPER="shipper_identity"; CARRIER="carrier_authority"; INSURANCE="insurance_evidence"; CONTACT="contact_validation"; PICKUP="pickup_instructions"; FRAUD="fraud_risk"
class ReviewResult(str,Enum):
    PENDING="pending"; MATCH="match"; MISMATCH="mismatch"; EVIDENCE_PRESENT="evidence_present"; INSUFFICIENT="insufficient_evidence"; WAIVED="waived"; EXPIRED="expired"; BLOCKED="blocked"
class ReviewSource(str,Enum):
    MANUAL="manual"; SYSTEM="system"; FUTURE_FMCSA="future_fmcsa"; FUTURE_INSURANCE="future_insurance"; FUTURE_IDENTITY="future_identity"; FUTURE_FRAUD="future_fraud_provider"
class FindingResolution(str,Enum):
    CONFIRMED="confirmed_match"; ACCEPTED="accepted_internal_value"; CORRECTED="corrected_canonical_data"; EVIDENCE="additional_evidence_provided"; FALSE_POSITIVE="false_positive"; WAIVED="waived"; BLOCKED="blocked"

class CaseCreate(StrictMutationModel): pass
class CaseUpdate(StrictUpdateModel):
    notes: Optional[str]=Field(default=None,max_length=1000)
class EmptyAction(StrictMutationModel): pass
class ReasonAction(StrictMutationModel): reason:str=Field(min_length=1,max_length=500)
class ReviewUpdate(StrictMutationModel):
    result:ReviewResult; source:ReviewSource=ReviewSource.MANUAL; reason:str=Field(default="",max_length=500); evidence_document_ids:list[str]=Field(default_factory=list,max_length=20)
    @model_validator(mode="after")
    def manual_only(self):
        if self.source != ReviewSource.MANUAL: raise ValueError("Clients may only submit manual review data in Phase 1C")
        if self.result == ReviewResult.WAIVED and not self.reason: raise ValueError("A waiver requires a reason")
        return self
class FindingUpdate(StrictMutationModel):
    resolution:FindingResolution; reason:str=Field(min_length=1,max_length=500); evidence_document_ids:list[str]=Field(default_factory=list,max_length=20)
class EvidenceAdd(StrictMutationModel):
    document_ids:list[str]=Field(min_length=1,max_length=20)
