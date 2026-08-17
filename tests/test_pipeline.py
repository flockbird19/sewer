import sys
import numpy as np
from pathlib import Path

# Add src to path so we can import pipeline directly
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pipeline.coordinator import PipelineCoordinator

def test_pipeline_coordinator():
    print("--- Testing PipelineCoordinator (Tiered Alerts) ---")
    
    threshold = 100.0
    coordinator = PipelineCoordinator(threshold=threshold, median_window=3, short_window=3, long_window=10)
    
    # We will feed in data that rises exponentially. 
    # At first it should be 'Safe', then cross into 'Early Warning', then 'Imminent', then 'Critical'
    # y = 1.0 * e^(0.1 * t) + 5
    
    time_points = np.arange(50)
    base_data = 1.0 * np.exp(0.1 * time_points) + 5.0
    
    # Add a single massive fault to ensure the median filter is working inside the coordinator
    raw_data = base_data.copy()
    raw_data[15] = 999.0
    
    print(f"{'Time':<5} | {'Raw':<6} | {'Smoothed':<8} | {'Status':<15} | {'Sec to Thresh'}")
    print("-" * 60)
    
    for t, val in enumerate(raw_data):
        result = coordinator.process_reading(val, float(t))
        
        status = result['status']
        smoothed = result['smoothed_value']
        tts = result['time_to_threshold_sec']
        tts_str = f"{tts:.1f}" if tts is not None else "N/A"
        
        # Only print every 5th tick to save space, but print the fault tick explicitly
        if t % 5 == 0 or t == 15 or status != 'Safe':
            print(f"{t:<5} | {val:<6.1f} | {smoothed:<8.1f} | {status:<15} | {tts_str}")

if __name__ == '__main__':
    test_pipeline_coordinator()
