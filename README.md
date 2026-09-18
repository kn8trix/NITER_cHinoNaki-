# Solar Efficiency System

This is a standalone Python backend module for monitoring solar panel performance. It calculates expected output from panel capacity, irradiance, temperature, and weather conditions, then reports performance as `HIGH`, `NORMAL`, `REDUCED`, or `LOW`.

It intentionally does not implement battery management, grid management, dispatch, LP optimization, prediction, or tariff optimization.

## Run the checks

```text
python -m unittest -v
```

## Use from a web backend

```python
from solar_efficiency import SolarReading, calculate_solar_efficiency

result = calculate_solar_efficiency(
    SolarReading(
        panel_capacity_kw=100,
        actual_output_kw=78,
        energy_generated_kwh=78,
        irradiance_w_m2=850,
        panel_temperature_c=42,
        ambient_temperature_c=32,
        weather="Sunny",
    )
)

payload = result.to_dict()
```

Use `build_trend(readings)` for graph-ready performance and output series, and `format_display(result)` for a plain-text status display. Pass `SolarThresholds` or `SolarConfiguration` to tune operational behavior without changing the calculation code.