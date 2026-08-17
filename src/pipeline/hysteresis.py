class StatusHysteresis:
    """
    Prevents status thrashing by requiring N consecutive safe readings 
    before downgrading an alert, while upgrading instantly.
    Includes a max_latch_ticks safeguard to prevent permanent deadlocks
    if the signal continuously oscillates right on the boundary.
    """
    def __init__(self, downgrade_threshold: int = 5, max_latch_ticks: int = 60):
        self.downgrade_threshold = downgrade_threshold
        self.max_latch_ticks = max_latch_ticks
        self.consecutive_lower_count = 0
        self.ticks_since_upgrade = 0
        self.current_latched_status = 'Safe'
        
        # Severity ordering
        self.severity = {
            'Safe': 0,
            'Early Warning': 1,
            'Imminent': 2,
            'Critical': 3
        }

    def process(self, predicted_status: str) -> str:
        pred_sev = self.severity[predicted_status]
        latched_sev = self.severity[self.current_latched_status]
        
        self.ticks_since_upgrade += 1
        
        if pred_sev > latched_sev:
            # Upgrade immediately
            self.current_latched_status = predicted_status
            self.consecutive_lower_count = 0
            self.ticks_since_upgrade = 0
        elif pred_sev < latched_sev:
            # Downgrade requires hysteresis
            self.consecutive_lower_count += 1
            
            if self.consecutive_lower_count >= self.downgrade_threshold:
                self.current_latched_status = predicted_status
                self.consecutive_lower_count = 0
                self.ticks_since_upgrade = 0
            elif self.ticks_since_upgrade >= self.max_latch_ticks:
                # Force downgrade if stuck for too long without seeing the higher state
                self.current_latched_status = predicted_status
                self.consecutive_lower_count = 0
                self.ticks_since_upgrade = 0
        else:
            # Same status (meaning we are confirming the higher latched state)
            self.consecutive_lower_count = 0
            self.ticks_since_upgrade = 0
            
        return self.current_latched_status
