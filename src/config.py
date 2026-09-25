import math
from pipeline.threshold import ThresholdConfig

# --- Smoothing ---
MEDIAN_WINDOW = 5  # samples; strips single-tick spikes/dropouts before anything else sees them

# --- Sensor preheat (a SEPARATE concern from the median-buffer-fill above) ---
# All four Winsen/Hanwei datasheets specify "Preheat time: Over 48 hours"
# before the sensor's published specs are considered valid - a real
# hardware requirement, not a software one, and unrelated to how many
# samples the median filter needs (see
# docs/research/mq-sensor-calibration-and-gas-detection.md, section 2).
# PREHEAT_SECONDS_DEV_MODE exists ONLY because every synthetic test
# scenario in this repo is a 600-second run - using the real 48-hour
# value as the active default would mean nothing in this codebase would
# ever leave "warming up". Flip PREHEAT_SECONDS to
# PREHEAT_SECONDS_REAL_HARDWARE for any actual deployment; don't just
# quietly keep the dev-mode value.
PREHEAT_SECONDS_REAL_HARDWARE = 48 * 3600  # 172,800s - the datasheet minimum
PREHEAT_SECONDS_DEV_MODE = 5.0             # NOT realistic - synthetic/demo use only
PREHEAT_SECONDS = PREHEAT_SECONDS_DEV_MODE

# A single fault spike is absorbed fine by the median filter alone - but
# measured testing showed that if 3+ fault spikes happen to land within one
# 5-sample window (possible by chance at a 5%-per-tick fault rate, or by a
# failing sensor faulting repeatedly), the median itself can be dragged past
# the danger threshold, firing a real false Critical alert. This rejects any
# single-tick jump bigger than this fraction of the danger threshold.
#
# IMPORTANT, per research into the actual MQ sensor datasheets (see
# docs/research/mq-sensor-calibration-and-gas-detection.md, section 2):
# the "real leaks can't rise this fast" justification this comment
# originally gave is NOT supported by the manufacturer's own data. None
# of the four datasheets publish a numeric response-time (T90) figure,
# and their response-curve graphs actually show the sensors reaching a
# plateau within seconds of a real step exposure - meaning a genuine fast,
# dangerous release plausibly CAN produce a jump this large in one second.
# This guard still earns its place against the specific, measured problem
# it was built for (clustered sensor faults defeating the median filter -
# see progress.md), but the 50% number itself is an unvalidated
# placeholder, not a physically-derived one. Re-derive it from real
# bench-tested step-response data once hardware exists (see "what to fix"
# item 6 in the research doc above).
MAX_JUMP_FRACTION_OF_THRESHOLD = 0.5

# A dropout fault (sensor briefly reads ~0) can be far smaller than 50% of
# the danger threshold in absolute terms for a gas whose normal baseline
# sits well below its threshold (e.g. CH4: baseline ~500ppm, threshold
# 50,000ppm - a drop to 0 is only 1% of threshold, so the check above
# never flags it). Testing found this let dropouts straight into the
# median filter; even though the filter absorbs them fine on their own,
# the filter's own correct recovery over the next few ticks (as the
# dropout ages out of its window) created a small, real swing in the
# smoothed value that the trend detector picked up as a genuine rise -
# a real, measured false alarm, found only via large-scale stress
# testing. This catches a near-total drop relative to the RECENT reading
# instead, regardless of how far that is from the (possibly much larger)
# danger threshold.
RELATIVE_DROP_FRACTION = 0.1  # a reading below this fraction of the last trusted value is also rejected as implausible

# Safety valve: a rejected jump is normally never trusted again, on the
# assumption it was a transient fault. But if the SAME new value keeps
# showing up, that stops looking like a glitch and starts looking like a
# genuine, permanent change the system needs to react to - a real reading
# must never be permanently ignored just because it arrived abruptly. This
# is set well above the longest fault cluster this design defends against
# (see MAX_JUMP_FRACTION_OF_THRESHOLD above), so it can't be exploited by
# the same clustered-fault attack that guard exists to stop.
JUMP_ACCEPT_AFTER_TICKS = 10

