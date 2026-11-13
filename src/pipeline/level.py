import collections

import config
from pipeline.eta import estimate_eta
from pipeline.hysteresis import StatusConfirmation
from pipeline.smoothing import MovingMedianFilter


class LevelMonitor:
    """
    Sewage level from an ultrasonic sensor mounted at the top of a tank,
    looking down (JSN-SR04T). Input is the measured distance to the
    liquid surface, in cm; output is how full the tank is and an overflow
    status on the same four-step scale the gases use.

    Deliberately NOT run through the gas trend detector: a tank that is
    pumped out on a cycle rises and falls all day, so "it is rising" is
    normal here, not a warning. Level alarms are plain fill thresholds
    (config.LEVEL_*_PCT), confirmed over several readings, plus a time-
    to-overflow estimate once the level is already high.

    empty_cm: distance the sensor reads when the tank is empty (sensor to
              floor). Measure it on site - every tank differs.
    full_cm:  distance at which the tank counts as overflowing. Cannot be
              less than the sensor's blind zone (about 25 cm for the
              JSN-SR04T): closer than that it cannot measure at all.
    """

    def __init__(self, empty_cm: float, full_cm: float = config.LEVEL_SENSOR_MIN_CM):
        if not empty_cm > full_cm >= config.LEVEL_SENSOR_MIN_CM:
            raise ValueError("need empty_cm > full_cm >= the sensor's minimum range")
        self.empty_cm = empty_cm
        self.full_cm = full_cm
        self.filter = MovingMedianFilter(window_size=config.MEDIAN_WINDOW)
        self.confirm = StatusConfirmation()
        self._window = collections.deque()
        self._last = None

    def process_reading(self, distance_cm, timestamp: float) -> dict:
        # The sensor reports 0 or an out-of-range value when it gets no
        # echo. That is "no reading", not "tank empty" or "tank full".
        valid = distance_cm is not None and config.LEVEL_SENSOR_MIN_CM <= distance_cm <= config.LEVEL_SENSOR_MAX_CM
        if not valid:
            if self._last is None:
                return self._result(distance_cm, 0.0, "Safe", "Sewage level has no valid reading yet.", held=True)
            return {**self._last, "raw_value": distance_cm, "held": True}

        smoothed_cm = self.filter.update(distance_cm)
        fill = (self.empty_cm - smoothed_cm) / (self.empty_cm - self.full_cm) * 100.0
        fill = max(0.0, fill)

        if fill >= config.LEVEL_CRITICAL_PCT:
            candidate = "Critical"
        elif fill >= config.LEVEL_IMMINENT_PCT:
            candidate = "Imminent"
        elif fill >= config.LEVEL_WARNING_PCT:
            candidate = "Early Warning"
        else:
            candidate = "Safe"
        status = self.confirm.process(candidate)

        # ETA to the overflow level, reusing the gas ETA fit: it works on
        # "percent of the alarm level", so rescale fill accordingly.
        self._window.append((timestamp, fill / config.LEVEL_CRITICAL_PCT * 100.0))
        while timestamp - self._window[0][0] > config.ETA_WINDOW_SEC:
            self._window.popleft()
        eta = estimate_eta(self._window) if status in ("Early Warning", "Imminent") else {}

        if status == "Safe":
            reason = f"Sewage level at {fill:.0f}% of the tank."
        elif status == "Critical":
            reason = f"Sewage level at {fill:.0f}% of the tank: overflow."
        else:
            reason = f"Sewage level high at {fill:.0f}% of the tank."
            if eta.get("eta_label"):
                reason += f" Time to overflow: {eta['eta_label']}."
        self._last = self._result(distance_cm, fill, status, reason, eta_label=eta.get("eta_label"),
                                   eta_minutes=eta.get("eta_minutes"))
        return self._last

    @staticmethod
    def _result(raw, fill, status, reason, eta_label=None, eta_minutes=None, held=False) -> dict:
        return {"raw_value": raw, "fill_pct": fill, "status": status, "reason": reason,
                "eta_minutes": eta_minutes, "eta_label": eta_label, "held": held}
