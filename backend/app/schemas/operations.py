from typing import Optional

from pydantic import Field, field_validator, model_validator

from .common import StrictMutationModel


class RouteCalculationRequest(StrictMutationModel):
    pickup: str = Field(min_length=1, max_length=500)
    delivery: str = Field(min_length=1, max_length=500)


class WeatherCheckRequest(StrictMutationModel):
    pickup: str = Field(min_length=1, max_length=200)
    delivery: str = Field(min_length=1, max_length=200)


class LoadIdRequest(StrictMutationModel):
    load_id: str = Field(min_length=1, max_length=100)


class SamsaraVehicleRequest(StrictMutationModel):
    truck_id: Optional[str] = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    vehicle_id: Optional[str] = Field(default=None, min_length=1, max_length=100)

    @field_validator("truck_id")
    @classmethod
    def reject_synthetic_vehicle_id(cls, value):
        if value is not None and value.upper().startswith("VEH"):
            raise ValueError("Synthetic vehicle identifiers are not accepted")
        return value

    @model_validator(mode="after")
    def exactly_one_identifier(self):
        if (self.truck_id is None) == (self.vehicle_id is None):
            raise ValueError("Provide exactly one truck identifier")
        return self
