# GridWise – Project Handover Document

**Repository:** `https://github.com/kn8trix/NITER_cHinoNaki-.git`
**Branch:** `main`
**Date:** September 18, 2026

---

## 1. Project Overview

GridWise is a **24-hour campus microgrid battery energy optimization** system built for the GridWise hackathon. It uses linear programming (PuLP) to find the cheapest dispatch schedule for a battery + solar + grid system, respecting operator directives expressed in natural language.

### What it does

1. Accepts hourly forecasts (demand, solar, tariff) and free-text operator notes
2. Parses operator notes into structured constraints (via OpenRouter LLM or rule-based regex fallback)
3. Solves a 24-hour linear program to minimize total grid cost
4. Returns the optimal hourly schedule with full financial breakdown

---

## 2. File Structure

```
NITER_cHinoNaki-/
├── main.py              # FastAPI server – POST /optimize, GET /health
├── parser.py            # Operator notes → structured constraints (OpenRouter + regex fallback)
├── optimizer.py         # PuLP LP engine – 24-hour minimization
├── requirements.txt     # Python dependencies
├── wsgi.py              # WSGI entry point for PythonAnywhere deployment
├── DEPLOY.md            # PythonAnywhere deployment guide
├── HANDOVER.md          # This document
└── .gitignore           # Standard Python gitignore
```

---

## 3. Architecture & Data Flow

```
Client POST /optimize
        │
        ▼
┌───────────────────┐
│   main.py         │  FastAPI endpoint, Pydantic input validation
│   OptimizeRequest │  Accepts: str | list[str] | None for operator_notes
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│   parser.py       │  1. Try rule-based regex parser (no API key needed)
│                   │  2. If no match → try OpenRouter LLM
│                   │  3. If no API key → return NO_OP_CONSTRAINTS
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│   optimizer.py    │  PuLP LpMinimize over 24 hours
│                   │  Variables: grid, solar_used, charge, discharge, battery
│                   │  Constraints: energy balance, battery transitions,
│                   │               end-of-day neutrality, operator directives
└───────┬───────────┘
        │
        ▼
   OptimizeResponse  (schedule + summary + total_cost_usd)
```

---

## 4. API Contract

### `POST /optimize`

**Request body (JSON):**

```json
{
  "initial_energy": 50.0,          // Battery SoE at start of day (kWh)
  "battery_capacity": 100.0,       // Max battery capacity (kWh)
  "max_c_rate": 20.0,              // Max charge/discharge rate (kWh/hour, ABSOLUTE)
  "demand_forecast": [12, ...],    // 24 hourly values (kWh)
  "solar_forecast": [0, ...],      // 24 hourly values (kWh)
  "tariffs": [4, ...],             // 24 hourly values ($/kWh)
  "operator_notes": [              // OPTIONAL: string or list of strings
    "no charging during peak hour 18",
    "keep minimum battery reserve 25 kwh",
    "allow aggressive discharge during hour 19"
  ]
}
```

**Response body:**

```json
{
  "status": "Optimal",
  "total_cost_usd": 3098.0,
  "schedule": [
    {
      "hour": 0,
      "grid_kwh": 1.0,
      "solar_used_kwh": 0.0,
      "solar_curtailed_kwh": 0.0,
      "charge_kwh": 0.0,
      "discharge_kwh": 11.0,
      "battery_energy_kwh": 39.0,
      "hourly_cost_usd": 4.0,
      "tariff_usd_per_kwh": 4.0,
      "demand_kwh": 12.0
    },
    ... (24 entries total)
  ],
  "summary": {
    "status": "Optimal",
    "total_cost_usd": 3098.0,
    "total_grid_import_kwh": 341.0,
    "total_solar_used_kwh": 490.0,
    "total_solar_curtailed_kwh": 223.0,
    "total_charge_kwh": 148.0,
    "total_discharge_kwh": 148.0,
    "battery_energy_start_kwh": 50.0,
    "battery_energy_end_kwh": 50.0,
    "min_battery_energy_kwh": 25.0,
    "max_battery_energy_kwh": 100.0,
    "applied_constraints": {
      "no_charge_windows": [[18, 19]],
      "no_discharge_windows": [],
      "max_grid_windows": [],
      "minimum_battery_reserve": 25.0
    }
  }
}
```

---

## 5. Key Design Decisions (Important for Next Developer)

### 5.1 `max_c_rate` is ABSOLUTE, not a fraction

