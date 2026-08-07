from enum import Enum
from math import isfinite
from typing import Optional, Literal
import re
from datetime import date, time

from pydantic import EmailStr, Field, field_validator, model_validator
from .common import StrictMutationModel, StrictUpdateModel

class ExtractionStatus(str, Enum):
    DRAFT="draft"; REVIEW_PENDING="review_pending"; DISCREPANCIES_FOUND="discrepancies_found"; ACCEPTED="accepted"; REJECTED="rejected"; SUPERSEDED="superseded"
class ExtractionSource(str, Enum):
    MANUAL="manual"; STRUCTURED_IMPORT="structured_import"; SYSTEM="system"; FUTURE_OCR="future_ocr"; FUTURE_AI="future_ai"
class ResolutionStatus(str, Enum):
    UNRESOLVED="unresolved"; ACCEPTED_AS_DOCUMENT="accepted_as_document"; ACCEPTED_AS_LOAD="accepted_as_load"; CORRECTED_DOCUMENT_ENTRY="corrected_document_entry"; CORRECTED_LOAD="corrected_load"; WAIVED="waived"

TEXT_FIELDS = {
    "rate_confirmation_number","customer_reference","broker_reference","broker_name","broker_mc","broker_contact_name","broker_contact_phone","carrier_name","shipper_name","consignee_name","commodity","equipment_type","pickup_name","pickup_address","pickup_city","pickup_state","pickup_postal_code","pickup_number","delivery_name","delivery_address","delivery_city","delivery_state","delivery_postal_code","delivery_number","temperature_requirement","seal_requirement","lumper_terms","detention_terms","payment_terms"
}
NUMERIC_FIELDS = {"linehaul_rate","fuel_surcharge","accessorial_total","total_rate","advance_amount","quick_pay_fee","detention_rate","layover_rate","tonu_rate","weight","piece_count","loaded_miles","deadhead_miles"}
DATE_FIELDS={"document_date","pickup_date","delivery_date"}; TIME_FIELDS={"pickup_time_start","pickup_time_end","delivery_time_start","delivery_time_end"}
LONG_FIELDS={"special_instructions"}
EXTRACTED_FIELD_NAMES=frozenset(TEXT_FIELDS|NUMERIC_FIELDS|DATE_FIELDS|TIME_FIELDS|LONG_FIELDS|{"broker_contact_email"})

class ExtractedFields(StrictMutationModel):
    rate_confirmation_number: Optional[str]=Field(None,max_length=100); document_date: Optional[str]=None; customer_reference: Optional[str]=Field(None,max_length=150); broker_reference: Optional[str]=Field(None,max_length=150)
    broker_name: Optional[str]=Field(None,max_length=200); broker_mc: Optional[str]=Field(None,max_length=50); broker_contact_name: Optional[str]=Field(None,max_length=150); broker_contact_email: Optional[EmailStr]=None; broker_contact_phone: Optional[str]=Field(None,max_length=40)
    carrier_name: Optional[str]=Field(None,max_length=200); shipper_name: Optional[str]=Field(None,max_length=200); consignee_name: Optional[str]=Field(None,max_length=200)
    linehaul_rate: Optional[float]=Field(None,ge=0); fuel_surcharge: Optional[float]=Field(None,ge=0); accessorial_total: Optional[float]=Field(None,ge=0); total_rate: Optional[float]=Field(None,ge=0); advance_amount: Optional[float]=Field(None,ge=0); quick_pay_fee: Optional[float]=Field(None,ge=0); detention_rate: Optional[float]=Field(None,ge=0); layover_rate: Optional[float]=Field(None,ge=0); tonu_rate: Optional[float]=Field(None,ge=0)
    commodity: Optional[str]=Field(None,max_length=200); weight: Optional[float]=Field(None,ge=0); equipment_type: Optional[str]=Field(None,max_length=100); piece_count: Optional[int]=Field(None,ge=0); loaded_miles: Optional[float]=Field(None,ge=0); deadhead_miles: Optional[float]=Field(None,ge=0)
    pickup_name: Optional[str]=Field(None,max_length=200); pickup_address: Optional[str]=Field(None,max_length=300); pickup_city: Optional[str]=Field(None,max_length=100); pickup_state: Optional[str]=Field(None,max_length=50); pickup_postal_code: Optional[str]=Field(None,max_length=20); pickup_date: Optional[str]=None; pickup_time_start: Optional[str]=None; pickup_time_end: Optional[str]=None; pickup_number: Optional[str]=Field(None,max_length=100)
    delivery_name: Optional[str]=Field(None,max_length=200); delivery_address: Optional[str]=Field(None,max_length=300); delivery_city: Optional[str]=Field(None,max_length=100); delivery_state: Optional[str]=Field(None,max_length=50); delivery_postal_code: Optional[str]=Field(None,max_length=20); delivery_date: Optional[str]=None; delivery_time_start: Optional[str]=None; delivery_time_end: Optional[str]=None; delivery_number: Optional[str]=Field(None,max_length=100)
    special_instructions: Optional[str]=Field(None,max_length=2000); temperature_requirement: Optional[str]=Field(None,max_length=200); seal_requirement: Optional[str]=Field(None,max_length=200); lumper_terms: Optional[str]=Field(None,max_length=500); detention_terms: Optional[str]=Field(None,max_length=500); payment_terms: Optional[str]=Field(None,max_length=500)
    @field_validator(*NUMERIC_FIELDS)
    @classmethod
    def finite_numbers(cls,v):
        if v is not None and not isfinite(v): raise ValueError("Must be finite")
        return v
    @field_validator(*DATE_FIELDS)
    @classmethod
    def valid_date(cls,v):
        if v is not None: date.fromisoformat(v)
        return v
    @field_validator(*TIME_FIELDS)
    @classmethod
    def valid_time(cls,v):
        if v is not None: time.fromisoformat(v)
        return v
    @field_validator("broker_contact_phone")
    @classmethod
    def valid_phone(cls,v):
        if v is not None and not re.fullmatch(r"[0-9+(). xX-]{7,40}",v): raise ValueError("Invalid phone")
        return v

