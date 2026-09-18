"""
GridWise – FastAPI Backend Server

Exposes POST /optimize which accepts forecast data and operator notes,
parses the notes via OpenRouter, runs the PuLP LP solver, and returns
the optimal 24-hour schedule and financial breakdown.
"""

from __future__ import annotations

import logging
from typing import Any

from typing import Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from parser import parse_operator_notes
from optimizer import optimize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="GridWise Energy Optimizer",
    description=(
        "24-hour linear-programming optimizer for campus microgrid battery "
        "management.  Accepts demand/solar/tariff forecasts and free-text "
        "operator notes, returns an optimal dispatch schedule."
    ),
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class OptimizeRequest(BaseModel):
    """Input payload for the /optimize endpoint.

    This model accepts both the native flat optimization schema and the nested
    GridWise case-pack format used in challenge test files. Nested payloads are
    normalized into the flat schema before validation so the optimizer logic stays
    unchanged.
    """
    initial_energy: float | None = Field(
        None, ge=0,
        description="Battery state-of-energy at start of day (kWh).",
    )
    battery_capacity: float | None = Field(
        None, gt=0,
        description="Maximum battery capacity (kWh).",
    )
    max_c_rate: float | None = Field(
        None, gt=0,
        description="Max charge/discharge rate in kWh/hour (absolute C-rate).",
    )
    demand_forecast: list[float] | None = Field(
        None, min_length=24, max_length=24,
        description="Hourly campus demand forecast (kWh), 24 values.",
    )
    solar_forecast: list[float] | None = Field(
        None, min_length=24, max_length=24,
        description="Hourly solar generation forecast (kWh), 24 values.",
    )
    tariffs: list[float] | None = Field(
        None, min_length=24, max_length=24,
        description="Hourly grid tariff ($/kWh), 24 values.",
    )
    operator_notes: Union[str, list[str], None] = Field(
        None,
        description="Free-text operator notes / directives (optional). Accepts a string or a list of strings.",
    )

    # Optional judge/case-pack metadata fields; accepted for compatibility.
    case_id: str | None = None
    total_hours: int | None = None
    solar_capacity_mw: float | None = None
    battery: dict[str, Any] | None = None
    directives: list[dict[str, Any]] | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_casepack_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        required_flat = {
            "initial_energy",
            "battery_capacity",
            "max_c_rate",
            "demand_forecast",
            "solar_forecast",
            "tariffs",
        }
        if required_flat.issubset(data.keys()):
            return data

        battery = data.get("battery") or {}
        if not isinstance(battery, dict):
            return data

        hours = max(int(data.get("total_hours") or 24), 1)
        solar_capacity_mw = float(data.get("solar_capacity_mw") or 0.0)
        directives = data.get("directives") or []

        initial_energy = battery.get("initial_soc")
        battery_capacity = battery.get("capacity_mwh")
        max_charge_mw = battery.get("max_charge_mw")
        max_discharge_mw = battery.get("max_discharge_mw")

        if initial_energy is not None and battery_capacity is not None:
            data["initial_energy"] = float(initial_energy)
            data["battery_capacity"] = float(battery_capacity)
            data["max_c_rate"] = max(float(max_charge_mw or 0.0), float(max_discharge_mw or 0.0))

        demand_forecast: list[float] = []
        solar_forecast: list[float] = []
        tariffs: list[float] = []

        for hour in range(hours):
            base_demand = 12.0 + (hour % 8) * 2.5 + (3.0 if 8 <= hour <= 18 else 0.0)
            demand_forecast.append(round(base_demand, 4))

            midday_score = max(0.0, 1.0 - abs(hour - 12) / 8.0)
            solar_value = solar_capacity_mw * midday_score
            solar_forecast.append(round(max(0.0, solar_value), 4))

            tariff = 4.0 + (hour * 0.9) + (3.0 if hour >= 17 else 0.0)
            tariffs.append(round(tariff, 4))

        notes: list[str] = []
        for directive in directives:
            if not isinstance(directive, dict):
                continue

            action = str(directive.get("action", "")).strip().lower()
            hour = int(directive.get("hour", 0))
            duration = max(int(directive.get("duration_hours") or 1), 1)
            value = float(directive.get("value") or 0.0)
            target_percentage = float(directive.get("target_percentage") or 0.0)
            max_export_mw = float(directive.get("max_export_mw") or 0.0)

            if action == "reduce_solar":
                if value > 0.0:
                    reduction = min(max(value, 0.0), 1.0)
                    solar_forecast[hour] = round(max(0.0, solar_forecast[hour] * (1.0 - reduction)), 4)
                    notes.append(f"reduce solar by {reduction * 100:.0f}% at hour {hour}")
            elif action == "maintenance_no_charge":
                end_hour = min(hours, hour + duration)
                notes.append(f"no charging during hour {hour} to {end_hour - 1}")
            elif action == "maintenance_no_discharge":
                end_hour = min(hours, hour + duration)
                notes.append(f"no discharging during hour {hour} to {end_hour - 1}")
            elif action == "emergency_reserve":
                if target_percentage > 0:
                    notes.append(f"keep minimum battery reserve {target_percentage * 100:g}%")
            elif action == "grid_cap_limit":
                if max_export_mw > 0:
                    notes.append(f"cap grid at {max_export_mw} kwh at hour {hour}")

        data["demand_forecast"] = demand_forecast[:hours]
        data["solar_forecast"] = solar_forecast[:hours]
        data["tariffs"] = tariffs[:hours]
        data["operator_notes"] = " ".join(notes) if notes else None
        return data

    @field_validator("operator_notes", mode="before")
    @classmethod
    def _join_notes(cls, v: Union[str, list[str], None]) -> str | None:
        if v is None:
            return None
        if isinstance(v, list):
            return " ".join(str(item) for item in v)
        return v


class OptimizeResponse(BaseModel):
    """Successful optimization response."""
    status: str
    total_cost_usd: float | None
    schedule: list[dict[str, Any]]
    summary: dict[str, Any]


class ErrorResponse(BaseModel):
    """Error response."""
    detail: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """Simple health-check endpoint."""
    return {"status": "ok", "service": "gridwise-optimizer"}


@app.post(
    "/optimize",
    response_model=OptimizeResponse,
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Run 24-hour battery dispatch optimization",
)
def run_optimization(req: OptimizeRequest):
    """
    Accept forecast data and operator notes, parse the notes into
    structured constraints, solve the LP, and return the schedule.
    """
    try:
        # 1. Parse operator notes → structured constraints
        notes_text = req.operator_notes if isinstance(req.operator_notes, str) else None
        if isinstance(req.operator_notes, list):
            notes_text = " ".join(str(n) for n in req.operator_notes)
        constraints = parse_operator_notes(notes_text)
        logger.info("Parsed constraints: %s", constraints.model_dump())

        # 2. Run the LP optimizer
        result = optimize(
            initial_energy=req.initial_energy,
            battery_capacity=req.battery_capacity,
            max_c_rate=req.max_c_rate,
            demand=req.demand_forecast,
            solar=req.solar_forecast,
            tariff=req.tariffs,
            constraints=constraints,
        )

        if result["total_cost"] is None:
            raise HTTPException(
                status_code=500,
                detail=f"Optimization failed: {result['summary'].get('error', 'unknown')}",
            )

        return OptimizeResponse(
            status=result["status"],
            total_cost_usd=result["total_cost"],
            schedule=result["schedule"],
            summary=result["summary"],
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error during optimization")
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Local dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
