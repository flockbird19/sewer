from dataclasses import dataclass

@dataclass
class ThresholdConfig:
    gas_name: str
    critical_ppm: float
    a_calibration: float = 1.0 # Default pass-through
    b_calibration: float = 1.0
    max_ppm: float = 10000.0
