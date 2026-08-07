from decimal import Decimal
from typing import Literal
from pydantic import Field, field_validator
from .common import StrictMutationModel, StrictUpdateModel

AccessorialType=Literal["detention","lumper","layover","stop_off","driver_assist","truck_order_not_used","redelivery","storage","toll","other_controlled"]
Currency=Literal["USD"]

class VersionAction(StrictMutationModel):
    version:int=Field(ge=1)
class CaseCreate(StrictMutationModel):
    pass
class CaseUpdate(StrictUpdateModel):
    version:int=Field(ge=1)
    finance_note:str|None=Field(default=None,max_length=1000)
class ReasonAction(VersionAction):
    reason:str=Field(min_length=1,max_length=500)
class EvidenceAdd(VersionAction):
    document_ids:list[str]=Field(min_length=1,max_length=25)
class FindingUpdate(VersionAction):
    resolution:Literal["resolved","waived"]
    reason:str=Field(min_length=1,max_length=500)
class AccessorialCreate(StrictMutationModel):
    version:int=Field(ge=1); type:AccessorialType; amount:Decimal=Field(ge=0,decimal_places=2,max_digits=12); currency:Currency="USD"; reason:str=Field(default="",max_length=500); evidence_document_ids:list[str]=Field(default_factory=list,max_length=20)
    @field_validator("amount")
    @classmethod
    def finite(cls,v):
        if not v.is_finite(): raise ValueError("Amount must be finite")
        return v
class AccessorialUpdate(StrictUpdateModel):
    version:int=Field(ge=1); amount:Decimal|None=Field(default=None,ge=0,decimal_places=2,max_digits=12); currency:Currency|None=None; reason:str|None=Field(default=None,max_length=500); evidence_document_ids:list[str]|None=Field(default=None,max_length=20)
    nullable_fields=frozenset()
    @field_validator("amount")
    @classmethod
    def finite(cls,v):
        if v is not None and not v.is_finite(): raise ValueError("Amount must be finite")
        return v
