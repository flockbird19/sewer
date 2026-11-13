import sys
from pathlib import Path

# Add src to path so we can import pipeline directly
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pipeline.coordinator import PipelineCoordinator
from pipeline.eta import estimate_eta


def test_stays_safe_on_flat_data():
    """Flat, non-rising data must never produce anything above Safe."""
    coordinator = PipelineCoordinator(threshold=100.0, gas_name="Test")
    for t in range(100):
        result = coordinator.process_reading(10.0, float(t))
        assert result["status"] == "Safe", f"t={t}: expected Safe, got {result['status']}"
    print("PASS: test_stays_safe_on_flat_data")


def test_critical_fires_without_confirmation_delay():
    """The safety floor (Layer 1) must never wait for the multi-tick
    confirmation counter - the moment the SMOOTHED reading reflects a real
    threshold breach, that tick is Critical. (A single isolated spike is
    correctly absorbed by the median filter as noise first - that's the
    filter doing its job, not a delay. A realistic ramp, not an instant
    100%+ teleport, is used here on purpose: an abrupt jump that big is
    treated with suspicion by design, since it's the same signature as a
    stuck/faulty sensor - see test_persistent_jump_is_eventually_trusted
    for that exact case, and progress.md for why.)"""
    coordinator = PipelineCoordinator(threshold=100.0, gas_name="Test")
    for t in range(10):
        coordinator.process_reading(10.0, float(t))  # warm up on safe data
    result = None
    for t in range(10, 40):
        val = min(10.0 + (t - 9) * 20.0, 150.0)  # ramps up over several ticks, not an instant jump
        result = coordinator.process_reading(val, float(t))
        if result["status"] == "Critical":
            break
    assert result["status"] == "Critical", f"expected Critical once breach is sustained, got {result['status']}"
    print("PASS: test_critical_fires_without_confirmation_delay")


def test_persistent_jump_is_eventually_trusted():
    """A jump too large to accept outright is treated with suspicion (it
    looks the same as a stuck/faulty sensor) - but if it keeps recurring,
    the system must eventually trust it rather than freezing on the old
    value forever. A real reading must never be permanently ignored."""
    coordinator = PipelineCoordinator(threshold=100.0, gas_name="Test")
    for t in range(10):
        coordinator.process_reading(10.0, float(t))  # warm up on safe data
    result = None
    for t in range(10, 40):
        result = coordinator.process_reading(150.0, float(t))  # abrupt and then held constant
    assert result["smoothed_value"] > 100.0, (
        f"a persistent new reading was never trusted - stuck at {result['smoothed_value']}"
    )
    print("PASS: test_persistent_jump_is_eventually_trusted")


def test_single_spike_does_not_upgrade_status():
    """One noisy tick must not be enough to raise the confirmed status -
    this is the direct fix for the flapping bug found in the old
    curve-fit predictor (see progress.md)."""
    coordinator = PipelineCoordinator(threshold=100.0, gas_name="Test")
    for t in range(30):
        coordinator.process_reading(10.0, float(t))
    result = coordinator.process_reading(40.0, 30.0)  # one noisy jump, still well under threshold
    assert result["status"] == "Safe", f"single spike should not upgrade status, got {result['status']}"
    print("PASS: test_single_spike_does_not_upgrade_status")


def test_sustained_rise_eventually_upgrades():
    """A rise that keeps happening tick after tick (not just once) should
    eventually be confirmed - the system must still be able to warn."""
    coordinator = PipelineCoordinator(threshold=100.0, gas_name="Test")
    statuses = []
    for t in range(60):
        val = 10.0 + t * 2.0  # steady climb, well past the rate-of-rise limit
        result = coordinator.process_reading(val, float(t))
        statuses.append(result["status"])
    assert any(s != "Safe" for s in statuses), "a sustained rise never triggered any warning"
    print("PASS: test_sustained_rise_eventually_upgrades")


def _ramp(start_pct, pct_per_min, seconds=60):
    return [(float(t), start_pct + pct_per_min / 60.0 * t) for t in range(seconds)]


def test_eta_none_on_flat_or_declining_rate():
    """Flat, falling or too-short data must yield no ETA at all."""
    for samples in (_ramp(10.0, 0.0), _ramp(50.0, -5.0), _ramp(10.0, 10.0, seconds=5)):
        result = estimate_eta(samples)
        assert result["eta_minutes"] is None and result["eta_label"] is None, result
    print("PASS: test_eta_none_on_flat_or_declining_rate")


