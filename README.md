# Day/Night & Next-Day Prediction Service

A backend component of the **BUP CSE Fest 2026 — Smart Campus Energy
Optimization Challenge / GridWise**.

## Scope

This service is **one team member's component**, not the full GridWise
system. It has exactly three responsibilities:

1. **Day/Night classification** — is it currently day or night, based on
   time *and* solar voltage.
2. **Next-day energy demand prediction** — a deterministic estimate of
   tomorrow's total campus load.
3. **Nighttime grid pre-charge decision** — whether the battery should be
   topped up from the grid overnight, and by how much.

### What this service does **NOT** do

- It does **not** build the full `/optimize-energy` endpoint.
- It does **not** produce a 24-hour `hourly_plan`.
- It does **not** do grid tariff optimization.
- It does **not** integrate an LLM or interpret operator notes.
- It does **not** produce `solar_reduction`, `minimum_battery_reserve`,
  `no_charge_window`, `no_discharge_window`, `max_grid_window`, or any
  other final battery-scheduling directives.

Those belong to the rest of the GridWise team. This service only returns
prediction and pre-charge information, which a teammate's component
consumes as one input among others.

## Project structure

```
prediction_service/
├── app/
│   ├── main.py              # FastAPI app, routes only
│   ├── models.py             # Pydantic request/response models + validation
│   ├── constants.py          # Thresholds and configuration
│   └── services/
│       └── prediction.py     # All business logic
├── tests/
│   └── test_prediction.py    # Unit + API tests (pytest)
├── requirements.txt
└── README.md
```

## API

### `GET /health`

Liveness check.

**Response — HTTP 200**
```json
{ "status": "ok" }
```

### `POST /predict`

Runs the full pipeline: day/night classification → next-day load
prediction → battery/deficit check → grid pre-charge decision → target
charge.

**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `current_timestamp` | datetime / ISO-8601 string | yes | |
| `solar_voltage` | float | yes | must be `>= 0` |
| `battery_soc_kwh` | float | yes | `0 <= soc <= battery_capacity_kwh` |
| `battery_capacity_kwh` | float | yes | must be `> 0` |
| `temp_forecast_c` | float | yes | tomorrow's forecast temperature |
| `operates_classes` | bool | yes | whether classes run tomorrow |
| `predicted_next_day_solar_kwh` | float or null | no | if supplied, enables deficit-based pre-charge; must be `>= 0` |
| `nighttime_baseline_kwh` | float | no | default `120.0`; must be `>= 0` |

`NaN` and `Infinity` are rejected on every numeric field. Invalid
payloads receive an HTTP `422` response with no internal details or
stack traces exposed.

**Example request**

```json
{
    "current_timestamp": "2026-09-18T22:00:00",
    "solar_voltage": 0.0,
    "battery_soc_kwh": 80.0,
    "battery_capacity_kwh": 500.0,
    "temp_forecast_c": 32.0,
    "operates_classes": true
}
```

**Example response — HTTP 200**

```json
{
    "is_daytime": false,
    "predicted_next_day_load_kwh": 437.5,
    "charge_with_grid": true,
    "target_charge_kwh": 40.0,
    "reasoning": "Nighttime detected. Battery SoC is 80.0 kWh, below the 120.0 kWh nighttime baseline. Grid pre-charge is required."
}
```

## Business rules

### Day/Night rule

```
is_daytime = solar_voltage >= 12.0 AND 06:00 <= current_time < 18:00
```

Both conditions must hold — never classify by time alone or voltage
alone.

### Next-day load prediction

```
base_demand = 350.0 kWh   if operates_classes else 100.0 kWh
predicted_demand = base_demand * 1.25   if temp_forecast_c > 30.0
                    else base_demand
```

This is a fixed formula, not a machine-learning model, and does not
factor in weather beyond `temp_forecast_c` or classroom occupancy.

### Nighttime grid pre-charge rule

Pre-charge is only ever considered at night (`is_daytime == False`).
It is triggered when **either**:

- `battery_soc_kwh < nighttime_baseline_kwh` (default baseline `120.0
  kWh`), **or**
- a predicted next-day deficit exists — only computed when
  `predicted_next_day_solar_kwh` is supplied:
  `net_deficit = predicted_next_day_load_kwh - predicted_next_day_solar_kwh
  - battery_soc_kwh`, triggered when `net_deficit > 0`.

If `predicted_next_day_solar_kwh` is not supplied, no solar generation
is invented — the deterministic nighttime baseline rule above is used
as the sole fallback.

**Target charge**, for the standard low-battery case:

```
target_charge_kwh = nighttime_baseline_kwh - battery_soc_kwh
```

clamped so that `0 <= target_charge_kwh <= battery_capacity_kwh -
battery_soc_kwh`. (Documented assumption: when pre-charge is triggered
purely by a predicted deficit while the battery is already at/above
baseline, the same baseline formula is used, which naturally clamps to
`0.0` — the spec defines an explicit charge-sizing formula only for the
low-battery case.)

## Running the service

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- API base URL: `http://127.0.0.1:8000`
- Interactive docs (Swagger): `http://127.0.0.1:8000/docs`
- Health check: `GET http://127.0.0.1:8000/health`
- Prediction: `POST http://127.0.0.1:8000/predict`

## Running tests

```bash
pytest
```

Tests cover: day/night boundary cases, all four load-prediction
combinations, low-battery and sufficient-battery nighttime paths,
daytime pre-charge suppression, battery-capacity clamping, validation
errors (negative SoC, SoC above capacity, invalid timestamp, NaN/Inf),
and both API endpoints.

## Integration for teammates

Any other GridWise component can call this service directly:

```
POST http://<this-service-host>:8000/predict
Content-Type: application/json

{
    "current_timestamp": "...",
    "solar_voltage": ...,
    "battery_soc_kwh": ...,
    "battery_capacity_kwh": ...,
    "temp_forecast_c": ...,
    "operates_classes": ...
}
```

and consume the response:

```json
{
    "is_daytime": ...,
    "predicted_next_day_load_kwh": ...,
    "charge_with_grid": ...,
    "target_charge_kwh": ...,
    "reasoning": ...
}
```

The API contract (the five response fields above) is stable and does
not depend on any other team member's code. This service has no
knowledge of, and no dependency on, the rest of the GridWise
optimizer.