The `max_c_rate` field represents **kWh/hour**, not a fraction of capacity.

| Input | Meaning |
|-------|---------|
| `max_c_rate: 20.0` | Battery can charge/discharge at most 20 kWh in any hour |
| `max_c_rate: 100.0` with `battery_capacity: 100.0` | Effectively 1C rate |

In `optimizer.py`, this is clamped: `max_charge = min(max_c_rate, battery_capacity)`.

### 5.2 `minimum_battery_reserve` dual interpretation

The `minimum_battery_reserve` field in `ParsedConstraints` supports two formats:

| Value | Interpretation |
|-------|---------------|
| `0.25` (≤ 1.0) | **Fraction** of capacity → `0.25 × 100 kWh = 25 kWh` |
| `25.0` (> 1.0) | **Absolute kWh** → used directly as `25 kWh` |

In `optimizer.py`:
```python
if constraints.minimum_battery_reserve <= 1.0:
    min_reserve_kwh = constraints.minimum_battery_reserve * battery_capacity
else:
    min_reserve_kwh = constraints.minimum_battery_reserve
```

### 5.3 `operator_notes` accepts `str | list[str] | None`

The Pydantic model uses a `@field_validator` to join list items with spaces before passing to the parser. The test payload sends a list of strings — this works.

### 5.4 Parser fallback chain

```
operator_notes input
    │
    ├─→ Empty/None? → return NO_OP_CONSTRAINTS
    │
    ├─→ Rule-based regex parser (_rule_based_parse)
    │   └─→ Matches found? → return parsed constraints
    │
    ├─→ OPENROUTER_API_KEY set? → call OpenRouter LLM
    │   └─→ Success? → return parsed constraints
    │   └─→ Failure? → return NO_OP_CONSTRAINTS
    │
    └─→ No API key → return NO_OP_CONSTRAINTS
```

### 5.5 End-of-day neutrality constraint

The optimizer enforces `battery_energy[23] == initial_energy`. This means the battery must return to its starting state by end of day — no net energy gain/loss over the 24-hour period.

---

## 6. Tested Operator Note Patterns

The rule-based regex parser (`_rule_based_parse`) handles these patterns:

| Pattern | Example | Parsed As |
|---------|---------|-----------|
| `no charging during hour X` | `"no charging during peak hour 18"` | `no_charge_windows: [[18, 19]]` |
| `no charging from X to Y` | `"no charging from 12 to 14"` | `no_charge_windows: [[12, 14]]` |
| `no discharging during hour X` | `"no discharging at hour 5"` | `no_discharge_windows: [[5, 6]]` |
| `keep minimum battery reserve X kwh` | `"keep minimum battery reserve 25 kwh"` | `minimum_battery_reserve: 25.0` |
| `minimum battery reserve X%` | `"minimum battery reserve 20%"` | `minimum_battery_reserve: 0.2` |
| `cap grid at X kwh at hour Y` | `"cap grid at 50 kwh at hour 18"` | `max_grid_windows: [{start:18, end:19, max_kwh:50}]` |

**Note:** The regex uses `charg\w+` and `discharg\w+` to match "charge", "charging", "discharge", "discharging" etc.

---

## 7. Verified Test Run

Using the hackathon test payload:

```json
{
  "initial_energy": 50.0,
  "battery_capacity": 100.0,
  "max_c_rate": 20.0,
  "demand_forecast": [12, 14, 18, 22, 28, 35, 42, 48, 52, 50, 45, 40, 38, 35, 32, 30, 35, 45, 55, 50, 40, 30, 20, 15],
  "solar_forecast": [0, 0, 0, 0, 0, 8, 20, 40, 65, 85, 95, 100, 95, 80, 60, 40, 20, 5, 0, 0, 0, 0, 0, 0],
  "tariffs": [4, 4, 3, 3, 3, 5, 8, 12, 16, 16, 12, 10, 8, 8, 10, 12, 16, 20, 22, 18, 12, 8, 5, 4],
  "operator_notes": [
    "no charging during peak hour 18",
    "keep minimum battery reserve 25 kwh",
    "allow aggressive discharge during hour 19"
  ]
}
```

**Results:**

| Metric | Value |
|--------|-------|
| Status | `Optimal` |
| Total cost | `$3,098.00` |
| Grid import | `341.0 kWh` |
| Solar used | `490.0 kWh` |
| Solar curtailed | `223.0 kWh` |
| Battery charge/discharge | `148.0 / 148.0 kWh` |
| Battery range | `25.0 – 100.0 kWh` |
| Start / End SoE | `50.0 → 50.0 kWh` ✅ |
| Hour 18 charge | `0.0 kWh` ✅ (no-charge constraint) |
| Min battery | `25.0 kWh` ✅ (reserve constraint) |