class ExtractionCreate(StrictMutationModel):
    document_id: str=Field(min_length=1,max_length=128)
    source: ExtractionSource=ExtractionSource.MANUAL
    extracted_fields: ExtractedFields=Field(default_factory=ExtractedFields)
    extraction_confidence: dict[str,float]=Field(default_factory=dict)
    notes: str=Field(default="",max_length=1000)
    @model_validator(mode="after")
    def source_contract(self):
        if self.source in {ExtractionSource.SYSTEM,ExtractionSource.FUTURE_OCR,ExtractionSource.FUTURE_AI}: raise ValueError("Source is not client-active in Phase 1B")
        if self.source==ExtractionSource.MANUAL and self.extraction_confidence: raise ValueError("Manual extraction cannot submit confidence")
        if any(k not in EXTRACTED_FIELD_NAMES or not isfinite(v) or v<0 or v>1 for k,v in self.extraction_confidence.items()): raise ValueError("Invalid field confidence")
        return self
class ExtractionUpdate(StrictUpdateModel):
    extracted_fields: Optional[ExtractedFields]=None
    notes: Optional[str]=Field(None,max_length=1000)
class ConfidenceUpdate(StrictMutationModel):
    extraction_confidence: dict[str,float]=Field(max_length=100)
    @field_validator("extraction_confidence")
    @classmethod
    def valid_confidence(cls,value):
        if any(k not in EXTRACTED_FIELD_NAMES or not isfinite(v) or v<0 or v>1 for k,v in value.items()): raise ValueError("Invalid field confidence")
        return value
class CompareAction(StrictMutationModel): pass
class SubmitAction(StrictMutationModel): pass
class AcceptAction(StrictMutationModel): pass
class RejectAction(StrictMutationModel): reason: str=Field(min_length=1,max_length=500)
class SupersedeAction(StrictMutationModel): reason: str=Field(min_length=1,max_length=500)
class ResolutionUpdate(StrictMutationModel):
    resolution: ResolutionStatus
    decision: Literal["keep_load_value","use_document_value","corrected_value"]
    corrected_value: Optional[str|float|int]=None
    reason: str=Field(default="",max_length=500)
    @model_validator(mode="after")
    def complete(self):
        if self.decision=="corrected_value" and self.corrected_value is None: raise ValueError("corrected_value is required")
        if self.resolution==ResolutionStatus.WAIVED and not self.reason: raise ValueError("Waiver requires a reason")
        return self
