import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pipeline.coordinator import PipelineCoordinator

def visualize_dataset(csv_path: Path, threshold: float = 100.0):
    print(f"Visualizing {csv_path.name}...")
    df = pd.read_csv(csv_path)
    data_array = df['H2S_ppm'].values
    
    coordinator = PipelineCoordinator(threshold=threshold, median_window=5, short_window=10, long_window=30)
    
    smoothed_vals = []
    statuses = []
    
    for t, val in enumerate(data_array):
        result = coordinator.process_reading(val, float(t))
        smoothed_vals.append(result['smoothed_value'])
        statuses.append(result['status'])
        
    time_points = np.arange(len(data_array))
    
    # Plotting
    plt.figure(figsize=(12, 6))
    
    # 1. Background coloring based on status
    status_colors = {
        'Safe': '#e6fcef',           # light green
        'Early Warning': '#fcf4e6',  # light yellow
        'Imminent': '#fcece6',       # light orange
        'Critical': '#fce6e6'        # light red
    }
    
    for t in range(len(time_points) - 1):
        plt.axvspan(t, t+1, facecolor=status_colors[statuses[t]], alpha=0.5)
        
    # 2. Raw vs Smoothed data
    plt.scatter(time_points, data_array, color='gray', alpha=0.3, label='Raw Sensor (Noise)', s=10)
    plt.plot(time_points, smoothed_vals, color='blue', linewidth=2, label='Smoothed (Median Filter)')
    
    # 3. Threshold Line
    plt.axhline(y=threshold, color='red', linestyle='--', linewidth=2, label='Danger Threshold')
    
    plt.title(f"Pipeline Visualization: {csv_path.name}", fontsize=14)
    plt.xlabel("Time (seconds)", fontsize=12)
    plt.ylabel("Gas Concentration (PPM)", fontsize=12)
    plt.ylim(0, min(np.max(data_array) * 1.1, threshold * 2.0)) # Cap the Y axis
    
    # Add a custom legend to show what colors mean
    import matplotlib.patches as mpatches
    handles, labels = plt.gca().get_legend_handles_labels()
    handles.append(mpatches.Patch(color='#e6fcef', label='Status: Safe'))
    handles.append(mpatches.Patch(color='#fcf4e6', label='Status: Early Warning'))
    handles.append(mpatches.Patch(color='#fcece6', label='Status: Imminent'))
    handles.append(mpatches.Patch(color='#fce6e6', label='Status: Critical'))
    plt.legend(handles=handles, loc="upper left")
    
    output_dir = Path(__file__).parent.parent / "docs"
    output_dir.mkdir(exist_ok=True)
    out_path = output_dir / f"{csv_path.stem}_plot.png"
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    
    print(f"Saved plot to {out_path}")

if __name__ == '__main__':
    data_dir = Path(__file__).parent.parent / "data" / "synthetic"
    visualize_dataset(data_dir / "slow_leak.csv")
    visualize_dataset(data_dir / "fast_leak.csv")
    visualize_dataset(data_dir / "sensor_fault.csv")
