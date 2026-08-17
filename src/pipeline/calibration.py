class ADCConverter:
    """
    Converts raw MQ sensor resistance ratios (Rs/R0) into PPM concentrations
    using a standard power-law curve: PPM = a * (Rs/R0)^b.
    
    Parameters 'a' and 'b' must be derived from the specific sensor's datasheet 
    (e.g., MQ-136 for H2S, MQ-4 for CH4).
    """
    def __init__(self, a: float = 1.0, b: float = 1.0, max_ppm: float = 10000.0):
        # Default to pass-through if uncalibrated
        self.a = a
        self.b = b
        self.max_ppm = max_ppm
        
    def to_ppm(self, rs_r0_ratio: float) -> float:
        if rs_r0_ratio <= 0:
            return 0.0
        val = self.a * (rs_r0_ratio ** self.b)
        return min(val, self.max_ppm)
