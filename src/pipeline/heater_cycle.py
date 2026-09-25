import config


class MQ7HeaterCycle:
    """
    Models the MQ-7 (CO) sensor's mandatory heater duty cycle.

    Unlike the other three sensors, MQ-7 does not read continuously. Per
    the Hanwei/Winsen MQ-7 datasheet (see
    docs/research/mq-sensor-calibration-and-gas-detection.md, section 2):
    it alternates a high-voltage "burn-off" phase (5.0V, 60s - cleans other
    adsorbed gases off the sensing element) with a low-voltage phase (1.5V,
    90s) - CO is only meaningfully readable during the low-voltage phase.
    A flat 1 Hz read with no phase awareness means most samples aren't CO
    measurements at all; they're mid-burn-off.

    This was discovered by researching primary sources AFTER the rest of
    this pipeline was built on the (unverified) assumption that every gas
    reads continuously at 1 Hz - a real, concrete gap the research closed.
    """

    HIGH_PHASE_SEC = config.MQ7_HEATER_HIGH_SEC
    LOW_PHASE_SEC = config.MQ7_HEATER_LOW_SEC
    CYCLE_SEC = HIGH_PHASE_SEC + LOW_PHASE_SEC

    def __init__(self):
        self._cycle_start = None

    def is_valid_reading(self, timestamp: float) -> bool:
        """True during the low-voltage phase, when the resistance change
        actually reflects CO concentration. False during burn-off."""
        if self._cycle_start is None:
            self._cycle_start = timestamp
        elapsed = (timestamp - self._cycle_start) % self.CYCLE_SEC
        return elapsed >= self.HIGH_PHASE_SEC
