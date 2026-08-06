from pydantic import Field

from .common import StrictMutationModel, StringEnum


class AlertType(StringEnum):
    WEATHER = "weather"
    ROAD = "road"
    FUEL = "fuel"
    ETA = "eta"
    SAFETY = "safety"


class DriverAlertRequest(StrictMutationModel):
    load_id: str = Field(min_length=1, max_length=100)
    alert_type: AlertType
    message: str = Field(default="", max_length=2000)
