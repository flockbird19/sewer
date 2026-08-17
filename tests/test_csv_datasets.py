import sys
import pandas as pd
import numpy as np
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pipeline.coordinator import PipelineCoordinator

def run_validation_on_array(name: str, data_array: np.ndarray, threshold: float):
    print(f"\n{'='*65}")
    print(f"Validating Dataset: {name}")
    print(f"Total Rows: {len(data_array)} | Threshold: {threshold:.2f}")
    print(f"{'='*65}")
    
    coordinator = PipelineCoordinator(threshold=threshold, median_window=5, short_window=10, long_window=30)
    
    current_status = 'Safe'
    status_changes = []
    
    for t, val in enumerate(data_array):
        result = coordinator.process_reading(val, float(t))
        new_status = result['status']
        
        if new_status != current_status:
            status_changes.append((t, current_status, new_status, result['time_to_threshold_sec'], result.get('smoothed_value', val)))
            current_status = new_status
            
    # Print summary table of state changes
    if not status_changes:
        print("Result: STABLE. Pipeline stayed 'Safe' for the entire duration.")
    else:
        print(f"{'Time (sec)':<12} | {'Old Status':<15} | {'New Status':<15} | {'Sec to Thresh':<15} | {'Reading'}")
        print("-" * 80)
        for change in status_changes:
            t, old_s, new_s, tts, reading = change
            tts_str = f"{tts:.1f}" if tts is not None else "N/A"
            print(f"{t:<12} | {old_s:<15} | {new_s:<15} | {tts_str:<15} | {reading:.2f}")
            
    print(f"{'='*65}\n")

def test_synthetic_datasets():
    data_dir = Path(__file__).parent.parent / "data" / "synthetic"
    
    # H2S Threshold based on synthetic config
    h2s_threshold = 100.0
    
    for csv_file in sorted(data_dir.glob("*.csv")):
        df = pd.read_csv(csv_file)
        if 'H2S_ppm' in df.columns:
            run_validation_on_array(f"Synthetic: {csv_file.name}", df['H2S_ppm'].values, h2s_threshold)

def test_reference_dataset():
    ref_file = Path(__file__).parent.parent / "data" / "reference" / "Dataset" / "batch1.dat"
    
    if not ref_file.exists():
        print("Reference dataset batch1.dat not found.")
        return
        
    print(f"Parsing UCI Reference Dataset: {ref_file.name}...")
    # Parse feature 1 from libsvm style dat file
    feature_1_values = []
    with open(ref_file, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) > 1:
                # Format: 1 1:15596.162100 2:...
                try:
                    feat1_str = parts[1].split(':')[1]
                    feature_1_values.append(float(feat1_str))
                except:
                    pass
                
    feature_1_values = np.array(feature_1_values)
    
    # Set threshold high above the noise to ensure it doesn't trigger falsely on static messy data
    threshold = np.max(feature_1_values) * 1.2
    
    run_validation_on_array(f"UCI Reference: {ref_file.name} (Sensor 1 Resistance)", feature_1_values, threshold)

if __name__ == '__main__':
    test_synthetic_datasets()
    test_reference_dataset()
