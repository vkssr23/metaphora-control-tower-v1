from typing import Literal, Optional
from pydantic import Field, model_validator
from .common import StrictMutationModel, StrictUpdateModel, StringEnum

class CheckType(StringEnum):
    DRIVER_ASSIGNMENT="driver_assignment"; DRIVER_OPERATIONAL="driver_operational_status"; CDL="cdl_administrative_status"; MEDICAL="medical_card_administrative_status"; MVR="mvr_administrative_status"; CLEARINGHOUSE="clearinghouse_administrative_status"; EMPLOYMENT="employment_verification_status"
    TRUCK_ASSIGNMENT="truck_assignment"; TRUCK_OPERATIONAL="truck_operational_status"; MAINTENANCE="truck_maintenance_condition"; INSURANCE="truck_insurance_evidence"; TRUCK_EQUIPMENT="truck_equipment_compatibility"
    TRAILER_ID="trailer_identifier"; TRAILER_EQUIPMENT="trailer_equipment_compatibility"; WEIGHT="load_weight_fit"; COMMODITY="commodity_equipment_fit"
    APPOINTMENT="appointment_feasibility"; HOS="hos_readiness"; PICKUP="pickup_readiness"; PARTY="required_party_clearance"; RATE="required_rate_confirmation"; PASSPORT="required_load_passport_state"
class CheckResult(StringEnum):
    PENDING="pending"; PASS="pass"; WARNING="warning"; FAIL="fail"; WAIVED="waived"; EXPIRED="expired"; INSUFFICIENT="insufficient_data"
class ManualSource(StringEnum): MANUAL="manual"
class EmptyAction(StrictMutationModel): pass
class ReasonAction(StrictMutationModel): reason:str=Field(min_length=3,max_length=500)
class CaseCreate(StrictMutationModel):
    trailer_identifier:str=Field(default="",max_length=100)
    trailer_equipment_type:str=Field(default="",max_length=100)
class CaseUpdate(StrictUpdateModel):
    trailer_identifier:Optional[str]=Field(default=None,max_length=100)
    trailer_equipment_type:Optional[str]=Field(default=None,max_length=100)
    operational_notes:Optional[str]=Field(default=None,max_length=2000)
class ManualCheckUpdate(StrictMutationModel):
    result:CheckResult
    source:ManualSource=ManualSource.MANUAL
    reason:str=Field(default="",max_length=500)
    @model_validator(mode="after")
    def waiver_reason(self):
        if self.result==CheckResult.WAIVED and len(self.reason.strip())<3: raise ValueError("Waiver reason is required")
        return self
class HosUpdate(StrictMutationModel):
    source:ManualSource=ManualSource.MANUAL
    available_drive_hours:float=Field(ge=0,le=24,allow_inf_nan=False)
    available_on_duty_hours:float=Field(default=0,ge=0,le=24,allow_inf_nan=False)
    cycle_hours_available:float=Field(default=0,ge=0,le=70,allow_inf_nan=False)
    required_trip_hours:float=Field(ge=0,le=24,allow_inf_nan=False)
    rest_required_before_pickup:bool=False
    reviewed_for_load:bool=True
    notes:str=Field(default="",max_length=1000)
class EvidenceAdd(StrictMutationModel):
    document_ids:list[str]=Field(min_length=1,max_length=25)
class FindingResolution(StringEnum): RESOLVED="resolved"; WAIVED="waived"
class FindingUpdate(StrictMutationModel):
    resolution:FindingResolution
    reason:str=Field(min_length=3,max_length=500)
    evidence_document_ids:list[str]=Field(default_factory=list,max_length=25)
