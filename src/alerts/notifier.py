import time

class AlertNotifier:
    """
    Handles broadcasting of hazard statuses to external dashboards,
    mobile apps, or local sirens.
    """
    def __init__(self, location_id: str = "Zone-A"):
        self.location_id = location_id
        
    def broadcast(self, status: str, ppm: float, sec_to_thresh: float = None):
        """
        Simulates an MQTT or HTTP Webhook call.
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Color coding for terminal output
        colors = {
            'Safe': '\033[92m',         # Green
            'Early Warning': '\033[93m',# Yellow
            'Imminent': '\033[33m',     # Orange
            'Critical': '\033[91m'      # Red
        }
        reset = '\033[0m'
        color = colors.get(status, reset)
        
        print(f"\n{color}[{timestamp}] [NETWORK BROADCAST] Node: {self.location_id}{reset}")
        print(f"{color}STATUS: {status.upper()}{reset}")
        print(f"{color}Gas Level: {ppm:.2f} PPM{reset}")
        if sec_to_thresh is not None:
            print(f"{color}Estimated Time to Danger: {sec_to_thresh:.1f} seconds{reset}")
        print("-" * 50)