# The cold-start problem: jump-rejection needs an initial trusted
# reference before it can protect anything, but a single bootstrap sample
# carries the same ~5%-per-tick fault risk as any other reading, and the
# 5-sample median-buffer warm-up alone isn't enough margin - testing found
# a real case where 3 of the first 5 ticks happened to be faults (P ~
# 0.1% per trial at a 5%-per-tick fault rate, so rare but not negligible
# at scale), poisoning the warm-up window before jump-rejection was even
# active yet and firing a real, latched false Critical. A larger initial
# batch, reduced to its robust median before anything downstream trusts
# it, needs a MAJORITY of samples to be bad to get corrupted - far less
# likely than 3-of-5. See progress.md.
REFERENCE_BOOTSTRAP_SAMPLES = 11

# --- Trend detection (statistical process control, see pipeline/trend.py) ---
# Two EWMAs per gas: a fast one that tracks the current level, and a slow
# one that tracks the recent "normal" baseline. The gap between them is
# the trend signal - no stored history required, just two running numbers.
EWMA_FAST_ALPHA = 0.3   # ~3-tick memory: reacts quickly to a real change
EWMA_SLOW_ALPHA = 0.05  # ~20-tick memory: slow, stable "what's normal"

# The tick-to-tick rate of change of even a smoothed level is itself noisy
# (a derivative amplifies noise). Smoothing it again with its own EWMA
# stops a handful of unlucky noisy ticks from making a genuine, ongoing
# rise briefly look like it stopped - this was caught by testing: a real,
# continuously climbing signal saw its raw rate estimate dip under the
# rate limit for 5 ticks in a row by chance alone, forcing an unwarranted
# downgrade. See progress.md.
RATE_EWMA_ALPHA = 0.3

# The three ALPHA constants above assume readings arrive exactly 1 second
# apart - true for H2S/CH4/NH3, but NOT for CO, which only produces a
# valid reading during ~90s of every 150s heater cycle (see
# heater_cycle.py). Applying a fixed per-tick alpha across an irregular
# 60+ second gap would silently corrupt the trend estimate - this was
# caught by testing once the MQ-7 heater cycle was modeled. These TAU
# constants are the equivalent continuous-time time-constants (seconds),
# derived so that at exactly 1-second spacing they reproduce the ALPHA
# values above exactly; pipeline/trend.py uses them to compute the
# correct effective alpha for whatever the real elapsed time was.
EWMA_FAST_TAU_SEC = -1.0 / math.log(1 - EWMA_FAST_ALPHA)
EWMA_SLOW_TAU_SEC = -1.0 / math.log(1 - EWMA_SLOW_ALPHA)
RATE_EWMA_TAU_SEC = -1.0 / math.log(1 - RATE_EWMA_ALPHA)

# CUSUM (cumulative sum) catches a slow, steady drift that's too gentle for
# the rate-of-rise check to notice tick-to-tick, but adds up over time.
CUSUM_SLACK_PCT = 1.0    # ignore drift smaller than this (in % of critical threshold)
CUSUM_ALERT_PCT = 15.0   # accumulated drift beyond this counts as "rising"

# Both expressed as % of THIS gas's own critical threshold, not raw PPM, so
# one limit works for every gas regardless of its absolute scale (H2S danger
# is 100 ppm, CH4 danger is 5000 ppm - a shared PPM/sec limit made no sense).
RATE_LIMIT_PCT_PER_MIN = 5.0    # sustained climb faster than this counts as "rising"
IMMINENT_PROXIMITY_PCT = 50.0   # a confirmed rise already past this point is Imminent, not just Early Warning

