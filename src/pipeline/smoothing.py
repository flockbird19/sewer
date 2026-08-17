import collections
import numpy as np

class MovingMedianFilter:
    """
    A stateful moving median filter designed for real-time streaming data.
    It maintains a sliding window of recent readings and outputs the median,
    which effectively strips out sudden spikes or dropouts (sensor faults)
    and smooths Gaussian noise.
    """
    def __init__(self, window_size: int = 5):
        if window_size < 1:
            raise ValueError("Window size must be at least 1")
        self.window_size = window_size
        self.buffer = collections.deque(maxlen=window_size)
        
    def update(self, value: float) -> float:
        """
        Adds a new value to the buffer and returns the current median.
        """
        self.buffer.append(value)
        return float(np.median(self.buffer))
