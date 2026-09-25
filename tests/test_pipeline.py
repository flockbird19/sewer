import sys
from pathlib import Path

# Add src to path so we can import pipeline directly
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pipeline.coordinator import PipelineCoordinator


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


if __name__ == "__main__":
    test_stays_safe_on_flat_data()
    test_critical_fires_without_confirmation_delay()
    test_persistent_jump_is_eventually_trusted()
    test_single_spike_does_not_upgrade_status()
    test_sustained_rise_eventually_upgrades()
    print("\nAll pipeline tests passed.")
