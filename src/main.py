import time
import sys
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pipeline.aggregator import MultiGasAggregator
from config import GAS_CONFIGS
from alerts.notifier import AlertNotifier

def run_multi_gas_loop():
    print("Initializing Multi-Gas Edge Node (statistical trend detection)...")

    # Initialize the aggregator with all 4 gases (H2S, CH4, CO, NH3)
    aggregator = MultiGasAggregator(configs=GAS_CONFIGS)
    notifier = AlertNotifier(location_id="Sewer-Shaft-42")

    current_status = 'Safe'

    print("Starting Infinite Multi-Gas Monitoring Loop (Press Ctrl+C to exit)\n")

    tick = 0
    next_tick_time = time.monotonic()

    try:
        while True:
            # Fixed-interval drift-corrected loop
            next_tick_time += 1.0
            tick += 1
            current_timestamp = time.time()

            # 1. Simulate reading from physical sensors (4 independent MQ sensors)
            # Normal baselines for each gas
            readings = {
                'H2S': max(0.0, 5.0 + random.uniform(-0.5, 0.5)),
                'CH4': max(0.0, 100.0 + random.uniform(-10, 10)),
                'CO': max(0.0, 10.0 + random.uniform(-2, 2)),
                'NH3': max(0.0, 2.0 + random.uniform(-0.2, 0.2))
            }

            # Simulate a leak on H2S starting at tick 40
            if tick >= 40:
                leak_amount = min(0.5 * (1.1 ** (tick - 40)), 500.0)
                readings['H2S'] += leak_amount

            # Simulate a completely different sudden spike on CH4 at tick 60
            if tick >= 60:
                readings['CH4'] += 4000.0

            # 2. Process ALL gases simultaneously
            result = aggregator.process_readings(readings, current_timestamp)
            new_status = result['master_status']

            # 3. Handle Status Changes & Alerting
            if new_status != current_status:
                trigger = result['gas_results'][result['trigger_gas']]
                reason = trigger['reason']
                if result['multi_gas_pattern']:
                    reason += f" [multiple gases rising together: {', '.join(result['contributing_gases'])}]"

                notifier.broadcast(new_status, trigger['smoothed_value'], reason)
                print(f"[{result['trigger_gas']} caused {new_status} status!]")
                current_status = new_status

            # Print a subtle heartbeat showing all gases
            print(f"Tick {tick} | H2S:{readings['H2S']:>5.1f} | CH4:{readings['CH4']:>6.1f} | CO:{readings['CO']:>4.1f} | NH3:{readings['NH3']:>4.1f} | STATUS: {new_status:<15}", end='\r')

            # 4. Sleep with drift correction
            sleep_for = next_tick_time - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)

    except KeyboardInterrupt:
        print("\n\nShutting down Multi-Gas Edge Node Pipeline")

if __name__ == "__main__":
    run_multi_gas_loop()
