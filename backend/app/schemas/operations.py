from pydantic import Field

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
    vehicle_id: str = Field(min_length=1, max_length=100)
