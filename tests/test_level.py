"""Checks for the sewage level monitor and for readings that go missing."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import GAS_CONFIGS
from pipeline.aggregator import MultiGasAggregator
from pipeline.coordinator import PipelineCoordinator
from pipeline.level import LevelMonitor


def test_level_warns_before_overflow_and_ignores_glitches():
    random.seed(1)
    monitor = LevelMonitor(empty_cm=300.0, full_cm=30.0)
    seen = []
    for t in range(900):
        # Tank fills steadily from empty to past the overflow line.
        distance = 300.0 - t * 0.32 + random.gauss(0, 1.0)
        if t % 40 == 7:
            distance = 0.0       # sensor got no echo
        if t == 100:
            distance = 31.0      # one wild reading while the tank is nearly empty
        result = monitor.process_reading(distance, float(t))
        if t < 400:
            assert result["status"] == "Safe", f"t={t}: false level alarm {result}"
        if not seen or seen[-1] != result["status"]:
            seen.append(result["status"])
    assert seen == ["Safe", "Early Warning", "Imminent", "Critical"], seen
    print("PASS: test_level_warns_before_overflow_and_ignores_glitches")


def test_level_gives_time_to_overflow():
    monitor = LevelMonitor(empty_cm=300.0, full_cm=30.0)
    label = None
    for t in range(900):
        result = monitor.process_reading(300.0 - t * 0.32, float(t))
        if result["status"] == "Early Warning" and result["eta_label"]:
            label = result["eta_label"]
    assert label is not None, "no time-to-overflow estimate while the level was high and rising"
    print(f"PASS: test_level_gives_time_to_overflow (last Early Warning estimate: {label})")


def test_missing_gas_reading_is_held_not_treated_as_zero():
    """A lost packet (None) must hold the last known state: no crash, no
    alarm, no reset, and the result must say it is held."""
    coordinator = PipelineCoordinator(threshold=100.0, gas_name="Test")
    random.seed(2)
    for t in range(60):
        coordinator.process_reading(10.0 + random.gauss(0, 0.2), float(t))
    for t in range(60, 120):
        result = coordinator.process_reading(None, float(t))
        assert result["held"] and result["status"] == "Safe", result
        assert abs(result["smoothed_value"] - 10.0) < 1.0, result
    for t in range(120, 200):
        result = coordinator.process_reading(10.0 + random.gauss(0, 0.2), float(t))
        assert not result["held"] and result["status"] == "Safe", f"t={t}: {result}"
    print("PASS: test_missing_gas_reading_is_held_not_treated_as_zero")


def test_site_status_is_worst_of_gas_and_level():
    aggregator = MultiGasAggregator(configs=GAS_CONFIGS, level_monitor=LevelMonitor(empty_cm=300.0, full_cm=30.0))
    result = None
    for t in range(40):
        result = aggregator.process_readings({"CH4": 500.0, "CO": 2.0}, float(t), level_cm=32.0)
    assert result["master_status"] == "Safe", result["master_status"]
    assert result["level"]["status"] == "Critical", result["level"]
    assert result["site_status"] == "Critical", result["site_status"]
    assert set(result["gas_results"]) == {"CH4", "CO"}, "sensors that are not installed must simply be absent"
    print("PASS: test_site_status_is_worst_of_gas_and_level")


if __name__ == "__main__":
    test_level_warns_before_overflow_and_ignores_glitches()
    test_level_gives_time_to_overflow()
    test_missing_gas_reading_is_held_not_treated_as_zero()
    test_site_status_is_worst_of_gas_and_level()
    print("\nAll level and missing-reading tests passed.")
