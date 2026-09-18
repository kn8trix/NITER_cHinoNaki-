"""Standalone solar panel performance and efficiency calculations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from math import isfinite
from typing import Iterable, Optional


class EfficiencyStatus(str, Enum):
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    REDUCED = "REDUCED"
    LOW = "LOW"


@dataclass(frozen=True)
class SolarThresholds:
    """Operational thresholds that can be tuned without changing the calculator."""

    high_performance_pct: float = 110.0
    normal_min_performance_pct: float = 90.0
    reduced_min_performance_pct: float = 70.0
    sudden_output_drop_pct: float = 25.0
    high_panel_temperature_c: float = 45.0
    high_irradiance_w_m2: float = 700.0
    high_irradiance_low_performance_pct: float = 75.0


@dataclass(frozen=True)
class SolarConfiguration:
    """Model assumptions for a panel system at standard test conditions."""

    reference_panel_temperature_c: float = 25.0
    temperature_coefficient_per_c: float = 0.004
    system_efficiency: float = 1.0
    minimum_temperature_factor: float = 0.75
    maximum_temperature_factor: float = 1.08
    weather_factors: dict[str, float] = field(
        default_factory=lambda: {
            "sunny": 1.0,
            "clear": 1.0,
            "partly cloudy": 0.92,
            "cloudy": 0.78,
            "overcast": 0.68,
            "rain": 0.72,
            "rainy": 0.72,
            "heavy rain": 0.55,
            "storm": 0.45,
        }
    )


@dataclass(frozen=True)
class SolarReading:
    panel_capacity_kw: Optional[float]
    actual_output_kw: Optional[float]
    energy_generated_kwh: Optional[float] = None
    irradiance_w_m2: Optional[float] = None
    panel_temperature_c: Optional[float] = None
    ambient_temperature_c: Optional[float] = None
    weather: Optional[str] = None
    cloud_rain_condition: Optional[str] = None
    timestamp: Optional[str] = None


@dataclass(frozen=True)
class SolarAlert:
    title: str
    message: str
    possible_causes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SolarEfficiencyResult:
    panel_capacity_kw: Optional[float]
    current_solar_output_kw: Optional[float]
    energy_generated_kwh: Optional[float]
    solar_irradiance_w_m2: Optional[float]
    panel_temperature_c: Optional[float]
    ambient_temperature_c: Optional[float]
    weather: str
    expected_solar_output_kw: Optional[float]
    actual_solar_output_kw: Optional[float]
    solar_performance_pct: Optional[float]
    efficiency_status: EfficiencyStatus
    alerts: tuple[SolarAlert, ...] = ()
    data_warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """Return JSON-serializable output for a web backend."""
        result = asdict(self)
        result["efficiency_status"] = self.efficiency_status.value
        result["alerts"] = [asdict(alert) for alert in self.alerts]
        return result


def _number(value: Optional[float], minimum: Optional[float] = None) -> Optional[float]:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        return None
    if minimum is not None and value < minimum:
        return None
    return float(value)


def _temperature_factor(panel_temperature_c: Optional[float], config: SolarConfiguration) -> float:
    if panel_temperature_c is None:
        return 1.0
    factor = 1.0 - config.temperature_coefficient_per_c * (
        panel_temperature_c - config.reference_panel_temperature_c
    )
    return max(config.minimum_temperature_factor, min(config.maximum_temperature_factor, factor))


def _weather_factor(reading: SolarReading, config: SolarConfiguration) -> float:
    weather = reading.weather.strip().lower() if isinstance(reading.weather, str) else ""
    condition = (
        reading.cloud_rain_condition.strip().lower()
        if isinstance(reading.cloud_rain_condition, str)
        else ""
    )
    for label in (condition, weather):
        if label in config.weather_factors:
            return config.weather_factors[label]
    return 1.0


def _status(performance_pct: Optional[float], thresholds: SolarThresholds) -> EfficiencyStatus:
    if performance_pct is None:
        return EfficiencyStatus.LOW
    if performance_pct >= thresholds.high_performance_pct:
        return EfficiencyStatus.HIGH
    if performance_pct >= thresholds.normal_min_performance_pct:
        return EfficiencyStatus.NORMAL
    if performance_pct >= thresholds.reduced_min_performance_pct:
        return EfficiencyStatus.REDUCED
    return EfficiencyStatus.LOW


def _drop_pct(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or previous <= 0:
        return None
    return max(0.0, (previous - current) / previous * 100.0)


def calculate_solar_efficiency(
    reading: SolarReading,
    historical_readings: Iterable[SolarReading] = (),
    *,
    thresholds: SolarThresholds = SolarThresholds(),
    config: SolarConfiguration = SolarConfiguration(),
) -> SolarEfficiencyResult:
    """Calculate expected output, performance, status, trend inputs, and alerts.

    Irradiance is the main generation driver. Temperature adjusts panel conversion,
    while weather/cloud conditions model additional availability losses.
    """
    capacity = _number(reading.panel_capacity_kw, 0.0)
    actual = _number(reading.actual_output_kw, 0.0)
    energy_generated = _number(reading.energy_generated_kwh, 0.0)
    irradiance = _number(reading.irradiance_w_m2, 0.0)
    panel_temperature = _number(reading.panel_temperature_c)
    ambient_temperature = _number(reading.ambient_temperature_c)
    warnings: list[str] = []

    if capacity is None:
        warnings.append("Solar panel capacity unavailable")
    if actual is None:
        warnings.append("Actual solar output unavailable")
    if irradiance is None:
        warnings.append("Solar irradiance unavailable")
    weather = reading.weather.strip() if isinstance(reading.weather, str) else ""
    weather = weather or "Weather data unavailable"

    expected: Optional[float] = None
    performance: Optional[float] = None
    if capacity is not None and irradiance is not None:
        expected = capacity * min(irradiance / 1000.0, 1.0)
        expected *= config.system_efficiency
        expected *= _temperature_factor(panel_temperature, config)
        expected *= _weather_factor(reading, config)
        expected = max(0.0, expected)
        if actual is not None and expected > 0:
            performance = actual / expected * 100.0

    historical = list(historical_readings)
    previous_output = _number(historical[-1].actual_output_kw, 0.0) if historical else None
    status = _status(performance, thresholds)
    alerts: list[SolarAlert] = []

    if performance is not None and performance < thresholds.reduced_min_performance_pct:
        alerts.append(
            SolarAlert(
                title="Solar Efficiency Reduced",
                message=(
                    f"Expected Output: {expected:.1f} kW; Actual Output: {actual:.1f} kW; "
                    f"Performance: {performance:.1f}%"
                ),
                possible_causes=(
                    "High panel temperature",
                    "Cloud cover",
                    "Reduced irradiance",
                    "Panel/system losses",
                ),
            )
        )
    drop = _drop_pct(actual, previous_output)
    if drop is not None and drop >= thresholds.sudden_output_drop_pct:
        alerts.append(SolarAlert("Sudden Solar Output Drop", f"Output dropped {drop:.1f}% from the previous reading."))
    if panel_temperature is not None and panel_temperature >= thresholds.high_panel_temperature_c:
        alerts.append(SolarAlert("High Panel Temperature", "Panel temperature may be reducing photovoltaic efficiency."))
    if (
        irradiance is not None
        and irradiance >= thresholds.high_irradiance_w_m2
        and performance is not None
        and performance < thresholds.high_irradiance_low_performance_pct
    ):
        alerts.append(SolarAlert("Low Output at High Irradiance", "Solar output is unexpectedly low for the available sunlight."))

    return SolarEfficiencyResult(
        panel_capacity_kw=capacity,
        current_solar_output_kw=actual,
        energy_generated_kwh=energy_generated,
        solar_irradiance_w_m2=irradiance,
        panel_temperature_c=panel_temperature,
        ambient_temperature_c=ambient_temperature,
        weather=weather,
        expected_solar_output_kw=expected,
        actual_solar_output_kw=actual,
        solar_performance_pct=performance,
        efficiency_status=status,
        alerts=tuple(alerts),
        data_warnings=tuple(warnings),
    )


def build_trend(
    readings: Iterable[SolarReading],
    *,
    thresholds: SolarThresholds = SolarThresholds(),
    config: SolarConfiguration = SolarConfiguration(),
) -> list[dict[str, Optional[float] | str]]:
    """Build graph-ready time, performance, and output points."""
    trend: list[dict[str, Optional[float] | str]] = []
    prior: list[SolarReading] = []
    for reading in readings:
        result = calculate_solar_efficiency(reading, prior, thresholds=thresholds, config=config)
        trend.append(
            {
                "time": reading.timestamp or "Time unavailable",
                "solar_performance_pct": result.solar_performance_pct,
                "solar_output_kw": result.actual_solar_output_kw,
            }
        )
        prior.append(reading)
    return trend


def format_display(result: SolarEfficiencyResult) -> str:
    """Format a safe human-readable display without NaN or Infinity values."""
    def value(number: Optional[float], unit: str = "") -> str:
        return f"{number:.1f}{unit}" if number is not None else "Unavailable"

    lines = [
        "SOLAR EFFICIENCY",
        f"Panel Capacity:       {value(result.panel_capacity_kw, ' kW')}",
        f"Solar Output:         {value(result.current_solar_output_kw, ' kW')}",
        f"Irradiance:            {value(result.solar_irradiance_w_m2, ' W/m2')}",
        f"Panel Temperature:     {value(result.panel_temperature_c, ' C')}",
        f"Ambient Temperature:   {value(result.ambient_temperature_c, ' C')}",
        f"Weather:               {result.weather}",
        f"Expected Output:       {value(result.expected_solar_output_kw, ' kW')}",
        f"Actual Output:         {value(result.actual_solar_output_kw, ' kW')}",
        f"Performance:           {value(result.solar_performance_pct, '%')}",
        f"Status:                {result.efficiency_status.value}",
    ]
    return "\n".join(lines)