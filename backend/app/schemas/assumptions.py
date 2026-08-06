from typing import Optional
from pydantic import Field
from .common import StrictUpdateModel

class AssumptionUpdate(StrictUpdateModel):
    fuel_price: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    mpg: Optional[float] = Field(default=None, gt=0, allow_inf_nan=False)
    driver_pay_solo_cpm: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    driver_pay_team_cpm: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    insurance_per_week: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    rental_per_week: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    factoring_fee_pct: Optional[float] = Field(default=None, ge=0, lt=100, allow_inf_nan=False)
    default_toll: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    target_margin_pct: Optional[float] = Field(default=None, ge=0, lt=100, allow_inf_nan=False)
    min_rpm: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    min_net_profit: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
