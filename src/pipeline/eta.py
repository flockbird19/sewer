import math
import statistics

import config


def estimate_eta(samples) -> dict:
    """
    Time until this gas reaches 100% of its alarm level, as a RANGE.

    samples: recent (timestamp_sec, pct_of_threshold) pairs, oldest first,
    all real readings (no held values). The caller
    (PipelineCoordinator._finish) only calls this once a rise is already
    confirmed - that gate is what stops an estimate flapping on noise,
    the bug that got the original curve-fit ETA removed (see progress.md).

    Two straight-line fits over the same window, both least-squares:

      linear       pct      vs time  ->  "it keeps rising at this speed"
      exponential  ln(pct)  vs time  ->  "it keeps accelerating like this"

    A steady inflow looks linear, a worsening leak looks exponential, and
    early in a rise the data cannot tell them apart (measured: the first
    version used the linear guess alone and was 41-48% off on linear leaks
    and 190-1000 s too optimistic on exponential ones). So this reports
    both: the earlier time is the one to act on, the later one is the
    best case. The range is wide at first and narrows as the level climbs.

    Returns eta_minutes (the EARLIER, conservative estimate),
    eta_minutes_high (the later one) and a display label. All None when
    the window is too short or the level is not rising.
    """
    none = {"eta_minutes": None, "eta_minutes_high": None, "eta_label": None}
    samples = [(t, p) for t, p in samples if p > 0]
    if len(samples) < config.ETA_MIN_SAMPLES:
        return none
    times = [t for t, _ in samples]
    if times[-1] - times[0] < config.ETA_MIN_SPAN_SEC:
        return none

    pcts = [p for _, p in samples]
    slope, slope_err, intercept = _fit(times, pcts)
    growth, growth_err, _ = _fit(times, [math.log(p) for p in pcts])
    if slope <= 0 or growth <= 0:
        return none

    # Extrapolate from the fitted value at the newest sample, not the raw
    # newest sample, so one noisy reading does not move the estimate.
    now_pct = min(max(slope * times[-1] + intercept, 0.01), 99.99)
    # Each end of the range is pushed outward by the uncertainty of its
    # own fit: the earlier end assumes the fastest plausible growth, the
    # later end the slowest plausible rise.
    fastest = max(slope + slope_err, growth * now_pct + growth_err * now_pct)
    eta_linear_slowest = (100.0 - now_pct) / (slope - slope_err) / 60.0 if slope > slope_err else math.inf
    eta_exponential_fastest = math.log(100.0 / now_pct) / (growth + growth_err) / 60.0
    low = min(eta_exponential_fastest, (100.0 - now_pct) / fastest / 60.0)
    high = max(eta_linear_slowest, math.log(100.0 / now_pct) / max(growth - growth_err, 1e-9) / 60.0)

    cap = config.ETA_CAP_MINUTES
    low_text = "under 1" if low < 1 else f"{low:.0f}"
    if low > cap:
        label = f">{cap:.0f} min"
    elif high > cap:  # also covers an unbounded later end (math.inf)
        label = f"{low_text} to >{cap:.0f} min"
    elif high < 1:
        label = "under 1 min"
    elif low >= 1 and round(low) == round(high):
        label = f"~{low:.0f} min"
    else:
        label = f"{low_text} to {high:.0f} min"
    return {"eta_minutes": low, "eta_minutes_high": high, "eta_label": label}


def _fit(xs, ys):
    """Least-squares line: (slope, uncertainty of the slope, intercept).

    The uncertainty is the usual standard error times
    config.ETA_UNCERTAINTY_MULTIPLE. The usual formula assumes each
    reading's noise is independent; ours come out of a 5-sample median
    filter, so neighbours share noise and the formula alone understates
    the error - the multiple was set by measurement (see
    tests/test_detection_quality.py), not theory."""
    fit = statistics.linear_regression(xs, ys)
    mean_x = statistics.fmean(xs)
    spread = sum((x - mean_x) ** 2 for x in xs)
    residual = sum((y - (fit.slope * x + fit.intercept)) ** 2 for x, y in zip(xs, ys))
    stderr = math.sqrt(residual / (len(xs) - 2) / spread)
    return fit.slope, config.ETA_UNCERTAINTY_MULTIPLE * stderr, fit.intercept
