from pipeline.threshold import ThresholdConfig

# Global pipeline constants
MEDIAN_WINDOW = 5
SHORT_WINDOW = 10
LONG_WINDOW = 30
HYSTERESIS_DOWNGRADE = 5
MAX_LATCH_TICKS = 60

# Specific Gas Thresholds & Calibration Constants
# NOTE: 'a' and 'b' calibration coefficients need to be measured/calculated 
# for each specific MQ sensor when hardware arrives.
GAS_CONFIGS = {
    "H2S": ThresholdConfig(gas_name="Hydrogen Sulfide", critical_ppm=100.0, a_calibration=1.0, b_calibration=1.0, max_ppm=5000.0),
    "CH4": ThresholdConfig(gas_name="Methane", critical_ppm=5000.0, a_calibration=1.0, b_calibration=1.0, max_ppm=50000.0),
    "CO":  ThresholdConfig(gas_name="Carbon Monoxide", critical_ppm=200.0, a_calibration=1.0, b_calibration=1.0, max_ppm=10000.0),
    "NH3": ThresholdConfig(gas_name="Ammonia", critical_ppm=50.0, a_calibration=1.0, b_calibration=1.0, max_ppm=5000.0)
}
