from typing import Optional

from pydantic import Field, field_validator

from .common import StrictMutationModel, StrictUpdateModel, StringEnum, finite, validate_date_or_empty


class TruckStatus(StringEnum):
    AVAILABLE = "Available"
    ASSIGNED = "Assigned"
    IN_TRANSIT = "In Transit"
    AT_PICKUP = "At Pickup"
    AT_DELIVERY = "At Delivery"
    IDLE = "Idle"
    MAINTENANCE = "Maintenance"
    OUT_OF_SERVICE = "Out of Service"


class MaintenanceStatus(StringEnum):
    GOOD = "Good"
    WARN = "Warn"
    BAD = "Bad"


class EldStatus(StringEnum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    FAULT = "Fault"


class TruckFields(StrictMutationModel):
    truck_number: str = Field(min_length=1, max_length=50)
    vin: str = Field(default="", max_length=50)
    plate: str = Field(default="", max_length=30)
    make: str = Field(default="", max_length=80)
    model: str = Field(default="", max_length=80)
    year: int = Field(default=2022, ge=1900, le=2100)
    status: TruckStatus = TruckStatus.AVAILABLE
    current_location: str = Field(default="", max_length=300)
    assigned_driver_id: Optional[str] = Field(default=None, max_length=100)
    samsara_id: str = Field(default="", max_length=100)
    eld_status: EldStatus = EldStatus.ACTIVE
    insurance_expiry: str = Field(default="", max_length=64)
    registration_expiry: str = Field(default="", max_length=64)
    annual_inspection_expiry: str = Field(default="", max_length=64)
    maintenance_status: MaintenanceStatus = MaintenanceStatus.GOOD
    weekly_revenue: float = Field(default=0, ge=0, allow_inf_nan=False)
    weekly_miles: float = Field(default=0, ge=0, allow_inf_nan=False)
    fuel_cost: float = Field(default=0, ge=0, allow_inf_nan=False)
    maintenance_cost: float = Field(default=0, ge=0, allow_inf_nan=False)
    idle_hours: float = Field(default=0, ge=0, allow_inf_nan=False)
    utilization: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)

    @field_validator("truck_number", mode="before")
    @classmethod
    def strip_number(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("vin", mode="before")
    @classmethod
    def normalize_vin(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("insurance_expiry", "registration_expiry", "annual_inspection_expiry")
    @classmethod
    def dates(cls, value):
        return validate_date_or_empty(value)


class TruckCreate(TruckFields):
    pass


class TruckUpdate(StrictUpdateModel):
    nullable_fields = frozenset({"assigned_driver_id"})
    truck_number: Optional[str] = Field(default=None, min_length=1, max_length=50)
    vin: Optional[str] = Field(default=None, max_length=50)
    plate: Optional[str] = Field(default=None, max_length=30)
    make: Optional[str] = Field(default=None, max_length=80)
    model: Optional[str] = Field(default=None, max_length=80)
    year: Optional[int] = Field(default=None, ge=1900, le=2100)
    status: Optional[TruckStatus] = None
    current_location: Optional[str] = Field(default=None, max_length=300)
    assigned_driver_id: Optional[str] = Field(default=None, max_length=100)
    samsara_id: Optional[str] = Field(default=None, max_length=100)
    eld_status: Optional[EldStatus] = None
    insurance_expiry: Optional[str] = Field(default=None, max_length=64)
    registration_expiry: Optional[str] = Field(default=None, max_length=64)
    annual_inspection_expiry: Optional[str] = Field(default=None, max_length=64)
    maintenance_status: Optional[MaintenanceStatus] = None
    weekly_revenue: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    weekly_miles: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    fuel_cost: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    maintenance_cost: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    idle_hours: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    utilization: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)

    _finite = field_validator("weekly_revenue", "weekly_miles", "fuel_cost", "maintenance_cost", "idle_hours", "utilization")(finite)

    @field_validator("vin", mode="before")
    @classmethod
    def normalize_vin(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("insurance_expiry", "registration_expiry", "annual_inspection_expiry")
    @classmethod
    def dates(cls, value):
        return validate_date_or_empty(value) if value is not None else value
