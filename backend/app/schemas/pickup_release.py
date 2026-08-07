from typing import Literal, Optional
from pydantic import Field, model_validator
from .common import StrictMutationModel, StrictUpdateModel, StringEnum

class ChecklistType(StringEnum):
    LOAD_PASSPORT="load_passport_current"; RATE="rate_confirmation_current"; PARTY="party_verification_current"; EXECUTION="execution_eligibility_current"
    DRIVER="driver_assignment_current"; TRUCK="truck_assignment_current"; TRAILER="trailer_identifier_current"
    FACILITY="pickup_facility_current"; ADDRESS="pickup_address_current"; DATE="pickup_date_current"; TIME="pickup_time_current"; REFERENCE="pickup_reference_current"; CONTACT="pickup_contact_current"; EQUIPMENT="equipment_current"; COMMODITY="commodity_current"
    FINDINGS="no_unresolved_blocking_findings"; CHANGE="no_last_minute_material_change"; AUTH="pickup_authorization_not_already_active"; SNAPSHOT="release_snapshot_current"
class ChecklistResult(StringEnum):
    PENDING="pending"; PASS="pass"; WARNING="warning"; FAIL="fail"; WAIVED="waived"; INSUFFICIENT="insufficient_data"
class EmptyAction(StrictMutationModel): pass
class CaseCreate(StrictMutationModel): pass
class CaseUpdate(StrictUpdateModel):
    operational_notes:Optional[str]=Field(None,max_length=2000)
class ReasonAction(StrictMutationModel): reason:str=Field(min_length=3,max_length=500)
class ChecklistUpdate(StrictMutationModel):
    result:ChecklistResult; reason:str=Field(default="",max_length=500)
    @model_validator(mode="after")
    def valid_reason(self):
        if self.result==ChecklistResult.WAIVED and len(self.reason.strip())<3: raise ValueError("Waiver reason is required")
        return self
class FindingUpdate(StrictMutationModel):
    resolution:Literal["confirmed_match","corrected_canonical_data","additional_evidence","manual_review_complete","false_positive","waived","blocked"]
    reason:str=Field(min_length=3,max_length=500)
class EvidenceAdd(StrictMutationModel): document_ids:list[str]=Field(min_length=1,max_length=25)
class DriverAcknowledge(StrictMutationModel): source:Literal["manual"]="manual"
class PickupConfirm(StrictMutationModel): source:Literal["manual"]="manual"; reference:str=Field(default="",max_length=200)
class ExceptionAction(StrictMutationModel):
    exception_type:Literal["pickup_refused","facility_closed","assignment_conflict","instruction_conflict","custody_dispute","other"]
    reason:str=Field(min_length=3,max_length=500)
