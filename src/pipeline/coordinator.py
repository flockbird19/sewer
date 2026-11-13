import collections
import statistics
from pipeline.calibration import ADCConverter
from pipeline.smoothing import MovingMedianFilter
from pipeline.trend import TrendDetector
from pipeline.hysteresis import StatusConfirmation
from pipeline.heater_cycle import MQ7HeaterCycle
from pipeline.eta import estimate_eta
import config


class PipelineCoordinator:
    """
    Turns one gas's raw sensor readings into a confirmed hazard status,
    one tick at a time. Pipeline, in order:

      -1. Heater cycle (MQ-7/CO only, when a heater_cycle is passed in) -
                      during the burn-off phase, no valid measurement
                      exists at all. The last known SMOOTHED reading is
                      held and fed through trend/confirm as if unchanged,
                      rather than the whole pipeline freezing: freezing
                      would leave a 60+ second gap for the trend detector
                      to jump across later, which is long enough to
                      corrupt its "recent baseline" EWMA too (caught by
                      testing - see progress.md). Holding the value
                      steady correctly reads as "no new information", not
                      as a data gap to recover from.
      0a. Bootstrap  - the first REFERENCE_BOOTSTRAP_SAMPLES ticks only
                      collect raw readings and always report Safe. Jump-
                      rejection (below) needs an initial trusted reference
                      before it can protect anything, and a single sample
                      is just as fault-prone as any other reading - so the
                      reference is seeded from the ROBUST MEDIAN of a
                      larger batch instead of trusting one value. Needs a
                      majority of that batch to be bad to get corrupted,
                      unlike a single-sample bootstrap. See progress.md.
      0b. Warm up    - the next median_window ticks fill the median
                      filter's buffer (now WITH jump-rejection active,
                      protected by the bootstrap reference) and still
                      always report Safe. Real MQ sensors also need
                      physical settling time before their reading means
                      anything - see PREHEAT_SECONDS in config.py.
      1. Calibrate  - raw sensor value -> PPM (pipeline/calibration.py)
      2. Reject     - a single-tick jump too large to be a real reading
                      (dropout or spike, judged BOTH relative to the
                      danger threshold and relative to the recent
                      reading itself - a near-total drop can be tiny
                      next to a far-away threshold but still implausible,
                      see RELATIVE_DROP_FRACTION in config.py) is treated
                      as a fault and replaced with the last known-good
                      value, so a cluster of faults can't drag the median
                      off course. If the same new value keeps showing up
                      for long enough, it stops looking like a glitch and
                      gets accepted as a genuine change instead - a real
                      reading is never permanently locked out.
      3. Smooth     - median filter strips any remaining spikes/dropouts
      4. Normalize  - PPM -> % of THIS gas's own critical threshold, so
                      every gas can share the same rate-of-rise limit
      5. Safety floor - if the raw reading is already at/over threshold,
                      that's Critical, immediately, no matter what
                      anything downstream thinks. Nothing can delay this.
      6. Trend      - is it rising, and how fast (pipeline/trend.py)
      7. Confirm    - require several ticks of agreement before the
                      status actually changes (pipeline/hysteresis.py)
    """

    def __init__(
        self,
        threshold: float,
        gas_name: str = "Gas",
        median_window: int = config.MEDIAN_WINDOW,
        a_calibration: float = 1.0,
        b_calibration: float = 1.0,
        max_ppm: float = 10000.0,
        max_jump_fraction: float = config.MAX_JUMP_FRACTION_OF_THRESHOLD,
        jump_accept_after_ticks: int = config.JUMP_ACCEPT_AFTER_TICKS,
        reference_bootstrap_samples: int = config.REFERENCE_BOOTSTRAP_SAMPLES,
        heater_cycle: MQ7HeaterCycle = None,
    ):
        self.threshold = threshold
        self.gas_name = gas_name
        self.median_window = median_window
        self.converter = ADCConverter(a=a_calibration, b=b_calibration, max_ppm=max_ppm)
        self.filter = MovingMedianFilter(window_size=median_window)
        self.trend = TrendDetector()
        self.confirm = StatusConfirmation()
        self.max_jump_fraction = max_jump_fraction
        self.jump_accept_after_ticks = jump_accept_after_ticks
        self.reference_bootstrap_samples = reference_bootstrap_samples
        self.heater_cycle = heater_cycle
        self._last_good_ppm = None
        self._pending_ppm = None
        self._pending_streak = 0
        self._ticks_seen = 0
        self._bootstrap_samples = []
        self._last_result = None
        self._last_smoothed = None
        self._last_pct = None
        self._peak_pct_since_safe = 0.0
        self._real_ticks_since_hold = self.median_window  # no hold yet
        self._eta_window = collections.deque()  # recent (timestamp, pct) of REAL readings, for the ETA fit

    def _is_implausible(self, ppm: float) -> bool:
        max_jump = self.max_jump_fraction * self.threshold
        if abs(ppm - self._last_good_ppm) > max_jump:
            return True
        # Also catch a near-total drop relative to the recent reading
        # itself, even when that's small next to a much larger threshold
        # (e.g. a dropout-to-zero on a gas whose baseline sits well below
        # its danger threshold) - see RELATIVE_DROP_FRACTION in config.py.
        if self._last_good_ppm > 0 and ppm < self._last_good_ppm * config.RELATIVE_DROP_FRACTION:
            return True
        return False

    def _reject_implausible_jump(self, ppm: float) -> float:
        max_jump = self.max_jump_fraction * self.threshold

        if not self._is_implausible(ppm):
            self._last_good_ppm = ppm
            self._pending_ppm = None
            self._pending_streak = 0
            return ppm

        # Too far from the trusted value to accept outright. Track whether
        # this same new value keeps recurring - a one-off fault won't, a
        # genuine change will.
        if self._pending_ppm is not None and abs(ppm - self._pending_ppm) <= max_jump:
            self._pending_streak += 1
        else:
            self._pending_ppm = ppm
            self._pending_streak = 1

        if self._pending_streak >= self.jump_accept_after_ticks:
            # Recurred long enough to stop looking like a fault - accept it.
            self._last_good_ppm = ppm
            self._pending_ppm = None
            self._pending_streak = 0
            return ppm

        # Still unconfirmed - treat as a fault, repeat the last good value
        # instead of letting it into the median filter's window.
        return self._last_good_ppm

    def process_reading(self, raw_value: float, timestamp: float) -> dict:
        if raw_value is None or (self.heater_cycle is not None and not self.heater_cycle.is_valid_reading(timestamp)):
            # No valid measurement exists right now: mid burn-off phase
            # (MQ-7/CO), or the caller passed None (lost radio packet,
            # or hardware reporting its own heater phase). If we haven't warmed up at all yet, there's
            # nothing to hold - report Safe and wait for the first real
            # reading. Otherwise, feed the trend/confirm logic the last
            # known smoothed reading, held steady, same as any other tick.
            if self._last_smoothed is None:
                return self._result(raw_value, 0.0, 0.0, "Safe", rate=0.0, cusum=0.0,
                                     reason=f"{self.gas_name} has no valid reading yet.", held=True)
            result = self._finish(raw_value, self._last_smoothed, self._last_pct, timestamp, held=True)
            self._last_result = result
            return result

        self._ticks_seen += 1
        ppm = self.converter.to_ppm(raw_value)

        if self._ticks_seen <= self.reference_bootstrap_samples:
            # Bootstrapping: just collect raw readings, no filtering or
            # jump-rejection yet (there's no trusted reference to reject
            # against). Report the running median-so-far so a real Critical
            # reading during this window still isn't hidden entirely.
            self._bootstrap_samples.append(ppm)
            smoothed = statistics.median(self._bootstrap_samples)
            if self._ticks_seen == self.reference_bootstrap_samples:
                # Seed the jump-rejection reference from the robust median
                # of the whole batch - needs a majority of it to be bad to
                # get corrupted, unlike trusting a single raw sample.
                self._last_good_ppm = smoothed
            pct = min(smoothed / self.threshold * 100.0, 999.0)
            self._last_smoothed, self._last_pct = smoothed, pct
            result = self._result(raw_value, smoothed, pct, "Safe", rate=0.0, cusum=0.0,
                                   reason=f"{self.gas_name} establishing a reliable baseline.")
            self._last_result = result
            return result

        if self._ticks_seen <= self.reference_bootstrap_samples + self.median_window:
            # Warming up: build the median filter's buffer (with
            # jump-rejection now active, protected by the bootstrap
            # reference above), but don't trust it enough to alert on yet.
            ppm = self._reject_implausible_jump(ppm)
            smoothed = self.filter.update(ppm)
            pct = min(smoothed / self.threshold * 100.0, 999.0)
            self._last_smoothed, self._last_pct = smoothed, pct
            result = self._result(raw_value, smoothed, pct, "Safe", rate=0.0, cusum=0.0,
                                   reason=f"{self.gas_name} warming up.")
            self._last_result = result
            return result

        ppm = self._reject_implausible_jump(ppm)
        smoothed = self.filter.update(ppm)
        pct = min(smoothed / self.threshold * 100.0, 999.0)
        self._last_smoothed, self._last_pct = smoothed, pct

        result = self._finish(raw_value, smoothed, pct, timestamp)
        self._last_result = result
        return result

    def _finish(self, raw_value: float, smoothed: float, pct: float, timestamp: float, held: bool = False) -> dict:
        """Safety floor + trend + confirm, given a smoothed reading - real
        or (during MQ-7 burn-off) held steady from the last real one."""
        if smoothed >= self.threshold:
            status = self.confirm.process("Critical")
            return self._result(
                raw_value, smoothed, pct, status, rate=0.0, cusum=0.0,
                reason=f"{self.gas_name} at or above its critical level ({smoothed:.1f} ppm).", held=held,
            )

        trend = self.trend.update(pct, timestamp, held=held)
        # The ETA fit only sees readings the median filter has fully caught
        # up on: for the first few real readings after a hold its window
        # still holds pre-gap values, so its output is stale by the length
        # of the gap (measured: this alone put the CO estimate ~40 s late).
        self._real_ticks_since_hold = 0 if held else self._real_ticks_since_hold + 1
        if self._real_ticks_since_hold > self.median_window // 2:
            self._eta_window.append((timestamp, pct))
        while self._eta_window and timestamp - self._eta_window[0][0] > config.ETA_WINDOW_SEC:
            self._eta_window.popleft()
        self._peak_pct_since_safe = max(self._peak_pct_since_safe, pct)

        if trend["rising"]:
            candidate = "Imminent" if pct >= config.IMMINENT_PROXIMITY_PCT else "Early Warning"
        elif pct <= self._peak_pct_since_safe * config.DOWNGRADE_RELATIVE_DROP_FRACTION:
            # Not currently rising, AND has genuinely fallen back from its
            # recent peak - a real candidate for downgrading.
            candidate = "Safe"
        else:
            # Not rising right now, but still close to its recent peak -
            # hold the current confirmed tier rather than offering Safe as
            # a candidate purely because the derivative signals went quiet.
            candidate = self.confirm.confirmed

        status = self.confirm.process(candidate)
        if status == "Safe":
            self._peak_pct_since_safe = 0.0

        # ETA only once a rise is already CONFIRMED (Early Warning or
        # Imminent) - never from the raw/unconfirmed trend["rising"] signal.
        # This is the direct fix for the flapping bug the original
        # curve-fit ETA feature caused (see progress.md and
        # docs/superpowers/specs/2026-09-25-eta-prediction-design.md).
        eta = {"eta_minutes": None, "eta_minutes_high": None, "eta_label": None}
        if status in ("Early Warning", "Imminent"):
            eta = estimate_eta(self._eta_window)
        eta_label = eta["eta_label"]

        if status == "Safe":
            reason = f"{self.gas_name} stable at {pct:.1f}% of its critical level."
        else:
            reason = (
                f"{self.gas_name} confirmed rising at {trend['rate_pct_per_min']:.1f}% "
                f"of critical level/min, currently {pct:.1f}% of critical level."
            )
            if eta_label is not None:
                reason += f" ETA to critical: {eta_label}."

        return self._result(
            raw_value, smoothed, pct, status, trend["rate_pct_per_min"], trend["cusum"], reason,
            held=held, **eta,
        )

    @staticmethod
    def _result(raw_value, smoothed, pct, status, rate, cusum, reason, eta_minutes=None, eta_minutes_high=None,
                eta_label=None, held=False) -> dict:
        return {
            "raw_value": raw_value,
            "smoothed_value": smoothed,
            "pct_of_threshold": pct,
            "status": status,
            "rate_pct_per_min": rate,
            "cusum": cusum,
            "reason": reason,
            "eta_minutes": eta_minutes,            # earlier (conservative) end of the range
            "eta_minutes_high": eta_minutes_high,  # later end of the range
            "eta_label": eta_label,
            "held": held,  # True = no fresh reading this tick; values are the last known ones
        }
