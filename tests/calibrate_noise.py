"""Measure how large the trend signals get on pure noise, in units of the
channel's own noise estimate. Used to set NOISE_*_MULTIPLE in config.py.

Run: python tests/calibrate_noise.py [seeds]
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import config
from config import GAS_CONFIGS
from generator.synthetic_gas_data import generate_gas_data
from test_detection_quality import _coordinator_for

seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 50
for gas, cfg in GAS_CONFIGS.items():
    for scenario in ["baseline", "sensor_fault"]:
        gaps, rates, noises, cus = [], [], [], []
        for seed in range(seeds):
            np.random.seed(seed)
            c = _coordinator_for(cfg, gas)
            for t, v in enumerate(generate_gas_data(scenario, 600, gas)):
                c.process_reading(v, float(t))
                tr = c.trend
                if tr.noise and tr._noise_samples >= config.NOISE_MIN_SAMPLES:
                    gaps.append((tr.fast_ewma - tr.slow_ewma) / tr.noise)
                    rates.append(tr.rate_ewma / tr.noise)
                    noises.append(tr.noise)
                    cus.append(tr.cusum / tr.noise)
        g, r = np.array(gaps), np.array(rates)
        print(f"{gas:4s}{scenario:13s} noise={np.mean(noises):.3f}%  "
              f"gap/noise p99.9={np.percentile(g, 99.9):.2f} max={g.max():.2f}  "
              f"rate/noise p99.9={np.percentile(r, 99.9):.1f} max={r.max():.1f}  cusum/noise p99.9={np.percentile(cus, 99.9):.1f} max={max(cus):.1f}")
