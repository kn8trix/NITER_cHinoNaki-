"""
Pydantic request/response models for the Day/Night & Next-Day
Prediction Service.

Validation rules enforced here (see constants.py for thresholds):
    - battery_capacity_kwh > 0
    - battery_soc_kwh >= 0
    - battery_soc_kwh <= battery_capacity_kwh
    - solar_voltage >= 0
    - predicted_next_day_solar_kwh >= 0 (if provided)
    - nighttime_baseline_kwh >= 0
    - all numeric fields must be finite (NaN / +-inf are rejected)
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.constants import DEFAULT_NIGHTTIME_BASELINE_KWH


def _reject_non_finite(value: float, field_name: str) -> float:
    """Raise if a float is NaN or +-infinity; otherwise return it unchanged."""
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number (got {value!r})")
    return value


class DispatchPredictionRequest(BaseModel):
    """Input payload for POST /predict.

    current_timestamp may be supplied as a datetime or as an ISO-8601
    string; Pydantic parses strings into datetime automatically and
    raises a validation error for anything unparseable.
    """

    current_timestamp: datetime
    solar_voltage: float
    battery_soc_kwh: float
    battery_capacity_kwh: float
    temp_forecast_c: float
    operates_classes: bool

    # Optional fields - only present because they materially affect the
    # next-day prediction / pre-charge decision. Do not add fields that
    # the flowchart does not need.
    predicted_next_day_solar_kwh: Optional[float] = None
    nighttime_baseline_kwh: float = Field(default=DEFAULT_NIGHTTIME_BASELINE_KWH)

    # -- field-level validation -------------------------------------------------

    @field_validator("solar_voltage")
    @classmethod
    def _validate_solar_voltage(cls, v: float) -> float:
        v = _reject_non_finite(v, "solar_voltage")
        if v < 0:
            raise ValueError("solar_voltage must be >= 0")
        return v

    @field_validator("battery_soc_kwh")
    @classmethod
    def _validate_battery_soc(cls, v: float) -> float:
        v = _reject_non_finite(v, "battery_soc_kwh")
        if v < 0:
            raise ValueError("battery_soc_kwh must be >= 0")
        return v

    @field_validator("battery_capacity_kwh")
    @classmethod
    def _validate_battery_capacity(cls, v: float) -> float:
        v = _reject_non_finite(v, "battery_capacity_kwh")
        if v <= 0:
            raise ValueError("battery_capacity_kwh must be > 0")
        return v

    @field_validator("temp_forecast_c")
    @classmethod
    def _validate_temp(cls, v: float) -> float:
        return _reject_non_finite(v, "temp_forecast_c")

    @field_validator("predicted_next_day_solar_kwh")
    @classmethod
    def _validate_predicted_solar(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        v = _reject_non_finite(v, "predicted_next_day_solar_kwh")
        if v < 0:
            raise ValueError("predicted_next_day_solar_kwh must be >= 0 when provided")
        return v

    @field_validator("nighttime_baseline_kwh")
    @classmethod
    def _validate_baseline(cls, v: float) -> float:
        v = _reject_non_finite(v, "nighttime_baseline_kwh")
        if v < 0:
            raise ValueError("nighttime_baseline_kwh must be >= 0")
        return v

    # -- cross-field validation ---------------------------------------------

    @model_validator(mode="after")
    def _validate_soc_within_capacity(self) -> "DispatchPredictionRequest":
        if self.battery_soc_kwh > self.battery_capacity_kwh:
            raise ValueError(
                "battery_soc_kwh must be <= battery_capacity_kwh "
                f"(got soc={self.battery_soc_kwh}, capacity={self.battery_capacity_kwh})"
            )
        return self


class DispatchPredictionResponse(BaseModel):
    """Output payload for POST /predict."""

    is_daytime: bool
    predicted_next_day_load_kwh: float
    charge_with_grid: bool
    target_charge_kwh: float
    reasoning: str
