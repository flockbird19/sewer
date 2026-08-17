import collections
import numpy as np

class DualWindowTracker:
    """
    Maintains a short-term and long-term history of data for trend analysis.
    Useful for calculating immediate rate of change (velocity) while having
    a longer baseline to compare against.
    """
    def __init__(self, short_size: int = 5, long_size: int = 30):
        if short_size >= long_size:
            raise ValueError("short_size must be strictly less than long_size")
        if short_size < 1:
            raise ValueError("short_size must be at least 1")
            
        self.short_size = short_size
        self.long_size = long_size
        # The buffer only needs to hold up to long_size elements
        self.buffer = collections.deque(maxlen=long_size)
        
    def update(self, value: float, timestamp: float):
        """
        Pushes a new (timestamp, value) into the tracking windows.
        """
        self.buffer.append((timestamp, value))
        
    @property
    def short_window(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Returns (timestamps, values) for the short window.
        """
        data = list(self.buffer)[-self.short_size:]
        if not data:
            return np.array([]), np.array([])
        t, v = zip(*data)
        return np.array(t), np.array(v)
        
    @property
    def long_window(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Returns (timestamps, values) for the long window.
        """
        if not self.buffer:
            return np.array([]), np.array([])
        t, v = zip(*self.buffer)
        return np.array(t), np.array(v)
        
    @property
    def is_ready(self) -> bool:
        # Prevent "startup panics" by forcing the pipeline to wait until 
        # it has a full baseline of history before making any predictions.
        return len(self.buffer) == self.long_size