---

## 8. Bugs Found & Fixed During Development

| # | Issue | File | Fix |
|---|-------|------|-----|
| 1 | `max_c_rate` capped at `le=1.0` — rejected values like `20.0` | `main.py` | Removed `le=1.0` constraint, changed description to "absolute C-rate" |
| 2 | `operator_notes` only accepted `str \| None` — rejected `list[str]` | `main.py` | Changed to `Union[str, list[str], None]` with `@field_validator` to join lists |
| 3 | `optimizer.py` treated `max_c_rate` as fraction (`capacity × rate`) — produced absurd bounds | `optimizer.py` | Changed to `min(max_c_rate, battery_capacity)` (absolute interpretation) |
| 4 | Regex `no\s+charge` didn't match `"no charging"` | `parser.py` | Changed to `no\s+charg\w+` to match charge/charging/etc. |
| 5 | `minimum_battery_reserve` capped at `le=1.0` — rejected `25.0` kWh values | `parser.py` | Removed `le=1.0`, added dual interpretation logic in optimizer |
| 6 | No offline parsing — without API key, all operator notes were silently ignored | `parser.py` | Added `_rule_based_parse()` regex fallback that runs before OpenRouter call |

---

## 9. Dependencies

```
fastapi>=0.104.0
uvicorn>=0.24.0
pulp>=2.7.0
pydantic>=2.5.0
requests>=2.31.0
openai>=1.6.0
```

**Install:**
```bash
pip install -r requirements.txt
```

---

## 10. Running Locally

```bash
# Start the server
python main.py
# OR
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Test health
curl http://localhost:8000/health

# Test optimize
curl -X POST http://localhost:8000/optimize \
  -H "Content-Type: application/json" \
  -d '{ ... }'  # (see Section 6 test payload)
```

---

## 11. Deployment

See `DEPLOY.md` for full PythonAnywhere instructions. Quick summary:

1. Clone repo on PythonAnywhere
2. `python3.10 -m venv venv && source venv/bin/activate`
3. `pip install -r requirements.txt`
4. Set WSGI file to `/home/<you>/NITER_cHinoNaki-/wsgi.py`
5. Set `OPENROUTER_API_KEY` in Web tab environment variables
6. Click Reload

---

## 12. What's NOT Done / Known Limitations

| Item | Status | Notes |
|------|--------|-------|
| OpenRouter integration | ⚠️ Needs API key | Rule-based parser works offline; LLM parser needs `OPENROUTER_API_KEY` |
| CORS middleware | ❌ Not added | Needed if calling from a browser frontend — see `DEPLOY.md` troubleshooting |
| Unit tests | ❌ Not created | No pytest suite yet |
| `prediction_service` integration | ❌ Not done | A previous request to extract/integrate this folder was not completed |
| Vercel deployment | ❌ Not configured | Only PythonAnywhere WSGI is set up |
| Rate limiting | ❌ Not implemented | No throttling on the `/optimize` endpoint |
| Persistence / caching | ❌ Not implemented | Every request runs a fresh LP solve |
| Error logging to file | ❌ Not configured | Only stdout logging via `logging.basicConfig` |

---

## 13. Extending the Parser

To add new operator note patterns, add regex rules to `_rule_based_parse()` in `parser.py`. The function builds a `ParsedConstraints` object — add new fields to the model if needed.

To improve LLM parsing, update the `SYSTEM_PROMPT` in `parser.py` and test with your OpenRouter API key.

---

## 14. Quick Reference for Next Developer

```bash
# What files matter most?
main.py          → API entry point, request/response models
parser.py        → Constraint extraction (regex + LLM)
optimizer.py     → LP solver (PuLP)

# How to test without API key?
The rule-based parser handles common patterns. No key needed for basic constraints.

# What's the most common bug?
max_c_rate is ABSOLUTE (kWh/hour), not a fraction. If you see bounds like
2000.0 on charge variables, someone is multiplying by capacity again.

# How to add a new constraint type?
1. Add field to ParsedConstraints in parser.py
2. Add regex rule to _rule_based_parse() in parser.py
3. Add PuLP constraint to optimize() in optimizer.py
4. Update the OpenRouter SYSTEM_PROMPT
```
