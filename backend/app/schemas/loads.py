from typing import Optional

from pydantic import Field, field_validator

from .common import StrictMutationModel, StrictUpdateModel, StringEnum, validate_date_or_empty


class LoadStage(StringEnum):
    BOOKED="Booked"; ASSIGNED="Assigned"; DISPATCHED="Dispatched"; PICKUP_STARTED="Pickup Started"
    ARRIVED_PICKUP="Arrived Pickup"; LOADED="Loaded"; IN_TRANSIT="In Transit"
    ARRIVED_DELIVERY="Arrived Delivery"; DELIVERED="Delivered"; DOCS_PENDING="Docs Pending"
    INVOICE_PENDING="Invoice Pending"; PAYMENT_PENDING="Payment Pending"; CLOSED="Closed"; EXCEPTION="Exception"

class RiskLevel(StringEnum):
    LOW="Low"; MEDIUM="Medium"; HIGH="High"; CRITICAL="Critical"
class LoadCreate(StrictMutationModel):
    customer: str = Field(min_length=1, max_length=200)
    broker: str = Field(default="", max_length=200); rate_con_number: str = Field(default="", max_length=100)
    pickup_address: str = Field(min_length=1, max_length=500); pickup_city: str = Field(default="", max_length=100); pickup_state: str = Field(default="", max_length=50); pickup_zip: str = Field(default="", max_length=20); pickup_appt: str = Field(default="", max_length=64)
    equipment_type: str = Field(default="", max_length=100); commodity: str = Field(default="", max_length=200); weight: float = Field(default=0, ge=0, allow_inf_nan=False)
    delivery_address: str = Field(min_length=1, max_length=500); delivery_city: str = Field(default="", max_length=100); delivery_state: str = Field(default="", max_length=50); delivery_zip: str = Field(default="", max_length=20); delivery_appt: str = Field(default="", max_length=64)
    miles: float = Field(default=0, ge=0, allow_inf_nan=False); est_drive_hours: float = Field(default=0, ge=0, allow_inf_nan=False); rate: float = Field(default=0, ge=0, allow_inf_nan=False)
    truck_id: Optional[str] = Field(default=None, max_length=100); driver_id: Optional[str] = Field(default=None, max_length=100)
    risk: RiskLevel = RiskLevel.LOW; eta: str = Field(default="", max_length=64); notes: str = Field(default="", max_length=5000)
    fuel_cost: float = Field(default=0, ge=0, allow_inf_nan=False); tolls: float = Field(default=0, ge=0, allow_inf_nan=False); lumper: float = Field(default=0, ge=0, allow_inf_nan=False); driver_pay: float = Field(default=0, ge=0, allow_inf_nan=False); factoring_fee: float = Field(default=0, ge=0, allow_inf_nan=False); other_expenses: float = Field(default=0, ge=0, allow_inf_nan=False)

    @field_validator("pickup_appt", "delivery_appt", "eta")
    @classmethod
    def dates(cls, value): return validate_date_or_empty(value)


class LoadUpdate(StrictUpdateModel):
    nullable_fields = frozenset({"truck_id", "driver_id"})
    customer: Optional[str] = Field(default=None, min_length=1, max_length=200); broker: Optional[str] = Field(default=None, max_length=200); rate_con_number: Optional[str] = Field(default=None, max_length=100)
    pickup_address: Optional[str] = Field(default=None, min_length=1, max_length=500); pickup_city: Optional[str] = Field(default=None, max_length=100); pickup_state: Optional[str] = Field(default=None, max_length=50); pickup_zip: Optional[str] = Field(default=None, max_length=20); pickup_appt: Optional[str] = Field(default=None, max_length=64)
    equipment_type: Optional[str] = Field(default=None, max_length=100); commodity: Optional[str] = Field(default=None, max_length=200); weight: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    delivery_address: Optional[str] = Field(default=None, min_length=1, max_length=500); delivery_city: Optional[str] = Field(default=None, max_length=100); delivery_state: Optional[str] = Field(default=None, max_length=50); delivery_zip: Optional[str] = Field(default=None, max_length=20); delivery_appt: Optional[str] = Field(default=None, max_length=64)
    miles: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False); est_drive_hours: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False); rate: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    truck_id: Optional[str] = Field(default=None, max_length=100); driver_id: Optional[str] = Field(default=None, max_length=100)
    risk: Optional[RiskLevel] = None; eta: Optional[str] = Field(default=None, max_length=64); notes: Optional[str] = Field(default=None, max_length=5000)
    fuel_cost: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False); tolls: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False); lumper: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False); driver_pay: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False); factoring_fee: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False); other_expenses: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("pickup_appt", "delivery_appt", "eta")
    @classmethod
    def dates(cls, value): return validate_date_or_empty(value) if value is not None else value


class StageChange(StrictMutationModel):
    stage: LoadStage
    notes: str = Field(default="", max_length=2000)
