import config


def estimate_eta(pct_of_threshold: float, rate_pct_per_min: float) -> dict:
    """
    Linear extrapolation: assumes the CURRENT smoothed rate-of-rise
    (already time-weighted and EWMA-smoothed by TrendDetector) holds
    constant. Deliberately simple - no curve-fitting, no new per-tick
    state - to avoid the bug class that got the original curve-fit-based
    ETA feature removed (see progress.md: it flip-flopped Safe<->Imminent
    six times on pure noise at 1-2% of threshold). Caller
    (PipelineCoordinator._finish) is responsible for only calling this
    once status is already confirmed Early Warning or Imminent - this
    function itself has no notion of confirmation state.

    Known, disclosed limitation (see
    docs/superpowers/specs/2026-09-25-eta-prediction-design.md): this
    assumes the rate holds constant, so it systematically OVER-predicts
    remaining time (under-estimates urgency) on an accelerating
    (exponential) rise, and is accurate on a genuinely linear one.
    """
    if rate_pct_per_min <= 0:
        return {"eta_minutes": None, "eta_label": None}

    remaining_pct = max(0.0, 100.0 - pct_of_threshold)
    eta = remaining_pct / rate_pct_per_min

    if eta > config.ETA_CAP_MINUTES:
        return {"eta_minutes": eta, "eta_label": f">{config.ETA_CAP_MINUTES:.0f} min"}
    return {"eta_minutes": eta, "eta_label": f"~{eta:.0f} min"}
