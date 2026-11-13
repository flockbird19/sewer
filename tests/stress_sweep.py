"""Large-scale randomized check of the detection pipeline.

Every gas x every scenario x many random seeds. Reports false alarms on
quiet/faulty data, severity flapping on real leaks, how close Critical
fires to the true crossing, and how much warning a slow leak gets.
Small runs miss real bugs in this pipeline (see progress.md), so run
hundreds of seeds before trusting any change to detection logic.

Run: python tests/stress_sweep.py [seeds]      (default 100)
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import config
from config import GAS_CONFIGS
from generator.synthetic_gas_data import generate_gas_data, true_crossing_time
from test_detection_quality import _coordinator_for

SEVERITY = {"Safe": 0, "Early Warning": 1, "Imminent": 2, "Critical": 3}
DURATION = 600


def run(seeds):
    failures = 0
    ticks = 0
    for gas, cfg in GAS_CONFIGS.items():
        tolerance = 10 + config.MQ7_HEATER_HIGH_SEC if gas == "CO" else 10
        false_alarm_runs = flapping_runs = late_critical = no_warning = 0
        leads, first_warn_pct = [], []
        for seed in range(seeds):
            for scenario in ["baseline", "sensor_fault", "slow_leak", "fast_leak"]:
                np.random.seed(seed)
                data = generate_gas_data(scenario, DURATION, gas)
                c = _coordinator_for(cfg, gas)
                statuses = []
                pcts = []
                for t, v in enumerate(data):
                    r = c.process_reading(v, float(t))
                    statuses.append(SEVERITY[r["status"]])
                    pcts.append(r["pct_of_threshold"])
                ticks += len(data)
                if scenario in ("baseline", "sensor_fault"):
                    if max(statuses) > 0:
                        false_alarm_runs += 1
                        if false_alarm_runs <= 2:
                            print(f"  false alarm: {gas}/{scenario} seed {seed} at t={statuses.index(max(statuses))}")
                    continue
                running_max = np.maximum.accumulate(statuses)
                if (np.array(statuses) < running_max).any():
                    flapping_runs += 1
                    if flapping_runs <= 2:
                        print(f"  flapping: {gas}/{scenario} seed {seed}")
                truth = true_crossing_time(scenario, DURATION, gas)
                crit = statuses.index(3) if 3 in statuses else None
                if crit is None or abs(crit - truth) > tolerance:
                    late_critical += 1
                    if late_critical <= 2:
                        print(f"  critical timing: {gas}/{scenario} seed {seed} fired {crit}, truth {truth:.0f}")
                warn = next((t for t, s in enumerate(statuses) if s in (1, 2)), None)
                if scenario == "slow_leak":
                    if warn is None or crit is None or warn >= crit:
                        no_warning += 1
                    else:
                        leads.append(crit - warn)
                        first_warn_pct.append(pcts[warn])
        bad = false_alarm_runs + flapping_runs + late_critical + no_warning
        failures += bad
        print(f"{gas:4s} false-alarm runs {false_alarm_runs}/{2 * seeds}  flapping runs {flapping_runs}/{2 * seeds}  "
              f"critical off-time {late_critical}/{2 * seeds}  slow leaks with no warning {no_warning}/{seeds}  "
              f"warning before Critical: min {min(leads, default=0)}s mean {np.mean(leads) if leads else 0:.0f}s "
              f"(first warning at {np.mean(first_warn_pct) if first_warn_pct else 0:.0f}% of alarm level)")
    print(f"{seeds} seeds, {ticks:,} ticks, {failures} failing runs")
    return failures


if __name__ == "__main__":
    sys.exit(1 if run(int(sys.argv[1]) if len(sys.argv) > 1 else 100) else 0)
