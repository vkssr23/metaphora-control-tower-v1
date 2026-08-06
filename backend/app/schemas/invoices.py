from typing import Optional
from pydantic import Field, field_validator
from .common import StrictMutationModel, StrictUpdateModel, StringEnum, validate_date_or_empty

class InvoiceStatus(StringEnum):
    NOT_READY="Not Ready"; DOCS_PENDING="Docs Pending"; READY="Ready to Invoice"; CREATED="Invoice Created"; SHARED="Invoice Shared"; PAYMENT_PENDING="Payment Pending"; PAID="Paid"; DISPUTED="Disputed"

class InvoiceCreate(StrictMutationModel):
    load_id: str = Field(min_length=1, max_length=100); customer: str = Field(default="", max_length=200)
    amount: float = Field(default=0, ge=0, allow_inf_nan=False); status: InvoiceStatus = InvoiceStatus.NOT_READY
    due_date: str = Field(default="", max_length=64); paid_date: str = Field(default="", max_length=64); dispute: bool = False; notes: str = Field(default="", max_length=5000)
    @field_validator("due_date", "paid_date")
    @classmethod
    def dates(cls, value): return validate_date_or_empty(value)

class InvoiceUpdate(StrictUpdateModel):
    customer: Optional[str] = Field(default=None, max_length=200)
    amount: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False); status: Optional[InvoiceStatus] = None
    due_date: Optional[str] = Field(default=None, max_length=64); paid_date: Optional[str] = Field(default=None, max_length=64); dispute: Optional[bool] = None; notes: Optional[str] = Field(default=None, max_length=5000)
    @field_validator("due_date", "paid_date")
    @classmethod
    def dates(cls, value): return validate_date_or_empty(value) if value is not None else value
