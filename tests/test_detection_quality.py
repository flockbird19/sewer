"""
Real, labeled evaluation of the detection pipeline - replaces "print a
table and eyeball it" with actual pass/fail numbers: false alarm rate,
detection lead time, and a direct regression check for the flapping bug
measured in the old curve-fit predictor. This is what "validated" should
mean for a safety system, and it didn't exist before this file.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pipeline.coordinator import PipelineCoordinator
from pipeline.aggregator import MultiGasAggregator
from pipeline.heater_cycle import MQ7HeaterCycle
import config
from config import GAS_CONFIGS
from generator.synthetic_gas_data import generate_gas_data, true_crossing_time

DURATION = 600


def _coordinator_for(cfg, gas=None):
    """Build a coordinator with this gas's FULL calibration, not just its
    threshold. Passing threshold alone silently falls back to the
    constructor's default max_ppm=10000 - harmless for H2S/CO/NH3 (well
    under 10000) but it clips CH4's real 50000 ppm threshold at 10000
    forever, making it physically impossible to ever reach Critical. This
    was caught by these exact tests failing - see progress.md.

    gas='CO' also wires up the MQ-7 heater duty cycle, so these tests
    reflect the real ~40% reading-availability constraint that sensor has
    (see docs/research/mq-sensor-calibration-and-gas-detection.md)."""
    return PipelineCoordinator(
        threshold=cfg.critical_ppm, gas_name=cfg.gas_name,
        a_calibration=cfg.a_calibration, b_calibration=cfg.b_calibration, max_ppm=cfg.max_ppm,
        heater_cycle=MQ7HeaterCycle() if gas == "CO" else None,
    )


def test_no_false_alarms_on_quiet_data():
    """A quiet channel, or one with injected sensor faults (which the
    median filter should strip), must NEVER report anything above Safe."""
    for gas, cfg in GAS_CONFIGS.items():
        for scenario in ["baseline", "sensor_fault"]:
            coordinator = _coordinator_for(cfg, gas)
            data = generate_gas_data(scenario, DURATION, gas)
            non_safe = [
                (t, result["status"])
                for t, val in enumerate(data)
                for result in [coordinator.process_reading(val, float(t))]
                if result["status"] != "Safe"
            ]
            assert not non_safe, f"{gas}/{scenario}: expected 0 false alarms, got {non_safe[:3]}"
    print("PASS: test_no_false_alarms_on_quiet_data (0 false alarms, all gases, baseline + sensor_fault)")


def test_no_flapping_on_real_leaks():
    """Regression test for the measured bug in the old curve-fit
    predictor: on fast_leak it flip-flopped Safe<->Imminent six times
    while the real reading was still at 1-2% of the danger threshold,
    each flip a confident-looking alert immediately retracted.

    NOTE: an early, low-percent 'Early Warning' is NOT automatically a
    false alarm - if it's a CONFIRMED, sustained rise (this pipeline
    requires several consecutive ticks to agree before it fires at all),
    catching it early is the entire point. What must never happen is the
    confirmed severity going back down and then back up again on a leak
    that is genuinely, monotonically getting worse - that's the actual
    cry-wolf-then-retract pattern that erodes trust."""
    SEVERITY = {"Safe": 0, "Early Warning": 1, "Imminent": 2, "Critical": 3}
    for gas, cfg in GAS_CONFIGS.items():
        for scenario in ["slow_leak", "fast_leak"]:
            coordinator = _coordinator_for(cfg, gas)
            data = generate_gas_data(scenario, DURATION, gas)
            max_severity_seen = 0
            regressions = []
            for t, val in enumerate(data):
                result = coordinator.process_reading(val, float(t))
                severity = SEVERITY[result["status"]]
                if severity < max_severity_seen:
                    regressions.append((t, result["status"], round(result["pct_of_threshold"], 1)))
                max_severity_seen = max(max_severity_seen, severity)
            assert not regressions, (
                f"{gas}/{scenario}: severity dropped then would need to rise again (flapping): {regressions[:5]}"
            )
    print("PASS: test_no_flapping_on_real_leaks (confirmed severity never regresses on a genuinely escalating leak)")


def test_detects_leaks_with_useful_lead_time():
    """On a real leak, the pipeline must reach Critical close to the true
    (noise-free) crossing time - not wildly early (a fluke) and not so
    late it's useless.

    CO gets a wider tolerance than the other three gases: MQ-7's mandatory
    heater duty cycle (see pipeline/heater_cycle.py) creates a real,
    datasheet-mandated blind window of up to MQ7_HEATER_HIGH_SEC seconds
    every cycle, during which no new CO reading exists at all - so a
    crossing that happens to fall inside that window is only detected
    once the next valid reading arrives. This is a genuine physical
    constraint of the sensor, not a software shortcoming, and loosening
    the CO tolerance to reflect it (rather than loosening it for every
    gas) keeps the test honest about where the slack actually comes from."""
    for gas, cfg in GAS_CONFIGS.items():
        tolerance_sec = 10 + config.MQ7_HEATER_HIGH_SEC if gas == "CO" else 10
        for scenario in ["slow_leak", "fast_leak"]:
            coordinator = _coordinator_for(cfg, gas)
            data = generate_gas_data(scenario, DURATION, gas)
            true_cross = true_crossing_time(scenario, DURATION, gas)

            critical_tick = next(
                (t for t, val in enumerate(data)
                 if coordinator.process_reading(val, float(t))["status"] == "Critical"),
                None,
            )
            assert critical_tick is not None, f"{gas}/{scenario}: never reached Critical"
            error = abs(critical_tick - true_cross)
            assert error <= tolerance_sec, (
                f"{gas}/{scenario}: Critical fired at t={critical_tick}, "
                f"true crossing was t={true_cross:.1f} (off by {error:.1f}s, tolerance {tolerance_sec}s)"
            )
    print("PASS: test_detects_leaks_with_useful_lead_time (Critical fires within 10s of true crossing, "
          f"or {10 + config.MQ7_HEATER_HIGH_SEC:.0f}s for CO's heater-cycle blind window)")


def test_early_warning_precedes_critical():
    """A useful system gives SOME advance notice before Critical on a
    slow leak - not just an instant Safe-to-Critical jump."""
    for gas, cfg in GAS_CONFIGS.items():
        coordinator = _coordinator_for(cfg, gas)
        data = generate_gas_data("slow_leak", DURATION, gas)
        first_warning_tick = None
        critical_tick = None
        for t, val in enumerate(data):
            result = coordinator.process_reading(val, float(t))
            if result["status"] in ("Early Warning", "Imminent") and first_warning_tick is None:
                first_warning_tick = t
            if result["status"] == "Critical":
                critical_tick = t
                break
        assert first_warning_tick is not None, f"{gas}: no advance warning before Critical on slow_leak"
        lead_time = critical_tick - first_warning_tick
        assert lead_time > 0, f"{gas}: warning did not precede Critical"
        print(f"  {gas}: {lead_time}s of advance warning before Critical (slow_leak)")
    print("PASS: test_early_warning_precedes_critical")


def test_multi_gas_fusion_flags_simultaneous_rise():
    """Two gases confirmed rising at once must be flagged as a joint
    pattern and treated as worse than either gas reported alone - the
    'combined gas patterns, not isolated thresholds' behavior a plain
    worst-of-N aggregator (the old design) can never produce."""
    aggregator = MultiGasAggregator(configs=GAS_CONFIGS)
    h2s_data = generate_gas_data("slow_leak", 300, "H2S")
    nh3_data = generate_gas_data("slow_leak", 300, "NH3")

    fused = None
    for t in range(300):
        readings = {"H2S": h2s_data[t], "NH3": nh3_data[t], "CH4": 500.0, "CO": 2.0}
        result = aggregator.process_readings(readings, float(t))
        if result["multi_gas_pattern"]:
            fused = result
            break

    assert fused is not None, "expected multi_gas_pattern to fire when two gases rise together"
    assert len(fused["contributing_gases"]) >= 2
    print(f"PASS: test_multi_gas_fusion_flags_simultaneous_rise (fired at t, gases={fused['contributing_gases']})")


if __name__ == "__main__":
    test_no_false_alarms_on_quiet_data()
    test_no_flapping_on_real_leaks()
    test_detects_leaks_with_useful_lead_time()
    test_early_warning_precedes_critical()
    test_multi_gas_fusion_flags_simultaneous_rise()
    print("\nAll detection-quality tests passed.")