def test_eta_range_brackets_a_linear_rise():
    """On a noise-free linear rise the true time must sit inside the
    reported range, and the later end must equal the linear answer."""
    samples = _ramp(40.0, 10.0)                 # ends at 49.83%, climbing 10%/min
    truth = (100.0 - samples[-1][1]) / 10.0     # minutes
    result = estimate_eta(samples)
    assert result["eta_minutes"] <= truth <= result["eta_minutes_high"] + 1e-6, (result, truth)
    assert abs(result["eta_minutes_high"] - truth) < 0.01, (result, truth)
    print(f"PASS: test_eta_range_brackets_a_linear_rise ({result['eta_label']}, truth {truth:.1f} min)")


def test_eta_label_survives_an_unbounded_later_end():
    """Noisy, barely-rising data: the slowest plausible rise is no rise at
    all, so the later end is unbounded. Must give a label, not crash
    (regression: round(inf) raised OverflowError)."""
    import random
    random.seed(4)
    samples = [(float(t), 20.0 + 0.02 * t + random.gauss(0, 1.5)) for t in range(60)]
    result = estimate_eta(samples)
    if result["eta_label"] is not None:
        assert result["eta_label"].endswith(">45 min"), result
    print(f"PASS: test_eta_label_survives_an_unbounded_later_end ({result['eta_label']})")


def test_eta_label_above_cap_shows_floor():
    """A rise so slow that even the earlier estimate is past the cap
    reports a floor, not a falsely precise number."""
    result = estimate_eta(_ramp(10.0, 0.05))
    assert result["eta_label"] == ">45 min", result
    print("PASS: test_eta_label_above_cap_shows_floor")


def test_eta_absent_before_confirmed_rising():
    """Flat, non-rising data must never carry an ETA - directly mirrors
    test_stays_safe_on_flat_data, but checking the new fields."""
    coordinator = PipelineCoordinator(threshold=100.0, gas_name="Test")
    for t in range(100):
        result = coordinator.process_reading(10.0, float(t))
        assert result["eta_minutes"] is None, f"t={t}: expected no ETA on flat data, got {result['eta_minutes']}"
        assert result["eta_label"] is None
    print("PASS: test_eta_absent_before_confirmed_rising")


def test_eta_appears_once_status_confirmed_rising():
    """Once a sustained rise is confirmed (Early Warning or worse), the
    result must carry a non-None ETA - this is the actual feature working
    end-to-end through the coordinator, not just the pure function."""
    coordinator = PipelineCoordinator(threshold=100.0, gas_name="Test")
    result = None
    for t in range(60):
        val = 10.0 + t * 2.0  # same steady climb used in test_sustained_rise_eventually_upgrades
        result = coordinator.process_reading(val, float(t))
        if result["status"] != "Safe":
            break
    assert result["status"] != "Safe", "a sustained rise never triggered any warning"
    if result["status"] == "Critical":
        assert result["eta_minutes"] is None, "Critical should never carry an ETA - it's already there"
    else:
        assert result["eta_minutes"] is not None, (
            f"expected an ETA once status={result['status']}, got eta_minutes=None"
        )
        assert result["eta_label"] is not None
        assert "ETA to critical" in result["reason"], f"expected ETA mentioned in reason, got: {result['reason']}"
    print(f"PASS: test_eta_appears_once_status_confirmed_rising (status={result['status']}, eta={result['eta_label']})")


def test_eta_absent_on_critical():
    """Critical always fires off the instant safety floor, before the
    trend/ETA logic ever runs - it must never carry an ETA (the gas is
    already there, an 'arrival time' is meaningless)."""
    coordinator = PipelineCoordinator(threshold=100.0, gas_name="Test")
    for t in range(10):
        coordinator.process_reading(10.0, float(t))  # warm up
    result = None
    for t in range(10, 40):
        val = min(10.0 + (t - 9) * 20.0, 150.0)
        result = coordinator.process_reading(val, float(t))
        if result["status"] == "Critical":
            break
    assert result["status"] == "Critical", f"expected Critical, got {result['status']}"
    assert result["eta_minutes"] is None, f"Critical must not carry an ETA, got {result['eta_minutes']}"
    assert result["eta_label"] is None
    print("PASS: test_eta_absent_on_critical")


if __name__ == "__main__":
    test_stays_safe_on_flat_data()
    test_critical_fires_without_confirmation_delay()
    test_persistent_jump_is_eventually_trusted()
    test_single_spike_does_not_upgrade_status()
    test_sustained_rise_eventually_upgrades()
    test_eta_none_on_flat_or_declining_rate()
    test_eta_range_brackets_a_linear_rise()
    test_eta_label_survives_an_unbounded_later_end()
    test_eta_label_above_cap_shows_floor()
    test_eta_absent_before_confirmed_rising()
    test_eta_appears_once_status_confirmed_rising()
    test_eta_absent_on_critical()
    print("\nAll pipeline tests passed.")
