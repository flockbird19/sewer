import numpy as np
import pandas as pd
from pathlib import Path

# Baseline configurations for each gas based on typical atmospheric/safe levels
# noise_std represents the Gaussian noise (jitter) from the sensors
GAS_CONFIG = {
    'H2S': {'baseline': 0.5, 'noise_std': 0.1, 'threshold': 100},   # ppm (MQ-136)
    'CH4': {'baseline': 500, 'noise_std': 50, 'threshold': 50000},  # ppm (MQ-4)
    'CO':  {'baseline': 2.0, 'noise_std': 0.5, 'threshold': 1200},  # ppm (MQ-7)
    'NH3': {'baseline': 1.0, 'noise_std': 0.2, 'threshold': 300},   # ppm (MQ-137)
}

def generate_gas_data(scenario, duration_sec=600, gas='H2S'):
    """
    Generates a synthetic time-series numpy array of ppm values for a given scenario.
    """
    cfg = GAS_CONFIG[gas]
    base = cfg['baseline']
    
    # 1. Base Gaussian noise (simulating sensor jitter)
    noise = np.random.normal(0, cfg['noise_std'], duration_sec)
    t = np.arange(duration_sec)
    
    if scenario == 'baseline':
        data = base + noise
        
    elif scenario == 'slow_leak':
        # Linear rise: reaches 1.2x the threshold by the end of the duration
        slope = (cfg['threshold'] * 1.2) / duration_sec 
        data = base + (slope * t) + noise
        
    elif scenario == 'fast_leak':
        # Exponential rise: simulates a sudden rupture, hits threshold rapidly
        # We calculate the growth rate so it hits threshold at 80% of the duration
        target_t = duration_sec * 0.8
        growth_rate = np.log(cfg['threshold'] / max(base, 0.1)) / target_t
        data = base * np.exp(growth_rate * t) + noise
        
    elif scenario == 'sensor_fault':
        data = base + noise
        # Inject random dropouts (to 0) and extreme spikes (2x threshold) on 5% of readings
        fault_indices = np.random.choice(duration_sec, size=int(duration_sec * 0.05), replace=False)
        for idx in fault_indices:
            if np.random.rand() > 0.5:
                data[idx] = 0
            else:
                data[idx] = cfg['threshold'] * 2
                
    else:
        raise ValueError(f"Unknown scenario: {scenario}")
        
    # Sensors cannot output negative PPM
    return np.clip(data, 0, None)


def generate_and_save_all_scenarios(output_dir="data/synthetic"):
    """
    Generates all 4 scenarios (combining all 4 gases) and saves them as CSV files.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True) # Automatically creates data/synthetic
    
    scenarios = ['baseline', 'slow_leak', 'fast_leak', 'sensor_fault']
    duration = 600  # 10 minutes of data at 1 reading/sec
    
    for scenario in scenarios:
        # Initialize DataFrame with a time column
        df = pd.DataFrame({'timestamp_sec': np.arange(duration)})
        
        # Populate each gas column
        for gas in GAS_CONFIG.keys():
            df[f"{gas}_ppm"] = generate_gas_data(scenario, duration, gas)
            
        csv_path = out_path / f"{scenario}.csv"
        df.to_csv(csv_path, index=False)
        print(f"Generated: {csv_path}")


def live_stream_generator(scenario, gas='H2S'):
    """
    A Python generator (yield) to simulate live streaming data for the prediction pipeline.
    """
    cfg = GAS_CONFIG[gas]
    t = 0
    
    while True:
        base = cfg['baseline']
        noise = np.random.normal(0, cfg['noise_std'])
        
        if scenario == 'baseline':
            val = base + noise
            
        elif scenario == 'slow_leak':
            slope = (cfg['threshold'] * 1.2) / 600 
            val = base + (slope * t) + noise
            
        elif scenario == 'fast_leak':
            growth_rate = np.log(cfg['threshold'] / max(base, 0.1)) / 480
            val = base * np.exp(growth_rate * t) + noise
            
        elif scenario == 'sensor_fault':
            val = base + noise
            if np.random.rand() < 0.05: # 5% chance of a fault on this specific reading
                val = 0 if np.random.rand() > 0.5 else cfg['threshold'] * 2
        
        yield max(0, val)
        t += 1


if __name__ == "__main__":
    print("Generating synthetic gas datasets...")
    generate_and_save_all_scenarios()
    print("Done. Ready for pipeline testing.")
