import unittest
import json

from solar_efficiency import (
    EfficiencyStatus,
    SolarReading,
    build_trend,
    calculate_solar_efficiency,
    format_display,
)


class SolarEfficiencyTests(unittest.TestCase):
    def test_output_above_expected_is_high(self):
        result = calculate_solar_efficiency(
            SolarReading(100, 95, irradiance_w_m2=800, weather="Sunny")
        )
        self.assertEqual(result.efficiency_status, EfficiencyStatus.HIGH)

    def test_sunny_moderate_temperature_is_normal(self):
        result = calculate_solar_efficiency(
            SolarReading(100, 78, 78, 850, 32, 28, "Sunny")
        )
        self.assertEqual(result.efficiency_status, EfficiencyStatus.NORMAL)
        self.assertIsNotNone(result.solar_performance_pct)

    def test_hot_panel_reduces_expected_output_and_alerts(self):
        result = calculate_solar_efficiency(
            SolarReading(100, 60, 60, 900, 60, 35, "Sunny")
        )
        self.assertLess(result.expected_solar_output_kw, 90)
        self.assertTrue(any("temperature" in alert.title.lower() for alert in result.alerts))

    def test_cloudy_and_rainy_conditions_do_not_force_zero(self):
        cloudy = calculate_solar_efficiency(SolarReading(100, 30, 30, 500, 30, 25, "Cloudy"))
        rainy = calculate_solar_efficiency(SolarReading(100, 12, 12, 250, 28, 24, "Heavy rain"))
        self.assertGreater(cloudy.expected_solar_output_kw, 0)
        self.assertGreater(rainy.expected_solar_output_kw, 0)

    def test_cool_temperature_needs_sunlight_to_generate(self):
        result = calculate_solar_efficiency(SolarReading(100, 0, 0, 0, 5, 5, "Clear"))
        self.assertEqual(result.efficiency_status, EfficiencyStatus.LOW)
        self.assertEqual(result.expected_solar_output_kw, 0)

    def test_low_output_at_high_irradiance_alerts(self):
        result = calculate_solar_efficiency(SolarReading(100, 20, 20, 900, 30, 25, "Sunny"))
        self.assertTrue(any("High Irradiance" in alert.title for alert in result.alerts))

    def test_sudden_drop_alert_uses_history(self):
        previous = SolarReading(100, 90, 90, 900, 30, 25, "Sunny")
        current = SolarReading(100, 50, 50, 900, 30, 25, "Sunny")
        result = calculate_solar_efficiency(current, [previous])
        self.assertTrue(any("Sudden" in alert.title for alert in result.alerts))

    def test_missing_values_are_safe(self):
        result = calculate_solar_efficiency(SolarReading(100, 10, weather=None, irradiance_w_m2=None))
        display = format_display(result)
        self.assertIsNone(result.solar_performance_pct)
        self.assertEqual(result.weather, "Weather data unavailable")
        self.assertIn("Solar irradiance unavailable", result.data_warnings)
        self.assertNotIn("NaN", display)
        self.assertNotIn("Infinity", display)

    def test_missing_weather_is_safe_when_irradiance_is_available(self):
        result = calculate_solar_efficiency(SolarReading(100, 70, irradiance_w_m2=800))
        self.assertEqual(result.weather, "Weather data unavailable")
        self.assertIsNotNone(result.solar_performance_pct)

    def test_invalid_numeric_and_weather_values_do_not_raise(self):
        result = calculate_solar_efficiency(
            SolarReading(
                panel_capacity_kw="100",
                actual_output_kw=float("nan"),
                energy_generated_kwh=float("inf"),
                irradiance_w_m2=-50,
                panel_temperature_c="hot",
                weather=123,
                cloud_rain_condition=object(),
            )
        )
        self.assertIsNone(result.panel_capacity_kw)
        self.assertIsNone(result.actual_solar_output_kw)
        self.assertIsNone(result.energy_generated_kwh)
        self.assertIsNone(result.solar_irradiance_w_m2)
        self.assertEqual(result.weather, "Weather data unavailable")

    def test_thresholds_are_configurable(self):
        from solar_efficiency import SolarThresholds

        result = calculate_solar_efficiency(
            SolarReading(100, 80, irradiance_w_m2=800, weather="Sunny"),
            thresholds=SolarThresholds(normal_min_performance_pct=105),
        )
        self.assertEqual(result.efficiency_status, EfficiencyStatus.REDUCED)

    def test_result_is_json_serializable_and_preserves_energy(self):
        result = calculate_solar_efficiency(SolarReading(100, 70, 70, 800, weather="Sunny"))
        payload = json.dumps(result.to_dict())
        self.assertIn('"energy_generated_kwh": 70.0', payload)

    def test_trend_is_graph_ready(self):
        readings = [
            SolarReading(100, 70, 70, 800, 30, 25, "Sunny", timestamp="10:00"),
            SolarReading(100, 60, 60, 700, 31, 26, "Cloudy", timestamp="11:00"),
        ]
        trend = build_trend(readings)
        self.assertEqual([point["time"] for point in trend], ["10:00", "11:00"])
        self.assertIn("solar_performance_pct", trend[0])
        self.assertIn("solar_output_kw", trend[0])


if __name__ == "__main__":
    unittest.main()