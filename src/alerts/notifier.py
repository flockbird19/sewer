import time


class AlertNotifier:
    """
    Handles broadcasting of hazard statuses to external dashboards,
    mobile apps, or local sirens.

    NOTE: broadcast() currently just prints to the terminal - it simulates
    where an MQTT publish or HTTP webhook call would go once there's an
    actual gateway/dashboard to send to (see progress.md, that's explicitly
    out of scope until funding/hardware arrives).
    """

    def __init__(self, location_id: str = "Zone-A"):
        self.location_id = location_id

    def broadcast(self, status: str, ppm: float, reason: str = ""):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        colors = {
            "Safe": "\033[92m",          # Green
            "Early Warning": "\033[93m", # Yellow
            "Imminent": "\033[33m",      # Orange
            "Critical": "\033[91m",      # Red
        }
        reset = "\033[0m"
        color = colors.get(status, reset)

        print(f"\n{color}[{timestamp}] [NETWORK BROADCAST] Node: {self.location_id}{reset}")
        print(f"{color}STATUS: {status.upper()}{reset}")
        print(f"{color}Gas Level: {ppm:.2f} PPM{reset}")
        if reason:
            print(f"{color}Reason: {reason}{reset}")
        print("-" * 50)
