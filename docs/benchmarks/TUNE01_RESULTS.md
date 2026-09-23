# ATP 2017–2024: one registered tuning pass, then the model freeze (TUNE01)

> **Independently reconstructed (archive decision D134).** Every number on this page
> comes from the single registered scoring pass of TUNE01 attempt 001
> ([tune01.json](tune01.json)). A separate implementation reproduced the estimate, the
> interval, the annual values and the draw hashes before acceptance.

## Result

TUNE01 asked one question: does a single registered tuning pass over the incumbent's
boosted-tree head improve match-weighted log loss by at least 0.0008, with an interval
excluding zero, on all 18,972 ATP targets from 2017 to 2024? It does not. The registered
sentences, filled from the JSON:

> One registered tuning pass over the model's boosted-tree head moved log loss by −0.0000
> [−0.0004, +0.0003] against full_tier_entry on 18,972 ATP matches from 2017 to 2024,
> short of the registered −0.0008 gate. The model is frozen as full_tier_entry.
>
> Model development is closed. No further feature or learner search will be run on this
> cohort.

At full precision TUNE01 − Arm 0 is −0.0000305, with block-8 interval [−0.0003924,
+0.0003305]; 4 of 8 years are negative, 2 positive and 2 exactly zero. Log loss is 0.597521
for TUNE01 and 0.597551 for Arm 0.

**The model is frozen at `full_tier_entry`; no further feature or learner search.** The
frozen ATP model is ARMS01 attempt 002 `full_tier_entry` with the unchanged two-candidate
boosting menu, past-only selection and slope calibration
([BUILDOAK_2017_2024_RESULTS.md](BUILDOAK_2017_2024_RESULTS.md)).

## What was compared

- **Arm 0, `full_tier_entry`.** The saved ARMS01 attempt 002 forecasts, not refitted. The
  head is the two-candidate menu `hgb_leaf07_depth3` / `hgb_leaf15_depth4`: 200
  iterations, learning rate 0.05, L2 10, minimum leaf 80, 255 bins, no early stopping and
  no subsampling, on a five-year window with past-only three-year selection and one
  non-negative slope calibration.
- **TUNE01.** The same chain, bundle (57 model columns), inputs and features. Only this
  bundle's candidate menu changes, from 2 to 110 candidates:
  - the two Arm 0 candidates as anchors, fitted exactly as before, so the selector can keep
    the incumbent;
  - a 108-point grid: maximum leaves 7, 15, 23 or 31; minimum leaf 160, 80 or 40; L2 30,
    10 or 1; learning rate 0.1, 0.05 or 0.02;
  - temporal early stopping for every grid candidate: five bagged stopping fits of up to
    1,000 iterations validated on the training window's most recent year, patience 20,
    and the loss-minimising iteration count k\* kept;
  - five-member seed bagging, each member refitted with k\* iterations on 80% of the
    window, with common random numbers across candidates.

Selection and calibration are unchanged. For each target year, every candidate gets one
slope fitted on its forecasts for the three preceding years, and the lowest calibrated
equal-year loss wins. Nothing is fitted, stopped, selected or calibrated on the target
year. The registered trial budget was 110 candidates over 11 raw years (1,210
candidate-years, 11,880 bagged member fits and 22 anchor fits), 8 selections and one
scoring pass. No other candidate, window, calibration form or learner was tried.

The registration was frozen at 2026-09-23T16:00:01Z, before any TUNE01 fit on real
targets (product commit `2fed784`, `configs/chains/atp_tune01_2017_2024.json`,
`configs/menus/tune01_hgb_menu.json`). Before scoring, the stop checks passed: every
pre-model artefact, every `base` and `full_tier` forecast and every anchor raw forecast was
byte-identical to the ARMS01 attempt 002 run.

## By year

| Year | Matches | Arm 0 | TUNE01 | TUNE01 − Arm 0 | TUNE01 selected | k\* | Slope TUNE01 / Arm 0 | Arm 0 selected |
|---|---:|---:|---:|---:|---|---:|---|---|
| 2017 | 2,323 | 0.5915 | 0.5920 | +0.00045 | lr 0.05, 7 leaves, min leaf 40, L2 1 | 179 | 0.992 / 0.968 | 7 leaves |
| 2018 | 2,606 | 0.6035 | 0.6045 | +0.00106 | lr 0.05, 7 leaves, min leaf 160, L2 1 | 99 | 0.968 / 0.957 | 7 leaves |
| 2019 | 2,502 | 0.6064 | 0.6057 | −0.00072 | lr 0.1, 7 leaves, min leaf 40, L2 10 | 79 | 0.916 / 0.913 | 7 leaves |
| 2020 | 1,250 | 0.5936 | 0.5930 | −0.00060 | lr 0.1, 7 leaves, min leaf 160, L2 10 | 91 | 0.922 / 0.923 | 7 leaves |
| 2021 | 2,390 | 0.5965 | 0.5964 | −0.00010 | lr 0.1, 7 leaves, min leaf 160, L2 10 | 95 | 0.954 / 0.942 | 15 leaves |
| 2022 | 2,538 | 0.5920 | 0.5914 | −0.00063 | lr 0.1, 7 leaves, min leaf 160, L2 10 | 84 | 0.987 / 0.977 | 15 leaves |
| 2023 | 2,682 | 0.5987 | 0.5987 | 0 | anchor `hgb_leaf07_depth3` | — | 1.030 / 1.030 | 7 leaves |
| 2024 | 2,681 | 0.5956 | 0.5956 | 0 | anchor `hgb_leaf07_depth3` | — | 1.033 / 1.033 | 7 leaves |

