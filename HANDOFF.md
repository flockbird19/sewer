# Handoff: Sewer Gas Prediction — Detection Pipeline

**Read `progress.md` first** — it's the living, detailed technical log (architecture,
every bug found/fixed with root causes, known limitations, file map, how to run). This
document is a higher-level handoff for picking the work back up; `progress.md` is the
source of truth for details and must stay in sync with the code.

## Goal

Build the software prediction/detection pipeline for a university URF project: an
early-warning system for toxic gas (H2S, CH4, CO, NH3) in underground sewer manholes,
using MQ-series gas sensors on an ESP32, eventually feeding a Raspberry Pi gateway over
LoRa. **Hardware, LoRa, the gateway, and the dashboard are explicitly out of scope right
now** — URF funding was approved but not yet received, so this work is 100% software,
tested entirely on synthetic data, with no physical sensors yet.

The deliverable is a real-time **statistical process control** detector (EWMA trend
tracking + CUSUM change-point detection + confirmation-gated alerts) — deliberately NOT
a trained ML model, since no real hazardous-gas training data exists or could safely be
collected. This was a considered decision, not a shortcut; see `progress.md` → "What
this actually is" for the full reasoning, and note the important finding that this SPC
approach has **no precedent in real commercial gas detectors** (they all use simple
threshold + STEL/TWA alarms) — present it as a novel, experimental design choice in any
report/paper, not established practice.

## Current Progress

The pipeline was **completely rebuilt this session**, replacing an earlier curve-fitting
approach (`scipy.optimize.curve_fit` predicting exact crossing times) that was measurably
flappy — it produced false alarms while readings were at 1–2% of the danger threshold.

Current architecture (see `progress.md` → "Architecture" for the full diagram):
heater-cycle gate (CO only) → calibrate → bootstrap (robust reference) → warm-up →
jump-rejection (with a persistence safety-valve) → median smoothing → normalize to %-of-
threshold → safety-floor Critical check → EWMA/CUSUM trend detection → confirmation
(N ticks must agree, both up and down) → per-gas result → multi-gas fusion aggregator.

**Verified state as of last commit-worthy point:** 0 false alarms and 0 severity-flapping
regressions across an 800-seed × 4-gas × 4-scenario stress sweep (12,800 trials, ~3.8M
ticks). Critical fires within 10s of the true crossing for H2S/CH4/NH3, within 70s for CO
(a real, explained consequence of its heater-cycle blind window, not a bug).

**Research completed this session:** a background agent researched primary sources (real
MQ-136/MQ-4/MQ-7/MQ-137 datasheets, real commercial confined-space detector manuals,
published sewer-IoT literature) and wrote fully-cited findings to
`docs/research/mq-sensor-calibration-and-gas-detection.md`. That research directly drove
several of the bug fixes below (most importantly: MQ-7 doesn't sample continuously —
it needs a mandatory heater duty cycle).

**11 real bugs were found and fixed this session, each via actual large-scale randomized
testing** (not reasoning alone) — full list with root causes in `progress.md` → "Bugs
found and fixed this session". Skim that list before touching the trend/coordinator logic
again; several of these are non-obvious and easy to accidentally reintroduce.

**Not yet committed to git.** Working tree has substantial modified/added/deleted files.
Check `git status` before doing anything destructive.

## What Worked

- **Statistical process control (EWMA + CUSUM + confirmation) over curve-fitting.**
  Simpler, cheaper (O(1) per tick, no `scipy`), and measurably more robust than the old
  exact-time-prediction approach.
- **Value-based downgrade rule, not just derivative-based.** The single most important
  correctness fix: a downgrade is only offered once the level has actually fallen back to
  70% of its recent peak — not just when the rate/CUSUM signals go quiet. This eliminated
  the last of the flapping bugs. Lesson: for a rising-hazard detector, "is it rising"
  (derivative-based) and "should we stand down" (level-based) are different questions —
  don't let one mechanism answer both.
- **Testing at real scale, not just a handful of seeds.** Bugs 6, 8, 9, 10, and 11 (see
  `progress.md`) were ONLY found because of 300–800 seed stress sweeps. Smaller sanity
  runs (tens of seeds) missed every one of them. When touching this pipeline again, verify
  with hundreds of seeds, not a quick smoke test.
- **Tracing exact failures with a fixed random seed**, rather than guessing at a constant
  to nudge. Every bug fix in `progress.md` has a concrete reproduction, not a guess.
- **Deep research against primary sources (via a background agent) before trusting
  assumptions.** Several "obviously reasonable" software assumptions (5-second warm-up,
  1Hz continuous sampling for every gas, a=1/b=1 calibration) turned out to be wrong by
  orders of magnitude once checked against the actual datasheets.
