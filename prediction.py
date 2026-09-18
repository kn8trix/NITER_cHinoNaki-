"""
Business logic for the Day/Night & Next-Day Prediction Service.

This module contains ALL decision logic. The FastAPI route in
app/main.py only validates the request (via Pydantic) and calls
predict_dispatch() defined here.

Scope reminder: this module predicts tomorrow's expected load and
decides whether nighttime grid pre-charge is needed. It does NOT
build a full 24-hour optimization schedule, does not apply grid
tariffs, and does not interpret operator notes - those belong to
other components of the GridWise system.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional

from app.constants import (
    BASE_DEMAND_WITH_CLASSES_KWH,
    BASE_DEMAND_WITHOUT_CLASSES_KWH,
    DAY_END_HOUR,
    DAY_START_HOUR,
    HOT_TEMP_MULTIPLIER,
    HOT_TEMP_THRESHOLD_C,
    MIN_DAYTIME_SOLAR_VOLTAGE,
)
from app.models import DispatchPredictionRequest, DispatchPredictionResponse


def classify_day_night(current_timestamp: datetime, solar_voltage: float) -> bool:
    """Return True if it is currently daytime.

    Rule (both conditions must hold):
        is_daytime = solar_voltage >= 12.0 AND 06:00 <= current_time < 18:00

    Time alone or voltage alone is never sufficient.
    """
    day_window_start = time(DAY_START_HOUR, 0)
    day_window_end = time(DAY_END_HOUR, 0)
    current_time = current_timestamp.time()

    within_time_window = day_window_start <= current_time < day_window_end
    within_voltage_threshold = solar_voltage >= MIN_DAYTIME_SOLAR_VOLTAGE

    return within_time_window and within_voltage_threshold


def predict_next_day_load(temp_forecast_c: float, operates_classes: bool) -> float:
    """Predict tomorrow's total expected campus load, in kWh.

    base_demand = 350.0 kWh if classes operate, else 100.0 kWh
    predicted_demand = base_demand * 1.25 if temp_forecast_c > 30.0
                        else base_demand
    """
    base_demand = (
        BASE_DEMAND_WITH_CLASSES_KWH if operates_classes else BASE_DEMAND_WITHOUT_CLASSES_KWH
    )

    if temp_forecast_c > HOT_TEMP_THRESHOLD_C:
        return base_demand * HOT_TEMP_MULTIPLIER

    return base_demand


def calculate_next_day_deficit(
    predicted_next_day_load_kwh: float,
    battery_soc_kwh: float,
    predicted_next_day_solar_kwh: Optional[float],
) -> Optional[float]:
    """Return tomorrow's predicted net energy deficit, or None if unknown.

    net_deficit = predicted_next_day_load_kwh - predicted_next_day_solar_kwh
                  - battery_soc_kwh

    If predicted_next_day_solar_kwh was not supplied, we deliberately do
    NOT invent a solar estimate. The caller falls back to the
    deterministic nighttime battery-baseline rule instead (see
    decide_grid_precharge).
    """
    if predicted_next_day_solar_kwh is None:
        return None

    return predicted_next_day_load_kwh - predicted_next_day_solar_kwh - battery_soc_kwh


def decide_grid_precharge(
    is_daytime: bool,
    battery_soc_kwh: float,
    nighttime_baseline_kwh: float,
    net_deficit: Optional[float],
) -> bool:
    """Decide whether nighttime grid pre-charge should occur.

    Grid pre-charge is only ever considered at night. At night it is
    triggered by either of:
        - battery_soc_kwh is below the nighttime baseline, OR
        - a predicted next-day energy deficit (net_deficit > 0), when
          predicted_next_day_solar_kwh was supplied.
    """
    if is_daytime:
        return False

    below_baseline = battery_soc_kwh < nighttime_baseline_kwh
    has_predicted_deficit = net_deficit is not None and net_deficit > 0

    return below_baseline or has_predicted_deficit


def calculate_target_charge(
    is_daytime: bool,
    charge_with_grid: bool,
    battery_soc_kwh: float,
    battery_capacity_kwh: float,
    nighttime_baseline_kwh: float,
) -> float:
    """Calculate how much energy (kWh) to draw from the grid overnight.

    Basic case (battery below nighttime baseline):
        target_charge_kwh = nighttime_baseline_kwh - battery_soc_kwh

    The result is always clamped so that:
        0 <= target_charge_kwh <= battery_capacity_kwh - battery_soc_kwh

    Assumption (documented per the spec's ambiguity-handling rule):
    when pre-charge is triggered purely by a predicted next-day deficit
    (battery already at/above the nighttime baseline), the same
    baseline-based formula is used and naturally clamps to 0.0 - the
    spec defines an explicit formula only for the low-battery case, and
    no additional charge-sizing rule was provided for the deficit-only
    case.
    """
    if is_daytime or not charge_with_grid:
        return 0.0

    raw_target = nighttime_baseline_kwh - battery_soc_kwh
    raw_target = max(0.0, raw_target)

    max_possible_charge = battery_capacity_kwh - battery_soc_kwh
    max_possible_charge = max(0.0, max_possible_charge)

    return min(raw_target, max_possible_charge)


def generate_reasoning(
    is_daytime: bool,
    current_timestamp: datetime,
    solar_voltage: float,
    predicted_next_day_load_kwh: float,
    battery_soc_kwh: float,
    nighttime_baseline_kwh: float,
    charge_with_grid: bool,
    net_deficit: Optional[float],
) -> str:
    """Generate a simple, deterministic (non-LLM) explanation string."""
    time_str = current_timestamp.strftime("%H:%M")

    if is_daytime:
        return (
            f"Daytime detected because the current time is {time_str} and solar "
            f"voltage is {solar_voltage:.1f} V. Tomorrow's predicted load is "
            f"{predicted_next_day_load_kwh:.1f} kWh. Grid pre-charge is disabled "
            f"during daytime."
        )

    if charge_with_grid:
        if battery_soc_kwh < nighttime_baseline_kwh:
            return (
                f"Nighttime detected. Battery SoC is {battery_soc_kwh:.1f} kWh, "
                f"below the {nighttime_baseline_kwh:.1f} kWh nighttime baseline. "
                f"Grid pre-charge is required."
            )
        return (
            f"Nighttime detected. Battery SoC is {battery_soc_kwh:.1f} kWh, at or "
            f"above the {nighttime_baseline_kwh:.1f} kWh nighttime baseline, but a "
            f"predicted next-day energy deficit of {net_deficit:.1f} kWh requires "
            f"grid pre-charge."
        )

    return (
        "Nighttime detected. Battery SoC is above the nighttime baseline and no "
        "next-day energy deficit requires grid pre-charge."
    )


def predict_dispatch(request: DispatchPredictionRequest) -> DispatchPredictionResponse:
    """Run the full prediction pipeline for one request.

    Request -> Day/Night Detection -> Predict Tomorrow's Load ->
    Check Nighttime Battery Condition -> Check Next-Day Deficit ->
    Decide Grid Pre-Charge -> Calculate Target Charge -> Response
    """
    is_daytime = classify_day_night(request.current_timestamp, request.solar_voltage)

    predicted_next_day_load_kwh = predict_next_day_load(
        request.temp_forecast_c, request.operates_classes
    )

    net_deficit = calculate_next_day_deficit(
        predicted_next_day_load_kwh,
        request.battery_soc_kwh,
        request.predicted_next_day_solar_kwh,
    )

    charge_with_grid = decide_grid_precharge(
        is_daytime,
        request.battery_soc_kwh,
        request.nighttime_baseline_kwh,
        net_deficit,
    )

    target_charge_kwh = calculate_target_charge(
        is_daytime,
        charge_with_grid,
        request.battery_soc_kwh,
        request.battery_capacity_kwh,
        request.nighttime_baseline_kwh,
    )

    reasoning = generate_reasoning(
        is_daytime,
        request.current_timestamp,
        request.solar_voltage,
        predicted_next_day_load_kwh,
        request.battery_soc_kwh,
        request.nighttime_baseline_kwh,
        charge_with_grid,
        net_deficit,
    )

    return DispatchPredictionResponse(
        is_daytime=is_daytime,
        predicted_next_day_load_kwh=predicted_next_day_load_kwh,
        charge_with_grid=charge_with_grid,
        target_charge_kwh=target_charge_kwh,
        reasoning=reasoning,
    )
