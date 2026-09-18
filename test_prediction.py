"""
Tests for the Day/Night & Next-Day Prediction Service.

Covers business-logic functions directly and the FastAPI endpoints
via TestClient.
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import DispatchPredictionRequest
from app.services.prediction import (
    classify_day_night,
    predict_dispatch,
    predict_next_day_load,
)

client = TestClient(app)


def make_request(**overrides) -> DispatchPredictionRequest:
    """Build a valid DispatchPredictionRequest, overriding fields as needed."""
    defaults = dict(
        current_timestamp=datetime(2026, 9, 18, 22, 0, 0),
        solar_voltage=0.0,
        battery_soc_kwh=80.0,
        battery_capacity_kwh=500.0,
        temp_forecast_c=32.0,
        operates_classes=True,
    )
    defaults.update(overrides)
    return DispatchPredictionRequest(**defaults)


# ---------------------------------------------------------------------------
# TEST 1 - DAYTIME
# ---------------------------------------------------------------------------
def test_daytime_full_pipeline():
    req = make_request(
        current_timestamp=datetime(2026, 9, 18, 12, 0, 0),
        solar_voltage=13.0,
        battery_soc_kwh=200.0,
        battery_capacity_kwh=500.0,
        temp_forecast_c=28.0,
        operates_classes=True,
    )
    result = predict_dispatch(req)

    assert result.is_daytime is True
    assert result.predicted_next_day_load_kwh == 350.0
    assert result.charge_with_grid is False
    assert result.target_charge_kwh == 0.0


# ---------------------------------------------------------------------------
# TEST 2 - NIGHTTIME + SUFFICIENT BATTERY
# ---------------------------------------------------------------------------
def test_nighttime_sufficient_battery():
    req = make_request(
        current_timestamp=datetime(2026, 9, 18, 22, 0, 0),
        solar_voltage=0.0,
        battery_soc_kwh=250.0,
        battery_capacity_kwh=500.0,
        temp_forecast_c=28.0,
        operates_classes=True,
    )
    result = predict_dispatch(req)

    assert result.is_daytime is False
    assert result.predicted_next_day_load_kwh == 350.0
    assert result.charge_with_grid is False
    assert result.target_charge_kwh == 0.0


# ---------------------------------------------------------------------------
# TEST 3 - NIGHTTIME + LOW BATTERY
# ---------------------------------------------------------------------------
def test_nighttime_low_battery():
    req = make_request(
        current_timestamp=datetime(2026, 9, 18, 22, 0, 0),
        solar_voltage=0.0,
        battery_soc_kwh=80.0,
        battery_capacity_kwh=500.0,
        temp_forecast_c=28.0,
        operates_classes=True,
    )
    result = predict_dispatch(req)

    assert result.is_daytime is False
    assert result.predicted_next_day_load_kwh == 350.0
    assert result.charge_with_grid is True
    assert result.target_charge_kwh == 40.0


# ---------------------------------------------------------------------------
# TEST 4-6 - NEXT-DAY LOAD FORMULA
# ---------------------------------------------------------------------------
def test_hot_active_day():
    assert predict_next_day_load(temp_forecast_c=35.0, operates_classes=True) == 437.5


def test_cool_non_class_day():
    assert predict_next_day_load(temp_forecast_c=25.0, operates_classes=False) == 100.0


def test_hot_non_class_day():
    assert predict_next_day_load(temp_forecast_c=35.0, operates_classes=False) == 125.0


# ---------------------------------------------------------------------------
# TEST 7-10 - DAY/NIGHT BOUNDARIES
# ---------------------------------------------------------------------------
def test_boundary_0600_is_daytime():
    assert classify_day_night(datetime(2026, 9, 18, 6, 0, 0), 12.0) is True


def test_boundary_1800_is_nighttime():
    assert classify_day_night(datetime(2026, 9, 18, 18, 0, 0), 12.0) is False


def test_0559_is_nighttime():
    assert classify_day_night(datetime(2026, 9, 18, 5, 59, 0), 13.0) is False


def test_low_solar_during_day_is_nighttime():
    assert classify_day_night(datetime(2026, 9, 18, 12, 0, 0), 11.9) is False


# ---------------------------------------------------------------------------
# TEST 11 - BATTERY CAPACITY CLAMP
# ---------------------------------------------------------------------------
def test_target_charge_never_exceeds_available_capacity():
    req = make_request(
        current_timestamp=datetime(2026, 9, 18, 22, 0, 0),
        solar_voltage=0.0,
        battery_soc_kwh=10.0,
        battery_capacity_kwh=25.0,  # capacity headroom (15 kWh) < baseline gap (110 kWh)
        temp_forecast_c=28.0,
        operates_classes=True,
        nighttime_baseline_kwh=120.0,
    )
    result = predict_dispatch(req)

    assert result.target_charge_kwh <= req.battery_capacity_kwh - req.battery_soc_kwh
    assert result.target_charge_kwh == 15.0


# ---------------------------------------------------------------------------
# TEST 12-14 - VALIDATION ERRORS
# ---------------------------------------------------------------------------
def test_invalid_negative_battery_soc_raises():
    with pytest.raises(ValidationError):
        make_request(battery_soc_kwh=-5.0)


def test_soc_above_capacity_raises():
    with pytest.raises(ValidationError):
        make_request(battery_soc_kwh=600.0, battery_capacity_kwh=500.0)


def test_invalid_timestamp_raises():
    with pytest.raises(ValidationError):
        make_request(current_timestamp="not-a-timestamp")


def test_negative_capacity_raises():
    with pytest.raises(ValidationError):
        make_request(battery_capacity_kwh=0.0)


def test_negative_solar_voltage_raises():
    with pytest.raises(ValidationError):
        make_request(solar_voltage=-1.0)


def test_nan_rejected():
    with pytest.raises(ValidationError):
        make_request(solar_voltage=float("nan"))


def test_infinity_rejected():
    with pytest.raises(ValidationError):
        make_request(battery_soc_kwh=float("inf"))


# ---------------------------------------------------------------------------
# TEST 15 - API HEALTH
# ---------------------------------------------------------------------------
def test_api_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# TEST 16 - API PREDICT
# ---------------------------------------------------------------------------
def test_api_predict_valid_request():
    payload = {
        "current_timestamp": "2026-09-18T22:00:00",
        "solar_voltage": 0.0,
        "battery_soc_kwh": 80.0,
        "battery_capacity_kwh": 500.0,
        "temp_forecast_c": 32.0,
        "operates_classes": True,
    }
    response = client.post("/predict", json=payload)
    assert response.status_code == 200

    body = response.json()
    for field in (
        "is_daytime",
        "predicted_next_day_load_kwh",
        "charge_with_grid",
        "target_charge_kwh",
        "reasoning",
    ):
        assert field in body

    assert body["is_daytime"] is False
    assert body["predicted_next_day_load_kwh"] == 437.5
    assert body["charge_with_grid"] is True
    assert body["target_charge_kwh"] == 40.0


def test_api_predict_invalid_request_returns_422():
    payload = {
        "current_timestamp": "2026-09-18T22:00:00",
        "solar_voltage": 0.0,
        "battery_soc_kwh": -10.0,  # invalid
        "battery_capacity_kwh": 500.0,
        "temp_forecast_c": 32.0,
        "operates_classes": True,
    }
    response = client.post("/predict", json=payload)
    assert response.status_code == 422
    # Ensure no internal details / stack trace leak
    assert "Traceback" not in response.text


# ---------------------------------------------------------------------------
# NEXT-DAY DEFICIT (optional field) BEHAVIOUR
# ---------------------------------------------------------------------------
def test_deficit_triggers_precharge_even_when_above_baseline():
    req = make_request(
        current_timestamp=datetime(2026, 9, 18, 22, 0, 0),
        solar_voltage=0.0,
        battery_soc_kwh=200.0,  # above default 120 kWh baseline
        battery_capacity_kwh=500.0,
        temp_forecast_c=32.0,
        operates_classes=True,
        predicted_next_day_solar_kwh=50.0,  # load 437.5 - 50 - 200 = 187.5 > 0
    )
    result = predict_dispatch(req)

    assert result.is_daytime is False
    assert result.charge_with_grid is True


def test_no_deficit_when_solar_and_battery_cover_load():
    req = make_request(
        current_timestamp=datetime(2026, 9, 18, 22, 0, 0),
        solar_voltage=0.0,
        battery_soc_kwh=200.0,
        battery_capacity_kwh=500.0,
        temp_forecast_c=32.0,
        operates_classes=True,
        predicted_next_day_solar_kwh=300.0,  # 437.5 - 300 - 200 < 0
    )
    result = predict_dispatch(req)

    assert result.charge_with_grid is False
    assert result.target_charge_kwh == 0.0
