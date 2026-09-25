class ADCConverter:
    """
    Converts raw MQ sensor resistance ratios (Rs/R0) into PPM concentrations
    using a standard power-law curve: PPM = a * (Rs/R0)^b.

    Parameters 'a' and 'b' must be derived from the specific sensor's datasheet
    (e.g., MQ-136 for H2S, MQ-4 for CH4).

    IMPORTANT: a=1, b=1 (the default below, and what every gas in
    config.py currently uses) is NOT a real calibration - it's a
    pass-through placeholder. Researching the actual manufacturer
    datasheets (see docs/research/mq-sensor-calibration-and-gas-detection.md,
    section 2) confirmed no datasheet supports these values: every MQ
    sensor has its own non-trivial power-law curve, and none of the four
    manufacturers publish numeric a/b - they must be fit from the
    datasheet's own Rs/R0-vs-ppm graph (read off 2-3 points and
    regress) or from real calibration-gas exposures once hardware
    exists. Concretely, for MQ-136 (H2S) at a REAL 50ppm exposure, the
    datasheet's own spec (Rs(air)/Rs(50ppm) >= 3) implies Rs/R0 ~= 0.33 -
    with a=b=1 this code would report ~0.33 "ppm" for an actual 50ppm
    exposure, under-reporting by roughly two orders of magnitude, in the
    dangerous direction. Also note MQ-7 specifically defines its own R0
    reference as resistance in 1000ppm hydrogen, not clean air like the
    other three sensors - fitting its curve the same way as the others
    would silently use the wrong reference condition.
    """
    def __init__(self, a: float = 1.0, b: float = 1.0, max_ppm: float = 10000.0):
        # Default to pass-through if uncalibrated - see the warning above.
        self.a = a
        self.b = b
        self.max_ppm = max_ppm
        
    def to_ppm(self, rs_r0_ratio: float) -> float:
        if rs_r0_ratio <= 0:
            return 0.0
        val = self.a * (rs_r0_ratio ** self.b)
        return min(val, self.max_ppm)
