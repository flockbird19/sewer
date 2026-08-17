import numpy as np
from scipy.optimize import curve_fit
from sklearn.metrics import r2_score
import warnings

def linear_model(x, m, c):
    return m * x + c

def exponential_model(x, a, b, c):
    return a * np.exp(b * x) + c

class GasPredictor:
    """
    Analyzes short and long windows to predict if and when a gas will cross a critical threshold.
    It uses robust curve fitting (linear and exponential) and auto-selects the best model based on R2 score.
    Returns categorized tiered alerts based on user-defined prediction horizons.
    """
    def __init__(self, threshold: float):
        self.threshold = threshold
        
    def _determine_status(self, current_val: float, time_to_threshold_sec: float) -> str:
        if current_val >= self.threshold:
            return 'Critical'
        if time_to_threshold_sec is None:
            return 'Safe'
        if time_to_threshold_sec <= 600: # 10 mins
            return 'Imminent'
        if time_to_threshold_sec <= 1800: # 30 mins
            return 'Early Warning'
        return 'Safe'
        
    def analyze(self, short_window: tuple[np.ndarray, np.ndarray], long_window: tuple[np.ndarray, np.ndarray]):
        """
        Returns a dictionary containing the tiered status, predicted time to threshold,
        and the R2 confidence score.
        """
        t_short, v_short = short_window
        t_long, v_long = long_window
        
        # Safety checks
        if len(v_short) < 2 or len(v_long) < 3:
            return {'status': 'Safe', 'time_to_threshold_sec': None, 'r2': None, 'model': None}
            
        current_val = v_short[-1]
        
        # If already crossed threshold, early exit
        if current_val >= self.threshold:
            return {'status': 'Critical', 'time_to_threshold_sec': 0.0, 'r2': None, 'model': None}
            
        # 1. Velocity Check (Immediate slope)
        x_short = t_short - t_short[0]
        m_short, _ = np.polyfit(x_short, v_short, 1)
        
        # If gas is clearing out or flat, we are safe
        if m_short <= 0.01:
            return {'status': 'Safe', 'time_to_threshold_sec': None, 'r2': None, 'model': None}
            
        # 2. Robust Curve Fitting on long window
        x_long = t_long - t_long[0]
        best_r2 = -float('inf')
        best_model_name = None
        best_time_relative = None
        
        # Suppress curve_fit warnings if it fails to converge on bad data
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            
            # --- Try Linear Fit ---
            try:
                popt_lin, _ = curve_fit(linear_model, x_long, v_long)
                y_pred_lin = linear_model(x_long, *popt_lin)
                r2_lin = r2_score(v_long, y_pred_lin)
                
                m, c = popt_lin
                if m > 0:
                    t_lin = (self.threshold - c) / m
                    if t_lin > x_long[-1]: # Must be in the future
                        best_r2 = r2_lin
                        best_model_name = 'linear'
                        best_time_relative = t_lin
            except Exception:
                pass
                
            # --- Try Exponential Fit ---
            try:
                p0 = (max(1e-5, np.max(v_long) - np.min(v_long)), 0.05, np.min(v_long))
                popt_exp, _ = curve_fit(exponential_model, x_long, v_long, p0=p0, maxfev=2000)
                y_pred_exp = exponential_model(x_long, *popt_exp)
                r2_exp = r2_score(v_long, y_pred_exp)
                
                a, b, c = popt_exp
                if a > 0 and b > 0 and (self.threshold - c) / a > 0:
                    t_exp = np.log((self.threshold - c) / a) / b
                    if t_exp > x_long[-1]:
                        if r2_exp > best_r2:
                            best_r2 = r2_exp
                            best_model_name = 'exponential'
                            best_time_relative = t_exp
            except Exception:
                pass
                
        # 3. Final Decision
        if best_model_name and best_r2 > 0.85: 
            # Convert to 'seconds from now'
            sec_from_now = best_time_relative - x_long[-1]
            if sec_from_now > 0:
                status = self._determine_status(current_val, sec_from_now)
                return {
                    'status': status, 
                    'time_to_threshold_sec': sec_from_now, 
                    'r2': best_r2, 
                    'model': best_model_name
                }
                
        return {'status': 'Safe', 'time_to_threshold_sec': None, 'r2': None, 'model': None}