- **Delegating heavy/slow verification (large stress sweeps) to background bash
  processes** while continuing other work, then confirming results via the completion
  notification rather than guessing at timing.

## What Didn't Work

- **Freezing all pipeline state during MQ-7's burn-off phase.** First attempt at the
  heater-cycle fix just froze everything during burn-off and resumed after — this left a
  60+ second gap that corrupted the EWMA trend state on resume (even with time-weighted
  alpha). Fix: hold the last known SMOOTHED reading and keep feeding it through
  trend/confirm as "unchanged" every tick, rather than freezing.
- **Trusting a single raw sample as the jump-rejection bootstrap reference.** Vulnerable
  to a ~5% chance the very first reading is itself a fault, which then poisons everything
  after it. Fix: bootstrap from the robust median of an 11-sample batch instead.
- **A threshold-relative-only fault filter.** Rejecting jumps only relative to the (often
  huge) danger threshold missed dropout faults on gases whose normal baseline sits far
  below their threshold (e.g., CH4 baseline ~500 vs. threshold 50,000 — a drop to 0 is
  only 1% of threshold, invisible to that filter). Fix: also reject drops relative to the
  recent reading itself, not just relative to the threshold.
- **A single-signal "is it rising" trigger.** Early version only used rate-of-rise; testing
  showed this alone was too noisy (a derivative amplifies noise). Needed THREE
  independent, differently-computed signals (rate EWMA, CUSUM, and "elevated above
  baseline") before it was robust — and even then, needed the value-based downgrade rule
  on top (see "What Worked").
- **Assuming a fix was done after it passed a small test run.** Multiple fixes this
  session looked correct at ~5–8 test runs and then failed at 300+ seeds. Don't declare a
  detection-logic fix verified without a real stress sweep.
- **Using the `Agent` tool with an agent ID as the prompt to "continue" a background
  agent.** This just starts an unrelated new agent — use `SendMessage` to actually resume
  one. (Caused one wasted, harmless agent spawn this session.)
- **Publishing files into a `worktree`-isolated agent's `docs/` output when `docs/` is
  gitignored.** The worktree auto-cleans once git sees "no tracked changes," which can
  delete the file before it's copied out. Recovered by asking the agent to repaste its
  content directly, but better to have the agent write somewhere non-gitignored, or copy
  the file out immediately/synchronously.

## Next Steps

From `progress.md` → "Known limitations" and the research doc's priority list, roughly in
order of importance:

1. **Decide what to do about the missing O2 sensor.** CH4's calibration is
   documented-invalid below 18% O2, and O2 depletion is itself a plausible confined-space
   hazard the current 4-gas BOM doesn't cover. This may be a BOM/proposal-level decision
   for the user, not just a code fix.
2. **Humidity/temperature compensation is unimplemented**, and per the research, no MQ
   datasheet's tested range even reaches sewer-level (~100% RH) — so this remains an
   extrapolation even once built. Lower priority than #1 since it needs digitized
   datasheet curves that don't exist in structured form yet.
3. **Cross-sensitivity correction between the four gas channels** — each sensor's own
   datasheet documents real cross-response to the others' target gases. Not yet modeled.
4. **A periodic recalibration/bump-test plan** for the eventual real deployment, given
   documented ~25–40%/year real sensor drift. This is more of an operational-plan/report
   item than a code item right now.
5. **Real calibration coefficients (`a`, `b` in `config.py`)** remain placeholders
   (1.0/1.0) — genuinely blocked on either digitizing the datasheets' own Rs/R0-vs-ppm
   graphs or real bench calibration once hardware arrives. Don't invent plausible-looking
   numbers without one of those two.
6. **Cheap, not-yet-done cleanup** (low priority, explicitly deferred each time so far):
   `README.md` and `requirements.txt` are still tracked-but-empty; `notebooks/explore.ipynb`
   is still a tracked, 0-byte, invalid file; the packaged console entry point
   (`sewer-gas-prediction` command) still prints a placeholder instead of running the real
   pipeline.
7. **Nothing is committed yet.** Once the user reviews the current state, it needs a
   commit (and the user should decide the message/scope — this session made 11 distinct
   bug fixes plus a full architecture rewrite, so consider whether that's one commit or
   several logical ones).
8. **Hardware work remains entirely out of scope** until funding/hardware arrives — don't
   start on ESP32 firmware, LoRa, the gateway, or the dashboard without the user
   explicitly reopening that scope.

To resume, a fresh session should: read `progress.md` in full, skim
`docs/research/mq-sensor-calibration-and-gas-detection.md` for the primary-source
findings, run `python tests/test_pipeline.py` and `python tests/test_detection_quality.py`
to confirm the current state still passes, then pick up at whichever "Next Steps" item the
user wants to prioritize.
