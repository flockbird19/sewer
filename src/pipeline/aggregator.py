from typing import Dict
from pipeline.coordinator import PipelineCoordinator
from pipeline.threshold import ThresholdConfig

class MultiGasAggregator:
    """
    Manages multiple PipelineCoordinators for an array of sensors.
    Outputs a "Worst-Case Wins" master status.
    """
    def __init__(self, configs: Dict[str, ThresholdConfig]):
        self.coordinators = {}
        for gas, cfg in configs.items():
            coord = PipelineCoordinator(
                threshold=cfg.critical_ppm,
                a_calibration=cfg.a_calibration,
                b_calibration=cfg.b_calibration,
                max_ppm=cfg.max_ppm
            )
            self.coordinators[gas] = coord
            
        self.severity = {
            'Safe': 0,
            'Early Warning': 1,
            'Imminent': 2,
            'Critical': 3
        }

    def process_readings(self, readings: Dict[str, float], timestamp: float) -> dict:
        """
        readings format: {'H2S': 4.5, 'CH4': 1000.0, ...}
        Returns the master status, and the individual results.
        """
        results = {}
        master_status = 'Safe'
        max_sev = 0
        
        for gas, raw_val in readings.items():
            if gas in self.coordinators:
                res = self.coordinators[gas].process_reading(raw_val, timestamp)
                results[gas] = res
                
                sev = self.severity[res['status']]
                if sev > max_sev:
                    max_sev = sev
                    master_status = res['status']
                    
        return {
            'master_status': master_status,
            'gas_results': results
        }
