from typing import Literal
from pydantic import Field, field_validator
from .common import StrictMutationModel, finite, validate_date_or_empty

Source=Literal["manual"]
class Versioned(StrictMutationModel): version:int=Field(ge=1)
class StartAction(StrictMutationModel): pass
class EmptyAction(Versioned): pass
class Progress(Versioned):
    source:Source="manual"; current_location_text:str=Field(default="",max_length=200); current_state_region:str=Field(default="",max_length=50); current_stop_index:int|None=Field(default=None,ge=0,le=100); remaining_miles_estimate:float|None=Field(default=None,ge=0,le=100000); driver_reported_eta:str=""; delay_minutes_estimate:int=Field(default=0,ge=0,le=100000); status_note:str=Field(default="",max_length=1000); route_status:Literal["unknown","nominal","possible_deviation"]="unknown"
    _finite=field_validator("remaining_miles_estimate")(finite)
    _time=field_validator("driver_reported_eta")(validate_date_or_empty)
class StopAction(Versioned):
    source:Source="manual"; location_text:str=Field(default="",max_length=200); reference:str=Field(default="",max_length=100)
class DetentionStart(Versioned):
    stop_index:int=Field(ge=0,le=100); source:Source="manual"; reason:str=Field(default="",max_length=500); supporting_document_ids:list[str]=Field(default_factory=list,max_length=20)
class DetentionEnd(Versioned):
    source:Source="manual"; reason:str=Field(default="",max_length=500)
class EtaEvaluate(Versioned):
    source:Source="manual"; manual_eta:str=""
    _time=field_validator("manual_eta")(validate_date_or_empty)
class ExceptionCreate(Versioned):
    type:Literal["pickup_departure_delayed","delivery_eta_at_risk","delivery_eta_late","appointment_missed","detention_active","detention_exceeds_threshold","driver_assignment_changed","truck_assignment_changed","trailer_assignment_changed","driver_unavailable","driver_reported_issue","truck_issue_reported","truck_status_changed","maintenance_issue_reported","possible_route_deviation","route_progress_unknown","custody_state_conflict","pickup_authorization_conflict","pickup_confirmation_conflict","pod_missing","required_document_missing","delivery_arrival_exception","delivery_confirmation_conflict","consignee_issue_reported","driver_update_overdue","operations_followup_required"]
    category:Literal["timing","detention","assignment","driver","truck","trailer","route","custody","document","delivery","communication","compliance","other"]
    severity:Literal["info","warning","high","critical"]; blocking:bool=False; title:str=Field(min_length=1,max_length=120); summary:str=Field(default="",max_length=1000); owner_user_id:str|None=Field(default=None,max_length=100); related_document_ids:list[str]=Field(default_factory=list,max_length=20)
class ExceptionAction(Versioned): reason:str=Field(default="",max_length=1000)
class AssignException(Versioned): owner_user_id:str=Field(min_length=1,max_length=100)
class DeliveryConfirm(Versioned):
    receiver_name:str=Field(default="",max_length=200); delivery_reference:str=Field(default="",max_length=100); evidence_document_ids:list[str]=Field(default_factory=list,max_length=20); note:str=Field(default="",max_length=1000); source:Source="manual"
class AmendPlan(Versioned): delivery_appt:str|None=None; delivery_address:str|None=Field(default=None,max_length=300); driver_id:str|None=Field(default=None,max_length=100); truck_id:str|None=Field(default=None,max_length=100); reason:str=Field(min_length=1,max_length=1000)
