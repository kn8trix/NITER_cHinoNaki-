"""
FastAPI application for the Day/Night & Next-Day Prediction Service.

This file contains ONLY API routing. All business logic lives in
app/services/prediction.py.

Scope: this service handles exactly three responsibilities:
    1. Day/Night classification
    2. Next-day energy demand prediction
    3. Nighttime grid pre-charge decision

It is one component of the larger BUP CSE Fest 2026 GridWise system
and does not implement the full campus energy optimizer.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.models import DispatchPredictionRequest, DispatchPredictionResponse
from app.services.prediction import predict_dispatch

logger = logging.getLogger("prediction_service")

app = FastAPI(
    title="Day/Night & Next-Day Prediction Service",
    description=(
        "GridWise component responsible for day/night classification, "
        "next-day energy demand prediction, and nighttime grid "
        "pre-charge decisions."
    ),
    version="1.0.0",
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fail safely: never leak stack traces or internal details."""
    logger.exception("Unhandled error while processing %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please contact the service owner."},
    )


@app.get("/health")
def health() -> dict:
    """Simple liveness check used by teammates / infra."""
    return {"status": "ok"}


@app.post("/predict", response_model=DispatchPredictionResponse)
def predict(request: DispatchPredictionRequest) -> DispatchPredictionResponse:
    """Run the day/night, next-day load, and grid pre-charge prediction.

    Validation is handled automatically by DispatchPredictionRequest;
    FastAPI returns HTTP 422 for invalid payloads before this function
    is even called.
    """
    return predict_dispatch(request)
