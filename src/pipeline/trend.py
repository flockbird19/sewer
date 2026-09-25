import math
import config


class TrendDetector:
    """
    Decides whether ONE gas's normalized reading is genuinely rising,
    using the same family of methods real industrial process-safety
    monitoring uses (statistical process control), instead of fitting a
    curve and solving for an exact future crossing time.

    Why not curve-fitting: fitting a line/exponential to ~30 noisy points
    and solving for when it crosses the threshold sounds precise, but a
    few points of ordinary sensor noise can coincidentally look like the
    start of a real curve and produce a confident, wrong prediction. This
    was measured directly on the old implementation: readings at 1-2% of
    the danger threshold triggered "Imminent" repeatedly. See progress.md.

    This class only answers "is it rising, and how fast" - it never
    predicts an exact arrival time. Two independent checks:

      1. Rate of rise: a fast-reacting EWMA of the signal, compared tick
         to tick, expressed as %-of-threshold per minute, then smoothed
         AGAIN with its own EWMA - a derivative amplifies noise, so
         smoothing only the level and not the rate lets a handful of
         unlucky ticks make a real, ongoing rise look like it paused.
      2. CUSUM (cumulative sum): the gap between the fast EWMA and a
         slow, stable "normal baseline" EWMA, accumulated over time.
         Catches a slow, steady drift too gentle for the rate check to
         notice on any single tick, but that adds up.

    Both are O(1) per tick - two running numbers, no stored history -
    which also makes this far cheaper than re-fitting a curve every
    second on an edge device.

    All three EWMAs are TIME-WEIGHTED, not fixed-per-call: the effective
    smoothing factor is derived from the actual elapsed time since the
    last update, not just "one more tick happened". This matters because
    not every gas samples at a uniform 1-second cadence any more - MQ-7
    (CO) only produces a valid reading ~90s out of every 150s heater
    cycle (see heater_cycle.py). A fixed per-tick alpha applied across a
    60+ second gap would badly misrepresent the trend; this was caught by
    testing once the heater cycle was modeled (see progress.md).
    """

    def __init__(
        self,
        fast_tau: float = config.EWMA_FAST_TAU_SEC,
        slow_tau: float = config.EWMA_SLOW_TAU_SEC,
        rate_tau: float = config.RATE_EWMA_TAU_SEC,
        cusum_slack: float = config.CUSUM_SLACK_PCT,
        cusum_alert: float = config.CUSUM_ALERT_PCT,
        rate_limit_pct_per_min: float = config.RATE_LIMIT_PCT_PER_MIN,
    ):
        self.fast_tau = fast_tau
        self.slow_tau = slow_tau
        self.rate_tau = rate_tau
        self.cusum_slack = cusum_slack
        self.cusum_alert = cusum_alert
        self.rate_limit_pct_per_min = rate_limit_pct_per_min

        self.fast_ewma = None
        self.slow_ewma = None
        self.rate_ewma = 0.0
        self.prev_fast_ewma = None
        self.prev_timestamp = None
        self.cusum = 0.0

    def update(self, pct_of_threshold: float, timestamp: float) -> dict:
        """
        pct_of_threshold: current smoothed reading, expressed as a percent
        of this gas's own critical threshold (e.g. 25.0 = a quarter of the
        way to danger). Normalizing this way lets one shared rate/CUSUM
        limit apply to every gas, no matter its absolute PPM scale.
        """
        if self.fast_ewma is None:
            # First sample ever: seed both EWMAs at the current value so we
            # don't start by pretending the baseline was zero.
            self.fast_ewma = pct_of_threshold
            self.slow_ewma = pct_of_threshold
            self.prev_fast_ewma = pct_of_threshold
            self.prev_timestamp = timestamp
            return {"rate_pct_per_min": 0.0, "cusum": 0.0, "rising": False}

        dt_sec = max(timestamp - self.prev_timestamp, 1e-6)

        alpha_fast = 1.0 - math.exp(-dt_sec / self.fast_tau)
        alpha_slow = 1.0 - math.exp(-dt_sec / self.slow_tau)
        self.fast_ewma = alpha_fast * pct_of_threshold + (1 - alpha_fast) * self.fast_ewma
        self.slow_ewma = alpha_slow * pct_of_threshold + (1 - alpha_slow) * self.slow_ewma

        instantaneous_rate = (self.fast_ewma - self.prev_fast_ewma) / dt_sec * 60.0
        alpha_rate = 1.0 - math.exp(-dt_sec / self.rate_tau)
        self.rate_ewma = alpha_rate * instantaneous_rate + (1 - alpha_rate) * self.rate_ewma

        # How far the fast average currently sits above the slow baseline.
        # This is the same quantity CUSUM accumulates below - but used
        # directly, it's a far more stable "is this still elevated" signal
        # than a derivative is: it compares two already-smoothed values
        # instead of differencing one of them tick to tick, so it doesn't
        # inherit the rate estimate's noise.
        elevated_above_baseline = (self.fast_ewma - self.slow_ewma) > self.cusum_slack

        # One-sided CUSUM: only accumulates while elevated_above_baseline is
        # true. Resets to zero (via the max(0, ...)) once it isn't.
        deviation = (self.fast_ewma - self.slow_ewma) - self.cusum_slack
        self.cusum = max(0.0, self.cusum + deviation)

        self.prev_fast_ewma = self.fast_ewma
        self.prev_timestamp = timestamp

        # Rising if it's currently elevated above its own recent baseline,
        # OR climbing fast, OR has been elevated for a while (CUSUM). The
        # measured bug this fixes: a genuinely ongoing rise still counts as
        # rising even during a few ticks where the (noisier) rate estimate
        # alone would have said otherwise - elevated_above_baseline catches
        # it because it isn't a derivative and doesn't inherit that noise.
        rising = elevated_above_baseline or self.rate_ewma > self.rate_limit_pct_per_min or self.cusum > self.cusum_alert

        return {"rate_pct_per_min": self.rate_ewma, "cusum": self.cusum, "rising": rising}
