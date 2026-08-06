from typing import Optional

from pydantic import Field, field_validator

from .common import StrictMutationModel, StringEnum, validate_date_or_empty


class DriverType(StringEnum):
    SOLO = "Solo"
    TEAM = "Team"


class LoadAnalysisRequest(StrictMutationModel):
    offered_rate: float = Field(ge=0, allow_inf_nan=False)
    loaded_miles: float = Field(ge=0, allow_inf_nan=False)
    deadhead_miles: float = Field(default=0, ge=0, allow_inf_nan=False)
    fuel_price: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    mpg: Optional[float] = Field(default=None, gt=0, allow_inf_nan=False)
    driver_type: DriverType = DriverType.SOLO
    driver_pay_cpm: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    tolls: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    pickup_city: str = Field(default="", max_length=200)
    delivery_city: str = Field(default="", max_length=200)
    pickup_datetime: str = Field(default="", max_length=64)
    delivery_datetime: str = Field(default="", max_length=64)
    broker: str = Field(default="", max_length=200)
    commodity: str = Field(default="", max_length=200)
    weight: float = Field(default=0, ge=0, allow_inf_nan=False)

    @field_validator("pickup_datetime", "delivery_datetime")
    @classmethod
    def dates(cls, value):
        return validate_date_or_empty(value)
