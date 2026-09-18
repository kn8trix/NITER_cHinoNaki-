# ⚡ GridWise Energy Optimization Backend

> **A smarter energy plan for Bangladesh University of Professionals (BUP).**

GridWise combines solar generation, campus demand, battery state, tariffs, and plain-language operator instructions into an optimal 24-hour dispatch plan for BUP.

[![API](https://img.shields.io/badge/API-FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://niter-chino-naki-67fatbwdq-k8-s-projects.vercel.app/)
[![Solver](https://img.shields.io/badge/Solver-PuLP%20%2B%20CBC-2563eb?style=for-the-badge)](https://github.com/coin-or/pulp)
[![Deployment](https://img.shields.io/badge/Deployment-Vercel-111827?style=for-the-badge&logo=vercel&logoColor=white)](https://niter-chino-naki-67fatbwdq-k8-s-projects.vercel.app/)

## 🌐 Live Demo

- **API base URL:** [niter-chino-naki-8l3nfxdka-k8-s-projects.vercel.app](https://niter-chino-naki-8l3nfxdka-k8-s-projects.vercel.app/)
- **Interactive API docs:** [Swagger UI](https://niter-chino-naki-8l3nfxdka-k8-s-projects.vercel.app/docs)
- **Optimization endpoint:** `POST /optimize`
- **Health check:** `GET /health`

## 🧪 API Evaluation

Evaluators can test GridWise directly through the [interactive Swagger docs](https://niter-chino-naki-8l3nfxdka-k8-s-projects.vercel.app/docs) or by sending a `POST` request to:

```text
https://niter-chino-naki-8l3nfxdka-k8-s-projects.vercel.app/optimize
```

Use a standard GridWise JSON payload containing:

- 24-hour `demand_forecast`
- 24-hour `solar_forecast`
- 24-hour `tariffs`
- Battery parameters such as `initial_energy`, `battery_capacity`, and `max_c_rate`
- Optional `operator_notes`

The backend returns the complete 24-hour optimal schedule, total cost, and parsed constraints in the required JSON schema.

## 🏫 Why BUP?

BUP's academic buildings, laboratories, residential areas, and shared services create changing demand throughout the day. Solar availability and grid tariffs also change by hour.

GridWise gives BUP operators a clear plan for:

- **During low-price hours:** the battery can charge when useful and permitted.
- **During sunny hours:** solar is used directly for campus demand before excess energy is curtailed or stored.
- **During expensive peak hours:** stored energy can reduce costly grid imports.
- **During reserve-sensitive periods:** minimum battery energy can be protected for resilience.
- **At the end of the day:** the optimizer enforces battery neutrality so the plan is operationally consistent with the initial state.

### 🎯 Example BUP scenario

When evening classes and campus services raise demand after solar production falls, GridWise preserves energy earlier, uses solar directly, and discharges the battery during expensive evening tariffs. BUP receives a transparent schedule showing the grid, solar, and battery contribution for every hour.

## 🌞🌙 Dispatch Flow

The flow below shows the complete BUP dispatch decision path. It separates daytime solar and directive handling from nighttime battery optimization, then returns to the shared 24-hour loop.

![GridWise BUP energy optimization flowchart](docs/gridwise-flowchart.svg)

<details>
<summary>View editable Mermaid source</summary>

```mermaid
flowchart TD
		A[Start system dispatch / LP optimizer run] --> B{Is it daytime or nighttime?}

		subgraph DAY[Daytime cycle and directive application]
			C[Parse operator notes and apply directives] --> D[Check solar generation forecast]
			D --> E[Check BUP campus demand and tariff rates]
			E --> F{Solar voltage and energy enough for cost trade-off?}
			F -->|Yes| G[Power BUP campus via solar]
			F -->|No| H[Use battery dispatch]
			H --> I{Battery reserve and state of charge above minimum threshold?}
			I -->|No| J[Use grid, respecting max_grid_window]
			I -->|Yes| K[Power BUP campus via battery]
			J --> L[Power BUP campus via grid and solar]
		end

		subgraph NIGHT[Nighttime cycle and optimization]
			M[Evaluate nighttime phase] --> N[Check battery voltage and state of charge]
			N --> O{Sufficient energy and end-of-day neutrality feasible?}
			O -->|No| P[Use grid, accounting for dynamic tariffs]
			O -->|Yes| Q[Discharge battery or hold reserve]
			Q --> R[Evaluate forward plan: charge at cheaper future hour]
			P --> R
			R --> S[Enforce end-of-day neutrality: battery_energy[23] = initial_energy]
		end

		B -->|Daytime| C
		B -->|Nighttime| M
		G --> T[Finish current hour and continue 24-hour loop]
		K --> T
		L --> T
		S --> T
		T --> B

		classDef start fill:#1e88e5,color:#fff,stroke:#0d47a1,stroke-width:2px;
		classDef day fill:#fff3cd,color:#5f4300,stroke:#f0ad00,stroke-width:2px;
		classDef night fill:#dbeafe,color:#12345b,stroke:#2563eb,stroke-width:2px;
		classDef decision fill:#fff,color:#222,stroke:#555,stroke-width:2px;
		classDef grid fill:#ffd6d6,color:#5f1010,stroke:#e53935,stroke-width:2px;
		classDef solar fill:#d9f7df,color:#124d1d,stroke:#43a047,stroke-width:2px;
		classDef finish fill:#c8e6c9,color:#164a19,stroke:#2e7d32,stroke-width:2px;

		class A start;
		class C,D,E,F,G,H,I,K day;
		class M,N,O,P,Q,R,S night;
		class B,F,I,O decision;
		class J,L,P grid;
		class G,K solar;
		class A,T finish;
```

</details>

### How the optimizer works through the flow

1. **Start with BUP's 24-hour inputs.** The API receives demand, solar, tariffs, battery state, and optional operator notes for hours `0` through `23`.
2. **Choose the operating phase.** The loop evaluates the current hour as daytime or nighttime. Both branches use the same forecasts and battery limits.
3. **Apply human instructions.** Operator notes are parsed into constraints such as no-charge windows, no-discharge windows, grid caps, and minimum battery reserve.
4. **Prioritize daytime solar.** The optimizer checks whether forecast solar can serve BUP demand. Solar is used directly first; extra solar can charge the battery when capacity and charge-rate limits allow. Any remainder is curtailed.
5. **Protect the battery reserve.** If solar is insufficient, the optimizer checks the battery state of charge and minimum reserve before discharging. If the reserve cannot be used, grid energy supplies BUP instead.
6. **Optimize nighttime energy.** When solar is unavailable, the model compares battery energy, future demand, tariffs, and end-of-day feasibility. It discharges during expensive hours when that is beneficial and holds reserve when required.
7. **Plan charging economically.** Charging is allowed only when the battery has room, the charge rate allows it, and the result supports the forward 24-hour plan. This prevents the battery from being emptied or overfilled at the wrong time.
8. **Enforce the final battery state.** The LP constraint `battery_energy[23] = initial_energy` ensures the schedule ends with the same battery energy with which BUP started.
9. **Return the next hourly decision.** The loop continues until all 24 hours are evaluated, then returns the full schedule, cost, energy totals, and applied constraints as JSON.

## ✨ Features

- 💰 **Economic dispatch:** minimizes 24-hour grid-import cost.
- ☀️ **Solar-first balancing:** uses available solar for campus demand.
- 🔋 **Battery optimization:** respects capacity, rate, state, and reserve limits.
- 📈 **Tariff awareness:** prioritizes battery use during expensive hours.
- 🗣️ **Natural-language directives:** understands notes such as `no charging during peak hour 18`.
- 📦 **Stable JSON:** returns `status`, `total_cost_usd`, `schedule`, and `summary`.
- 🔁 **Flexible input:** accepts native flat payloads and supported nested case packs.

## 🚀 API Usage

Send a `POST` request to `/optimize` with six required optimization inputs and optional operator notes. Every forecast array contains 24 hourly values.

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

`operator_notes` accepts either a string or a list of strings.

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

The real response contains 24 schedule objects, one for each hour from `0` through `23`.

## 🛠️ Run Locally

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

## ✅ Verification

Eight BUP-style scenarios were tested: balanced demand, high demand, solar surplus, low battery capacity, flat tariffs, charging restrictions, zero solar, and low C-rate limits. All eight returned HTTP `200`, `status: "Optimal"`, and 24 hourly schedule records.

## 🧰 Technology Stack

- Python 3
- FastAPI
- Pydantic
- PuLP / CBC linear-program solver
- OpenRouter-compatible operator-note parsing
- Vercel Serverless Functions
