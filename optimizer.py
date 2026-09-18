"""
GridWise – 24-Hour Linear Programming Optimizer (PuLP)

Decision variables per hour h ∈ {0 … 23}:
    grid_kwh[h]        – energy drawn from the grid
    solar_used_kwh[h]  – solar energy used directly (curtailed solar is free)
    charge[h]          – energy flowing INTO the battery
    discharge[h]       – energy flowing OUT of the battery
    battery_energy[h]  – state-of-energy at end of hour h

Objective: minimize Σ grid_kwh[h] × tariff[h]
"""

from __future__ import annotations

import logging
from typing import Any

import pulp

from parser import ParsedConstraints

logger = logging.getLogger(__name__)

HOURS = list(range(24))


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


# ---------------------------------------------------------------------------
# Main optimizer
# ---------------------------------------------------------------------------

def optimize(
    *,
    initial_energy: float,
    battery_capacity: float,
    max_c_rate: float,
    demand: list[float],
    solar: list[float],
    tariff: list[float],
    constraints: ParsedConstraints | None = None,
) -> dict[str, Any]:
    """
    Run the 24-hour LP optimization and return the optimal schedule.

    Parameters
    ----------
    initial_energy : float
        Battery state-of-energy at the start of the day (kWh).
    battery_capacity : float
        Maximum battery capacity (kWh).
    max_c_rate : float
        Maximum charge/discharge rate expressed as a *fraction* of capacity
        per hour (e.g., 0.5 = half the capacity in one hour).
    demand : list[float]
        Hourly campus demand forecast (kWh) for 24 hours.
    solar : list[float]
        Hourly solar generation forecast (kWh) for 24 hours.
    tariff : list[float]
        Hourly grid tariff ($/kWh) for 24 hours.
    constraints : ParsedConstraints or None
        Operator directives parsed from free-text notes.

    Returns
    -------
    dict
        ``{"status": ..., "total_cost": ..., "schedule": [...], "summary": ...}``
    """
    if constraints is None:
        constraints = ParsedConstraints()

    max_charge = battery_capacity * max_c_rate
    max_discharge = battery_capacity * max_c_rate

    # ---- Helpers to build hour-window sets ----
    def _hours_in_windows(windows: list[list[int]]) -> set[int]:
        hours: set[int] = set()
        for w in windows:
            if len(w) == 2:
                s, e = int(w[0]), int(w[1])
                hours.update(range(s, e))
        return hours

    no_charge_h = _hours_in_windows(constraints.no_charge_windows)
    no_discharge_h = _hours_in_windows(constraints.no_discharge_windows)

    # max_grid_windows: list of {"start", "end", "max_kwh"}
    max_grid_map: dict[int, float] = {}
    for w in constraints.max_grid_windows:
        s, e = int(w["start"]), int(w["end"])
        for h in range(s, e):
            max_grid_map[h] = min(max_grid_map.get(h, float("inf")), float(w["max_kwh"]))

    min_reserve_kwh = constraints.minimum_battery_reserve * battery_capacity

    # ==================================================================
    # Build LP
    # ==================================================================
    prob = pulp.LpProblem("GridWise_DayAhead", pulp.LpMinimize)

    # Decision variables
    grid = {h: pulp.LpVariable(f"grid_{h}", lowBound=0) for h in HOURS}
    solar_used = {h: pulp.LpVariable(f"solar_{h}", lowBound=0) for h in HOURS}
    charge = {h: pulp.LpVariable(f"charge_{h}", lowBound=0, upBound=max_charge) for h in HOURS}
    discharge = {h: pulp.LpVariable(f"discharge_{h}", lowBound=0, upBound=max_discharge) for h in HOURS}
    battery = {h: pulp.LpVariable(f"battery_{h}", lowBound=min_reserve_kwh, upBound=battery_capacity) for h in HOURS}

    # ---- Objective: minimize grid cost ----
    prob += pulp.lpSum(grid[h] * tariff[h] for h in HOURS), "TotalGridCost"

    # ---- Constraints ----

    # 1. Energy balance each hour
    #    grid + solar_used + discharge = demand + charge
    for h in HOURS:
        prob += (
            grid[h] + solar_used[h] + discharge[h] == demand[h] + charge[h],
            f"Balance_{h}",
        )

    # 2. Solar usage ≤ solar availability
    for h in HOURS:
        prob += solar_used[h] <= solar[h], f"SolarCap_{h}"

    # 3. Battery state-of-energy transitions
    #    battery[h] = battery[h-1] + charge[h] - discharge[h]
    prob += battery[0] == initial_energy + charge[0] - discharge[0], "BatteryInit"
    for h in range(1, 24):
        prob += (
            battery[h] == battery[h - 1] + charge[h] - discharge[h],
            f"BatteryTrans_{h}",
        )

    # 4. End-of-day neutrality: battery_energy[23] == initial_energy
    prob += battery[23] == initial_energy, "EndOfDayNeutrality"

    # 5. Operator directives: no-charge windows
    for h in no_charge_h:
        prob += charge[h] == 0, f"NoCharge_{h}"

    # 6. Operator directives: no-discharge windows
    for h in no_discharge_h:
        prob += discharge[h] == 0, f"NoDischarge_{h}"

    # 7. Operator directives: max grid import
    for h, max_kw in max_grid_map.items():
        prob += grid[h] <= max_kw, f"MaxGrid_{h}"

    # 8. Minimum battery reserve enforced via variable bounds (already set)

    # ==================================================================
    # Solve
    # ==================================================================
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=60)
    status_code = prob.solve(solver)

    status = pulp.LpStatus[status_code]
    logger.info("LP solver status: %s", status)

    if status not in ("Optimal", "Feasible"):
        return {
            "status": status,
            "total_cost": None,
            "schedule": [],
            "summary": {"error": f"Solver returned status: {status}"},
        }

    # ==================================================================
    # Extract results
    # ==================================================================
    schedule: list[dict[str, Any]] = []
    total_cost = 0.0
    total_solar_curtailed = 0.0

    for h in HOURS:
        g = pulp.value(grid[h])
        su = pulp.value(solar_used[h])
        c = pulp.value(charge[h])
        d = pulp.value(discharge[h])
        b = pulp.value(battery[h])
        cost_h = g * tariff[h]
        curtailed = solar[h] - su

        total_cost += cost_h
        total_solar_curtailed += curtailed

        schedule.append({
            "hour": h,
            "grid_kwh": round(g, 4),
            "solar_used_kwh": round(su, 4),
            "solar_curtailed_kwh": round(max(curtailed, 0), 4),
            "charge_kwh": round(c, 4),
            "discharge_kwh": round(d, 4),
            "battery_energy_kwh": round(b, 4),
            "hourly_cost_usd": round(cost_h, 4),
            "tariff_usd_per_kwh": tariff[h],
            "demand_kwh": demand[h],
        })

    summary = {
        "status": status,
        "total_cost_usd": round(total_cost, 4),
        "total_grid_import_kwh": round(sum(s["grid_kwh"] for s in schedule), 4),
        "total_solar_used_kwh": round(sum(s["solar_used_kwh"] for s in schedule), 4),
        "total_solar_curtailed_kwh": round(total_solar_curtailed, 4),
        "total_charge_kwh": round(sum(s["charge_kwh"] for s in schedule), 4),
        "total_discharge_kwh": round(sum(s["discharge_kwh"] for s in schedule), 4),
        "battery_energy_start_kwh": initial_energy,
        "battery_energy_end_kwh": round(pulp.value(battery[23]), 4),
        "min_battery_energy_kwh": round(min(s["battery_energy_kwh"] for s in schedule), 4),
        "max_battery_energy_kwh": round(max(s["battery_energy_kwh"] for s in schedule), 4),
        "applied_constraints": constraints.model_dump(),
    }

    return {
        "status": status,
        "total_cost": round(total_cost, 4),
        "schedule": schedule,
        "summary": summary,
    }
