import sys
import numpy as np
from pathlib import Path

# Add src to path so we can import pipeline directly
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pipeline.smoothing import MovingMedianFilter
from pipeline.windows import DualWindowTracker
from pipeline.extrapolation import GasPredictor

def test_pipeline_components():
    print("--- Testing GasPredictor (Auto-Model Selection) ---")
    
    # Simulate an exponential rise (e.g. H2S fast leak)
    # y = 1.5 * e^(0.1 * x) + 10
    # Threshold = 100
    # True time to threshold -> 100 = 1.5 * e^(0.1 * t) + 10 => 90 / 1.5 = e^(0.1 * t) => 60 = e^(0.1 * t) => t = ln(60) / 0.1 ~ 40.94 seconds
    
    threshold = 100.0
    predictor = GasPredictor(threshold=threshold)
    
    # Generate 35 seconds of data (not yet at threshold, but enough to curve fit)
    time_points = np.arange(35)
    data = 1.5 * np.exp(0.1 * time_points) + 10.0
    
    # We will just pass the last 5 points as short window, and all 35 as long window for testing
    short_window = (time_points[-5:], data[-5:])
    long_window = (time_points, data)
    
    result = predictor.analyze(short_window, long_window)
    
    print("\n" + "="*80)
    print(f"{'Metric':<35} | {'Value'}")
    print("-" * 80)
    print(f"{'Status':<35} | {result['status']}")
    
    if result['status'] != 'Safe':
        predicted_t = len(long_window) + result['time_to_threshold_sec']
        print(f"{'Predicted Exact Time to Threshold':<35} | {predicted_t:.2f} seconds")
        print(f"{'True Time to Threshold':<35} | 40.94 seconds")
        print(f"{'Model Auto-Chosen':<35} | {result['model']}")
        print(f"{'Confidence Score (R2)':<35} | {result['r2']:.4f}")
    print("="*80 + "\n")

if __name__ == '__main__':
    test_pipeline_components()