# A real hazard doesn't stop being one just because its RATE of rise or
# CUSUM happens to look calm for a few ticks - testing found this happens
# legitimately during a slowly-decelerating-but-still-rising stretch of an
# exponential curve (the fast/slow EWMA gap can shrink to a small,
# steady-state value even while the level keeps climbing). A downgrade
# candidate is only offered once the level has actually fallen back to
# this fraction of its recent peak - not just when the derivative-based
# signals go quiet. See progress.md.
DOWNGRADE_RELATIVE_DROP_FRACTION = 0.7

# --- Confirmation (replaces instant single-sample alerts) ---
# A single noisy tick can no longer raise OR lower the alert by itself -
# only an already-dangerous raw reading (the Critical safety floor) is instant.
CONFIRM_TICKS_UP = 3     # consecutive agreeing ticks needed to raise severity
CONFIRM_TICKS_DOWN = 10   # consecutive agreeing ticks needed to lower severity
MAX_LATCH_TICKS = 60     # force a downgrade after this many ticks stuck, even without full confirmation

# --- ETA prediction ---
# A linear extrapolation of the CURRENT smoothed rate-of-rise (see
# pipeline/eta.py) - deliberately not curve-fitting, to avoid the exact bug
# class that got the original curve-fit-based ETA feature removed this
# session (see progress.md). Only computed once a rise is already
# confirmed (status Early Warning or Imminent), never from raw/unconfirmed
# trend signals. Above this many minutes, report a floor ("> N min")
# instead of a specific number - precision this far out isn't meaningful
# given the method. See docs/superpowers/specs/2026-09-25-eta-prediction-design.md.
ETA_CAP_MINUTES = 45.0

# --- Multi-gas fusion ---
FUSION_MIN_GASES = 2  # this many gases confirmed-rising at once = treat it one tier worse

# --- MQ-7 (CO) heater duty cycle ---
# Per the Hanwei/Winsen MQ-7 datasheet: CO is only readable during the
# low-voltage phase of an alternating heater cycle, not continuously like
# the other three sensors. See pipeline/heater_cycle.py and
# docs/research/mq-sensor-calibration-and-gas-detection.md (section 2).
MQ7_HEATER_HIGH_SEC = 60.0   # 5.0V burn-off phase - readings here are NOT valid CO measurements
MQ7_HEATER_LOW_SEC = 90.0    # 1.5V phase - the only window where the resistance change means CO

# --- Per-gas calibration & danger thresholds ---
# NOTE: 'a' and 'b' calibration coefficients are placeholders (pass-through)
# until real MQ sensor hardware arrives and gets calibrated against a known
# concentration (manufacturer datasheet curve, or a borrowed reference
# detector). See progress.md for the calibration plan.
#
# These critical_ppm values are the single source of truth for "dangerous"
# for every gas - the synthetic data generator imports them too, so the
# test data and the real alert thresholds can never drift apart again.
# Values are each gas's NIOSH IDLH (Immediately Dangerous to Life or Health)
# level, except CH4 which uses 5% by volume (50,000 ppm) - its Lower
# Explosive Limit, the recognized alarm point for methane since it's an
# asphyxiant/explosion risk rather than a toxicity one.
GAS_CONFIGS = {
    "H2S": ThresholdConfig(gas_name="Hydrogen Sulfide", critical_ppm=100.0, a_calibration=1.0, b_calibration=1.0, max_ppm=5000.0),
    "CH4": ThresholdConfig(gas_name="Methane", critical_ppm=50000.0, a_calibration=1.0, b_calibration=1.0, max_ppm=100000.0),
    "CO":  ThresholdConfig(gas_name="Carbon Monoxide", critical_ppm=1200.0, a_calibration=1.0, b_calibration=1.0, max_ppm=10000.0),
    "NH3": ThresholdConfig(gas_name="Ammonia", critical_ppm=300.0, a_calibration=1.0, b_calibration=1.0, max_ppm=5000.0)
}
