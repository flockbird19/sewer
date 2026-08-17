from pipeline.smoothing import MovingMedianFilter
from pipeline.windows import DualWindowTracker
from pipeline.extrapolation import GasPredictor
from pipeline.calibration import ADCConverter
from pipeline.hysteresis import StatusHysteresis

class PipelineCoordinator:
    """
    Master controller that sequences the data flow:
    1. ADC Calibration (Rs/R0 -> PPM)
    2. Median Filtering (Noise/Spike suppression)
    3. Window Tracking (Short/Long term history)
    4. Prediction (Curve fitting & Threshold analysis)
    5. Hysteresis (Prevent alert thrashing)
    """
    def __init__(self, threshold: float, median_window: int = 5, short_window: int = 10, long_window: int = 30, a_calibration: float = 1.0, b_calibration: float = 1.0, max_ppm: float = 10000.0):
        self.threshold = threshold
        self.converter = ADCConverter(a=a_calibration, b=b_calibration, max_ppm=max_ppm) 
        self.filter = MovingMedianFilter(window_size=median_window)
        self.tracker = DualWindowTracker(short_size=short_window, long_size=long_window)
        self.predictor = GasPredictor(threshold=threshold)
        self.hysteresis = StatusHysteresis(downgrade_threshold=5)
        
    def process_reading(self, raw_value: float, timestamp: float) -> dict:
        """
        Takes a raw sensor reading and timestamp, passes it through the full pipeline,
        and returns the current hazard status and prediction metrics.
        """
        # 1. Calibrate (Raw ADC to PPM)
        ppm_value = self.converter.to_ppm(raw_value)
        
        # 2. Filter Spikes
        smoothed_value = self.filter.update(ppm_value)
        
        # 3. Update Memory Windows
        self.tracker.update(smoothed_value, timestamp)
        
        # 4. Immediate Critical Check (Overrides is_ready blindness)
        if smoothed_value >= self.threshold:
            status = 'Critical'
            final_status = self.hysteresis.process(status)
            return {
                'raw_value': raw_value,
                'smoothed_value': smoothed_value,
                'status': final_status,
                'time_to_threshold_sec': 0.0,
                'r2': None,
                'model': None
            }
            
        # 5. Guard: Wait for baseline buffer to fill up
        if not self.tracker.is_ready:
            return {
                'raw_value': raw_value,
                'smoothed_value': smoothed_value,
                'status': 'Safe', 
                'time_to_threshold_sec': None,
                'r2': None,
                'model': None
            }
            
        # 6. Predict Future
        prediction = self.predictor.analyze(self.tracker.short_window, self.tracker.long_window)
        
        # 7. Apply Hysteresis
        final_status = self.hysteresis.process(prediction['status'])
        
        prediction['raw_value'] = raw_value
        prediction['smoothed_value'] = smoothed_value
        prediction['status'] = final_status 
        
        return prediction
