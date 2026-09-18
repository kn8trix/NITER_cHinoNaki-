"""
Deterministic thresholds and configuration values for the
Day/Night & Next-Day Prediction Service.

Keeping these in one place makes the business rules easy to audit
and change without touching the logic in services/prediction.py.
"""

# --- Day/Night classification -------------------------------------------
# A timestamp is considered "daytime" only when BOTH the clock time is
# within the daytime window AND the solar voltage reading is at/above
# the minimum daytime threshold.
DAY_START_HOUR: int = 6          # inclusive, 06:00
DAY_END_HOUR: int = 18           # exclusive, 18:00
MIN_DAYTIME_SOLAR_VOLTAGE: float = 12.0  # volts

# --- Next-day load prediction --------------------------------------------
BASE_DEMAND_WITH_CLASSES_KWH: float = 350.0
BASE_DEMAND_WITHOUT_CLASSES_KWH: float = 100.0
HOT_TEMP_THRESHOLD_C: float = 30.0
HOT_TEMP_MULTIPLIER: float = 1.25

# --- Nighttime battery baseline ------------------------------------------
# Default minimum battery State-of-Charge (kWh) the campus wants to hold
# overnight. Can be overridden per-request via
# DispatchPredictionRequest.nighttime_baseline_kwh.
DEFAULT_NIGHTTIME_BASELINE_KWH: float = 120.0
