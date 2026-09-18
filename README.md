# GridWise Energy Optimization Backend

> A decision-support backend for Bangladesh University of Professionals (BUP) that plans economical, reliable 24-hour campus energy dispatch.

GridWise is a FastAPI service that combines solar generation, campus demand, battery state, electricity tariffs, and natural-language operator instructions into an optimal hourly dispatch plan. The project is designed around BUP as the primary campus and test subject: it helps campus operators decide when to use solar, charge or discharge storage, and import electricity from the grid.

## Live Demo

- **Live API:** [niter-chino-naki-67fatbwdq-k8-s-projects.vercel.app](https://niter-chino-naki-67fatbwdq-k8-s-projects.vercel.app/)
- **Optimization endpoint:** `POST /optimize`
- **Health check:** `GET /health`

## Why BUP?

BUP is a strong use case for a campus-scale energy optimizer because its academic buildings, administrative facilities, laboratories, residential areas, and shared services have changing demand throughout the day. Solar output is also time-dependent, while grid prices can make some hours significantly more expensive than others.

GridWise gives BUP a repeatable operating plan instead of relying on manual decisions:

- **During low-price hours:** the battery can charge when useful and permitted.
- **During sunny hours:** solar is used directly for campus demand before excess energy is curtailed or stored.
- **During expensive peak hours:** stored energy can reduce costly grid imports.
- **During reserve-sensitive periods:** minimum battery energy can be protected for resilience.
- **At the end of the day:** the optimizer enforces battery neutrality so the plan is operationally consistent with the initial state.

### Example BUP scenario

Suppose BUP expects high demand around evening class, laboratory, and campus-service hours while solar production falls to zero. GridWise can preserve energy during the day, use available solar directly, charge within the battery's power limit, and discharge during expensive evening tariffs. The result is a 24-hour schedule that shows exactly how much energy comes from the grid, solar, and battery each hour.

## Dispatch Flow

The following flow captures the operating logic used by the project. The daytime and nighttime branches converge into one continuous 24-hour optimization loop.

```mermaid
flowchart TD
		A[Start system dispatch / LP optimizer run] --> B{Daytime or nighttime?}

		B -->|Daytime| C([Daytime cycle and directive application])
		B -->|Nighttime| D([Nighttime cycle and optimization])

		C --> E[Parse operator notes and apply directives]
		E --> F[Check solar generation forecast]
		F --> G[Check BUP campus demand and tariff rates]
		G --> H{Solar voltage and energy enough for cost trade-off?}
		H -->|Yes| I[Power BUP campus via solar]
		H -->|No| J[Use battery dispatch]

		D --> K[Evaluate nighttime phase]
		K --> L[Check battery voltage and state of charge]
		L --> M{Sufficient energy and end-of-day neutrality feasible?}
		M -->|Yes| N[Discharge battery or hold reserve]
		M -->|No| O[Use grid, accounting for dynamic tariffs]
		N --> P[Evaluate forward plan and charge at cheaper future hour]
		O --> P
		P --> Q[Enforce end-of-day neutrality: battery_energy[23] = initial_energy]

		J --> R{Battery reserve and state of charge above minimum?}
		R -->|Yes| S[Use grid with reserve protection]
		R -->|No| T[Power BUP campus via grid and solar]

		I --> U[Finish and continue 24-hour loop]
		S --> U
		T --> U
		Q --> U

		classDef start fill:#1e88e5,color:#fff,stroke:#0d47a1,stroke-width:2px;
		classDef day fill:#fff3cd,color:#5f4300,stroke:#f0ad00,stroke-width:2px;
		classDef night fill:#dbeafe,color:#12345b,stroke:#2563eb,stroke-width:2px;
		classDef decision fill:#fff,color:#222,stroke:#555,stroke-width:2px;
		classDef grid fill:#ffd6d6,color:#5f1010,stroke:#e53935,stroke-width:2px;
		classDef solar fill:#d9f7df,color:#124d1d,stroke:#43a047,stroke-width:2px;
		classDef finish fill:#c8e6c9,color:#164a19,stroke:#2e7d32,stroke-width:2px;

		class A start;
		class C,E,F,G day;
		class D,K,L,N,P,Q night;
		class B,H,M,R decision;
		class O,S grid;
		class I,T solar;
		class J,U finish;
```

## Features

- **Economic dispatch:** minimizes total grid-import cost across a 24-hour horizon.
- **Solar-first balancing:** uses available solar directly for campus demand.
- **Battery optimization:** respects initial energy, capacity, charge rate, discharge rate, and reserve limits.
- **Tariff awareness:** shifts battery use toward expensive grid hours when constraints allow.
- **Natural-language directives:** parses operator notes such as `no charging during peak hour 18` and `keep minimum battery reserve 25 kwh`.
- **Deterministic JSON:** returns a stable top-level response with `status`, `total_cost_usd`, `schedule`, and `summary`.
- **Nested case compatibility:** accepts both the native flat schema and supported nested GridWise case-pack payloads.

## API Usage

Send a `POST` request to `/optimize` with six required optimization inputs and optional operator notes.

### Request body

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
		"keep minimum battery reserve 25 kwh"
	]
}
```

Every forecast array contains exactly 24 hourly values. `operator_notes` accepts either a string or a list of strings.

### Example request with cURL

```bash
curl -X POST \
	https://niter-chino-naki-67fatbwdq-k8-s-projects.vercel.app/optimize \
	-H "Content-Type: application/json" \
	-d @payload.json
```

### Response contract

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
		}
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

The real response contains 24 schedule objects, one for each hour from `0` through `23`. The example shows the contract and one representative hourly record.

## Architecture

```text
Client / BUP operations dashboard
							|
							v
			 FastAPI POST /optimize
							|
			Pydantic request validation
							|
			Operator-note constraint parser
							|
				PuLP linear-program model
							|
				24-hour dispatch schedule
							|
					JSON response
```

### Core modules

- `main.py` - FastAPI application, request validation, schema normalization, and response handling.
- `parser.py` - converts operator notes into structured constraints.
- `optimizer.py` - builds and solves the 24-hour PuLP optimization model.
- `wsgi.py` - deployment entry point for the serverless environment.

## Mathematical Model

For each hour $h$, the optimizer balances energy with:

$$
grid_h + solarUsed_h + discharge_h = demand_h + charge_h
$$

Battery state evolves as:

$$
battery_h = battery_{h-1} + charge_h - discharge_h
$$

The objective is to minimize total grid cost:

$$
\min \sum_{h=0}^{23} grid_h \times tariff_h
$$

The model also enforces battery bounds, charge and discharge limits, operator directives, and end-of-day neutrality.

## Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

The local API runs at `http://127.0.0.1:8000`.

Check it with:

```bash
curl http://127.0.0.1:8000/health
```

## Verification

The deployed API was tested with eight BUP-style GridWise scenarios covering balanced demand, high demand peaks, solar surplus, low battery capacity, flat tariffs, charging restrictions, zero solar, and low C-rate limits. All eight returned HTTP `200`, `status: "Optimal"`, and 24 hourly schedule records.

## Technology Stack

- Python 3
- FastAPI
- Pydantic
- PuLP / CBC linear-program solver
- OpenRouter-compatible operator-note parsing
- Vercel Serverless Functions

## Team / Context

**NITER cHinoNaki - BUP Hackathon**

GridWise is presented as a practical campus-energy optimization prototype for BUP. Its goal is to help campus stakeholders make transparent, cost-aware dispatch decisions while preserving operational constraints and battery resilience.