In 2023 and 2024 the selector kept the incumbent anchor, so those TUNE01 forecast files are
byte-identical to Arm 0. In every other year every forecast differs. Every grid candidate in
every raw year stopped on patience; none reached the 1,000-iteration cap (1,188 patience
stops). Selected configurations, slopes and k\* come from the run's past-only selection
records; they are descriptive, never a gate.

## The contrast

| Contrast | Matches | Difference | Years negative | Block 8 (primary) | Block 4 | Block 13 | Equal-year mean | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| TUNE01 − Arm 0 | 18,972 | −0.0000305 | 4 of 8 | [−0.0004, +0.0003] | [−0.0004, +0.0003] | [−0.0004, +0.0003] | −0.0001 [−0.0004, +0.0002] | ≤ −0.0008 and upper bound < 0: failed |

Descriptive companions, block 8: Brier score difference −0.00004 [−0.0002, +0.0001] and
winner-accuracy difference −0.0010 [−0.0027, +0.0008].

Intervals are 95% percentile intervals from 5,000 stationary calendar-week bootstrap draws
on one inclusive Monday grid from 2017-01-02 to 2024-11-11 (411 weeks, 271 with matches),
PCG64 seed 20260923, computed by the frozen ARMS01 scorer reused unchanged. They condition
on the saved forecasts and omit refit, selection, early-stopping and bagging-seed variance.

## Power and what the null means

The registration planned an effective per-match SD of 0.076, which gives a minimum
detectable effect of 0.0015 and a 30% chance of passing the gate at a true −0.0008. The
realised effective SD was much smaller, **0.025** (week-block design effect 0.69): the two
arms share inputs, features and the selection rule, and agree exactly in 2023 and 2024.
The interval half-width is therefore about ±0.0004, and **gains of about 0.0005 or more were
detectable** (minimum detectable effect 0.0005 at 80% power). A tuned head worth that much
would most likely have shown an interval excluding zero; this one shows an estimate of
−0.00003.

What this does not show: that tuning cannot help at all. Effects below about 0.0005 are
inside this interval, and the registered menu covers learning rate, tree count with early
stopping, tree size, minimum leaf, L2 and bagging, not every learner family. The declared
exclusions (monotonic and interaction constraints, column subsampling, recency weights,
other windows, bin counts, learners, stacking, blending and calibration forms) are closed
by the freeze without having been tested.

## The model freeze

TUNE01 was registered as the last model-development experiment on this cohort (archive
decision D130, Phase 3). With the gate failed, archive decision D134 froze the ATP model:

- **Frozen model:** `full_tier_entry` from ARMS01 attempt 002 (`full_tier` plus nine
  entry-status and tournament-level columns, the any-qualifier flag counting Q only), with
  the two-candidate boosting menu, five-year window, past-only three-year selection and one
  non-negative slope calibration. Chain configuration
  `configs/chains/atp_arms01_attempt002_2017_2024.json`; the eight 2017–2024 selected
  forecast hashes are in [tune01.json](tune01.json) under `frozen_model`.
- **Closed:** any new experiment, registered or exploratory, on ATP outcomes that changes
  or selects among features or feature blocks, learner families, hyperparameters or menus,
  training windows, weighting, selection rules, calibration forms, bagging, stacking or
  blending, and any screen on saved forecasts that proposes such a change.
- **Still permitted:** annual refits of the frozen procedure on new data; bug fixes
  recorded as defects and rerun as new attempts against the frozen hashes; source
  maintenance that does not change the procedure; prospective evaluation; a WTA analogue
  under its own single-pass registration; the market study; publication.
- **Reopens when:** a new data source outside the public record is acquired and
  registered, a defect in the frozen model is demonstrated, or the owner lifts the freeze.

The review behind this rule estimated that the remaining 0.010 log-loss gap to the
Pinnacle closing price is information the public record does not contain, so a further
model search on the same inputs is the wrong lever.

## Verification and limits

After scoring, an independent reconstruction reproduced the result with separate code
(`references/TUNE01/reconstruction/attempt_001/RECONSTRUCTION.md`, verdict ACCEPT): the
membership rebuilt byte-identical, all 16 bound forecast files rehashed identical, the
Arm 0 files equal to the ARMS01 attempt 002 Arm 1 files, the point estimate, interval,
annual values and log-loss draw hashes identical, and the 2023 and 2024 TUNE01 files
byte-identical to Arm 0. The only differences were Brier draw hashes, and the joint hashes
that include them, from a known last-bit arithmetic class; the Brier intervals agree to
1e-19. Archive decision D134
records the acceptance.

This is an exposed retrospective comparison on 2017–2024, not an untouched test or
prospective evidence. The registration was not blind: the menu was shaped by the
22 September review's audit of 2021–2023 outcomes and by the ARMS01 selection records.
No WTA analogue (TUNE01-WTA) was registered or run. No claim here extends beyond this
menu, this cohort and paired log loss.

Machine-readable aggregates, per-year selections, draw hashes, the frozen-model record and
provenance hashes: [tune01.json](tune01.json).
