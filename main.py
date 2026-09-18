"""
GridWise – FastAPI Backend Server

Exposes POST /optimize which accepts forecast data and operator notes,
parses the notes via OpenRouter, runs the PuLP LP solver, and returns
the optimal 24-hour schedule and financial breakdown.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

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
    """Input payload for the /optimize endpoint."""
    initial_energy: float = Field(
        ..., ge=0,
        description="Battery state-of-energy at start of day (kWh).",
    )
    battery_capacity: float = Field(
        ..., gt=0,
        description="Maximum battery capacity (kWh).",
    )
    max_c_rate: float = Field(
        ..., gt=0, le=1.0,
        description="Max charge/discharge rate as fraction of capacity per hour.",
    )
    demand_forecast: list[float] = Field(
        ..., min_length=24, max_length=24,
        description="Hourly campus demand forecast (kWh), 24 values.",
    )
    solar_forecast: list[float] = Field(
        ..., min_length=24, max_length=24,
        description="Hourly solar generation forecast (kWh), 24 values.",
    )
    tariffs: list[float] = Field(
        ..., min_length=24, max_length=24,
        description="Hourly grid tariff ($/kWh), 24 values.",
    )
    operator_notes: str | None = Field(
        None,
        description="Free-text operator notes / directives (optional).",
    )


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
        constraints = parse_operator_notes(req.operator_notes)
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
