from enum import Enum
from typing import Optional
from pydantic import Field, model_validator
from .common import StrictMutationModel, StrictUpdateModel

class PassportStatus(str, Enum):
    DRAFT="draft"; REVIEW_PENDING="review_pending"; BLOCKED="blocked"; APPROVED="approved"; PICKUP_AUTHORIZED="pickup_authorized"; REVOKED="revoked"
class CheckpointType(str, Enum):
    LOAD_DETAILS="load_details"; RATE_CONFIRMATION="rate_confirmation"; BROKER_IDENTITY="broker_identity"; SHIPPER_IDENTITY="shipper_identity"; PROFITABILITY="profitability"; DRIVER_ELIGIBILITY="driver_eligibility"; TRUCK_ELIGIBILITY="truck_eligibility"; TRAILER_ELIGIBILITY="trailer_eligibility"; APPOINTMENT_FEASIBILITY="appointment_feasibility"; PICKUP_INSTRUCTIONS="pickup_instructions"
class CheckpointStatus(str, Enum):
    PENDING="pending"; PASS="pass"; FAIL="fail"; WAIVED="waived"; EXPIRED="expired"
class CheckpointSource(str, Enum):
    MANUAL="manual"; SYSTEM="system"; FUTURE_INTEGRATION="future_integration"

class PassportCreate(StrictMutationModel):
    trailer_identifier: str = Field(default="", max_length=100)
class PassportUpdate(StrictUpdateModel):
    trailer_identifier: Optional[str] = Field(default=None, max_length=100)
class CheckpointUpdate(StrictMutationModel):
    status: CheckpointStatus
    blocking: bool = True
    reason_code: str = Field(default="", max_length=64, pattern=r"^[a-z0-9_\-]*$")
    notes: str = Field(default="", max_length=1000)
    evidence_document_ids: list[str] = Field(default_factory=list, max_length=20)
    expires_at: Optional[str] = Field(default=None, max_length=64)
    source: CheckpointSource = CheckpointSource.MANUAL
    @model_validator(mode="after")
    def controlled_decision(self):
        if self.status == CheckpointStatus.WAIVED and not self.reason_code: raise ValueError("Waived checkpoints require a reason_code")
        if self.source != CheckpointSource.MANUAL: raise ValueError("Clients may only record a manual source in Phase 1A")
        return self
class ReasonAction(StrictMutationModel):
    reason: str = Field(min_length=1, max_length=500)
class EmptyAction(StrictMutationModel):
    pass
