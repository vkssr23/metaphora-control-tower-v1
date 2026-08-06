from typing import Literal, Optional

from pydantic import EmailStr, Field, field_validator

from .common import StrictMutationModel, StrictUpdateModel, StringEnum, validate_date_or_empty


class DriverStatus(StringEnum):
    AVAILABLE = "Available"
    ASSIGNED = "Assigned"
    DRIVING = "Driving"
    OFF_DUTY = "Off Duty"
    HOME_TIME = "Home Time"
    MISSING_UPDATE = "Missing Update"
    INACTIVE = "Inactive"


class PayType(StringEnum):
    CPM = "CPM"
    FLAT = "Flat"


class SoloTeam(StringEnum):
    SOLO = "Solo"
    TEAM = "Team"


class MvrStatus(StringEnum):
    CLEAR = "Clear"
    REVIEW = "Review"
    EXPIRED = "Expired"

class ClearinghouseStatus(StringEnum):
    CLEAR = "Clear"
    PENDING = "Pending"
    ISSUE = "Issue"

class EmploymentVerification(StringEnum):
    COMPLETE = "Complete"
    PENDING = "Pending"

# These values are safety-managed administrative statuses only. They do not
# represent evidence from an external CDL, MVR, or Clearinghouse verifier.


class DriverCreate(StrictMutationModel):
    name: str = Field(min_length=1, max_length=150)
    phone: str = Field(default="", max_length=50)
    email: EmailStr | Literal[""] = ""
    cdl_number: str = Field(default="", max_length=80)
    cdl_state: str = Field(default="", max_length=30)
    cdl_expiry: str = Field(default="", max_length=64)
    medical_expiry: str = Field(default="", max_length=64)
    clearinghouse_status: ClearinghouseStatus = ClearinghouseStatus.PENDING
    mvr_status: MvrStatus = MvrStatus.CLEAR
    employment_verification: EmploymentVerification = EmploymentVerification.PENDING
    pay_type: PayType = PayType.CPM
    cents_per_mile: float = Field(default=0.55, ge=0, allow_inf_nan=False)
    flat_weekly_pay: float = Field(default=0, ge=0, allow_inf_nan=False)
    solo_team: SoloTeam = SoloTeam.SOLO
    driver_type: SoloTeam = SoloTeam.SOLO
    assigned_truck_id: Optional[str] = Field(default=None, max_length=100)
    status: DriverStatus = DriverStatus.AVAILABLE
    current_location: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=5000)
    weekly_miles: float = Field(default=0, ge=0, allow_inf_nan=False)
    weekly_revenue: float = Field(default=0, ge=0, allow_inf_nan=False)
    on_time_pickup_pct: float = Field(default=95, ge=0, le=100, allow_inf_nan=False)
    on_time_delivery_pct: float = Field(default=93, ge=0, le=100, allow_inf_nan=False)
    missed_updates: int = Field(default=0, ge=0)
    late_deliveries: int = Field(default=0, ge=0)
    safety_issues: int = Field(default=0, ge=0)
    score: float = Field(default=85, ge=0, le=100, allow_inf_nan=False)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        if value == "": return ""
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("cdl_expiry", "medical_expiry")
    @classmethod
    def dates(cls, value): return validate_date_or_empty(value)


class DriverUpdate(StrictUpdateModel):
    nullable_fields = frozenset({"assigned_truck_id"})
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    phone: Optional[str] = Field(default=None, max_length=50)
    email: EmailStr | Literal[""] | None = None
    cdl_number: Optional[str] = Field(default=None, max_length=80)
    cdl_state: Optional[str] = Field(default=None, max_length=30)
    cdl_expiry: Optional[str] = Field(default=None, max_length=64)
    medical_expiry: Optional[str] = Field(default=None, max_length=64)
    clearinghouse_status: Optional[ClearinghouseStatus] = None
    mvr_status: Optional[MvrStatus] = None
    employment_verification: Optional[EmploymentVerification] = None
    pay_type: Optional[PayType] = None
    cents_per_mile: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    flat_weekly_pay: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    solo_team: Optional[SoloTeam] = None
    driver_type: Optional[SoloTeam] = None
    assigned_truck_id: Optional[str] = Field(default=None, max_length=100)
    status: Optional[DriverStatus] = None
    current_location: Optional[str] = Field(default=None, max_length=300)
    notes: Optional[str] = Field(default=None, max_length=5000)
    weekly_miles: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    weekly_revenue: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    on_time_pickup_pct: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    on_time_delivery_pct: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    missed_updates: Optional[int] = Field(default=None, ge=0)
    late_deliveries: Optional[int] = Field(default=None, ge=0)
    safety_issues: Optional[int] = Field(default=None, ge=0)
    score: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        if value == "": return ""
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("cdl_expiry", "medical_expiry")
    @classmethod
    def dates(cls, value): return validate_date_or_empty(value) if value is not None else value
