import config

SEVERITY = {"Safe": 0, "Early Warning": 1, "Imminent": 2, "Critical": 3}


class StatusConfirmation:
    """
    Requires several consecutive ticks to agree before the confirmed status
    changes in EITHER direction - up or down.

    The old version only gated downgrades; an upgrade fired instantly off
    a single sample. That's what caused the measured flapping bug: one
    lucky-looking noisy tick was enough to fire "Imminent" at 1-2% of the
    real danger level, then a few ticks later it got walked back down,
    then fired again. Requiring a few ticks to agree before an upgrade
    fires kills that, at the cost of a few seconds of extra delay before a
    real alert - a trade worth making for a system that has to be trusted.

    The one exception, by design: 'Critical' (an already-dangerous raw
    reading) always wins instantly, with no confirmation delay. That
    decision is made one layer up (PipelineCoordinator), before this class
    ever sees it - this class just latches onto it and resets its state.
    """

    def __init__(
        self,
        confirm_up: int = config.CONFIRM_TICKS_UP,
        confirm_down: int = config.CONFIRM_TICKS_DOWN,
        max_latch_ticks: int = config.MAX_LATCH_TICKS,
    ):
        self.confirm_up = confirm_up
        self.confirm_down = confirm_down
        self.max_latch_ticks = max_latch_ticks

        self.confirmed = "Safe"
        self._streak_tier = None
        self._streak_count = 0
        self._ticks_since_change = 0

    def process(self, candidate: str) -> str:
        if candidate == "Critical":
            self._latch("Critical")
            return self.confirmed

        self._ticks_since_change += 1

        if candidate == self.confirmed:
            # Candidate agrees with where we already are - nothing pending.
            self._streak_tier = None
            self._streak_count = 0
            self._ticks_since_change = 0
            return self.confirmed

        if candidate == self._streak_tier:
            self._streak_count += 1
        else:
            self._streak_tier = candidate
            self._streak_count = 1

        going_up = SEVERITY[candidate] > SEVERITY[self.confirmed]
        needed = self.confirm_up if going_up else self.confirm_down

        # Safety valve: if we're stuck above Safe for a very long time
        # without ever seeing enough consecutive calm ticks to confirm a
        # downgrade (e.g. a signal oscillating right at the boundary),
        # force it down anyway rather than latching forever.
        forced_downgrade = (not going_up) and self._ticks_since_change >= self.max_latch_ticks

        if self._streak_count >= needed or forced_downgrade:
            self._latch(candidate)

        return self.confirmed

    def _latch(self, status: str) -> None:
        self.confirmed = status
        self._streak_tier = None
        self._streak_count = 0
        self._ticks_since_change = 0
