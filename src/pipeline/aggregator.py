from typing import Dict
from pipeline.coordinator import PipelineCoordinator
from pipeline.threshold import ThresholdConfig
from pipeline.heater_cycle import MQ7HeaterCycle
import config

SEVERITY_ORDER = ["Safe", "Early Warning", "Imminent", "Critical"]


class MultiGasAggregator:
    """
    Runs every gas through its own PipelineCoordinator, then combines them.

    Worst-case-wins is the baseline rule (whichever gas is in the worst
    confirmed state sets the master status) - but on its own that's just
    N independent thresholds with a max() on top, which is exactly the
    "isolated thresholds" limitation the literature review criticized in
    other systems. On top of it, this adds one real piece of new
    information: if two or more gases are simultaneously confirmed rising,
    that is a meaningfully stronger signal than any one of them alone
    (e.g. a general atmosphere problem, not one sensor drifting) - so the
    master status is bumped one tier worse (never past Critical), and the
    response says which gases triggered it.
    """

    def __init__(self, configs: Dict[str, ThresholdConfig], level_monitor=None):
        # level_monitor: an optional pipeline.level.LevelMonitor for the
        # tank this box sits in. Level is reported alongside the gases and
        # never changes the gas master status - overflow and toxic air are
        # different hazards - but both feed the single site_status.
        self.level_monitor = level_monitor
        self.coordinators = {
            gas: PipelineCoordinator(
                threshold=cfg.critical_ppm,
                gas_name=cfg.gas_name,
                a_calibration=cfg.a_calibration,
                b_calibration=cfg.b_calibration,
                max_ppm=cfg.max_ppm,
                # MQ-7 (CO) is the only sensor here with a mandatory heater
                # duty cycle - see pipeline/heater_cycle.py.
                heater_cycle=MQ7HeaterCycle() if gas == "CO" else None,
            )
            for gas, cfg in configs.items()
        }

    def process_readings(self, readings: Dict[str, float], timestamp: float, level_cm: float = None) -> dict:
        """
        readings format: {'H2S': 4.5, 'CH4': 1000.0, ...}
        Leave a gas out entirely if its sensor is not installed. Pass
        None for a gas whose reading is missing this tick (lost packet,
        heater burn-off reported by the hardware): its last state is held.
        level_cm: ultrasonic distance to the sewage surface, if fitted.
        """
        level = self.level_monitor.process_reading(level_cm, timestamp) if self.level_monitor else None
        results = {
            gas: self.coordinators[gas].process_reading(raw_val, timestamp)
            for gas, raw_val in readings.items()
            if gas in self.coordinators
        }

        if not results:
            return {"master_status": "Safe", "trigger_gas": None, "multi_gas_pattern": False,
                    "contributing_gases": [], "gas_results": {}, "level": level,
                    "site_status": level["status"] if level else "Safe"}

        trigger_gas = max(results, key=lambda g: SEVERITY_ORDER.index(results[g]["status"]))
        master_status = results[trigger_gas]["status"]

        contributing_gases = [gas for gas, res in results.items() if res["status"] != "Safe"]
        multi_gas_pattern = False

        if len(contributing_gases) >= config.FUSION_MIN_GASES and master_status != "Critical":
            bumped_index = min(SEVERITY_ORDER.index(master_status) + 1, len(SEVERITY_ORDER) - 1)
            master_status = SEVERITY_ORDER[bumped_index]
            multi_gas_pattern = True

        return {
            "master_status": master_status,
            "trigger_gas": trigger_gas,
            "multi_gas_pattern": multi_gas_pattern,
            "contributing_gases": contributing_gases,
            "gas_results": results,
            "level": level,
            "site_status": max(master_status, level["status"] if level else "Safe", key=SEVERITY_ORDER.index),
        }
