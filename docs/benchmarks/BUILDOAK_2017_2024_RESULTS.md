# ATP 2017–2024: BuildOak comparison, entry status and a blend (ARMS01)

> **Independently reconstructed (archive decisions D131 and D132).** Every number on
> this page comes from the single registered scoring pass of ARMS01 attempt 002
> ([buildoak_2017_2024.json](buildoak_2017_2024.json)). A separate implementation
> reproduced every registered estimate and interval before acceptance.

Extended to ATP 2017–2025 with the frozen model, as exposed retrospective data (EXT2025):
[BUILDOAK_2017_2025_RESULTS.md](BUILDOAK_2017_2025_RESULTS.md). This page stays the registered
result; nothing on it changes.

## Registered outcomes

ARMS01 fixed three gates, and the sentences that report them, before any 2017–2023
BuildOak forecast or any fit of the new rung on real targets existed. Filled from the
JSON:

- **Gate 2, public comparison: supported.** Alcaraz scores ahead of every public model we
  could run, with intervals excluding zero: the BuildOak XGBoost adaptation on 18,972 ATP
  matches from 2017 to 2024 (paired log loss −0.0070, 95% interval [−0.0100, −0.0040], 7
  of 8 years), and the Ultimate Tennis Statistics formula and the Ingram point model on
  2,681 ATP matches from 2024. Paired log loss, stationary calendar-week bootstrap.
- **Gate 1, covariate block: passed (new rung).** full_tier_entry: full_tier plus entry
  status (Q, LL, WC, PR) and tournament-level context; −0.0011 versus full_tier [−0.0018,
  −0.0004], 6 of 8 years negative.
- **Gate 3, blend: failed.** A past-only logit blend with BuildOak did not beat both
  components with intervals excluding zero (blend − Alcaraz −0.0009 [−0.0021, +0.0003];
  blend − BuildOak −0.0076 [−0.0107, −0.0043]); no blend is released.

Log loss is the only gated metric; Brier score and winner accuracy are descriptive. The
Ultimate Tennis Statistics and Ingram comparisons named in the gate 2 sentence are the
accepted 2024 results ([EXTERNAL_2024_2025_RESULTS.md](EXTERNAL_2024_2025_RESULTS.md),
[INGRAM_2024_RESULTS.md](INGRAM_2024_RESULTS.md)). They were scored with the `full_tier`
forecasts and were not rerun for `full_tier_entry`.

### Why this is attempt 002

Attempt 001 implemented the any-qualifier flag as "either side entered as Q or LL",
following the frozen admissibility note and the Arm 1 code. The registered design text
says Q only. A check of the implementation against the registration found the difference
after attempt 001 had been scored and reconstructed. Attempt 002 reran Arm 1 exactly as
registered: the flag counts Q only and the LL signed difference is kept. The design,
cohort, Arm 0 and BuildOak forecasts, scorer and seed are unchanged, and the new forecasts
were scored once. This attempt is the primary result on this page. Attempt 001 is reported
as the disclosed implemented variant: −0.0010 [−0.0018, −0.0003] against `full_tier` and
−0.0070 [−0.0100, −0.0040] against BuildOak, with the same three gate verdicts.

## What was compared

Three complete forecasting systems on the same 18,972 ATP primary targets from 2017 to
2024: the all-target cohort of the accepted TIER01 attempt 002 run, with its 380
provisional-identity rows excluded and retirements retained.

- **Arm 0, `full_tier`.** The saved, accepted forecasts. No refit.
- **Arm 1, `full_tier_entry`.** `full_tier` plus nine declared model columns (57 inputs
  instead of 48), refitted on the unchanged trunk: the same boosting menu, five-year
  training window, past-only selection and calibration, and D−2 history rule. The nine
  columns are the signed A−B differences of the Q, LL, WC and PR entry codes, a symmetric
  any-qualifier flag, and one-hot Grand Slam, Masters, other tour-level and Finals flags.
  Round, seeds and draw size are not admitted. Entry status and level are attributes of
  the published draw. A lucky-loser substitution can happen after D−2, so it has its own
  sensitivity. The any-qualifier flag counts a Q entry on either side, as registered.
- **BuildOak adaptation.**
  [buildoak/tennis-xgboost-autoresearch](https://github.com/buildoak/tennis-xgboost-autoresearch/tree/237d1e7ae020de062a994dd7f987881fa2c9a795)
  at `237d1e7`, under the frozen adaptation accepted for 2024
  ([BUILDOAK_2024_RESULTS.md](BUILDOAK_2024_RESULTS.md)), replayed walk-forward. There is
  one fit per 30 December boundary, from 2016-12-30 for the 2017 targets to 2022-12-30 for
  2023. Each fit has its own fit-boundary Elo reference and D−2 releases. The accepted
  2024 run is reused byte for byte. Every fit trained a 900-tree global model and an
  800-tree tour-level model. The recent-era blend stayed below its activation threshold in
  every year, and every target received a native forecast, so the fallback was never used.

## Scores on the 18,972 matches

| Measure | Arm 0 `full_tier` | Arm 1 `full_tier_entry` | BuildOak adaptation |
|---|---:|---:|---:|
| Log loss, match-weighted (lower is better) | 0.5986 | 0.5976 | 0.6046 |
| Log loss, equal-year mean | 0.5984 | 0.5972 | 0.6041 |
| Brier score, match-weighted | 0.2068 | 0.2063 | 0.2093 |
| Winner accuracy | 66.5% | 66.8% | 66.2% |

| Year | Matches | Arm 0 | Arm 1 | BuildOak | Arm 1 − Arm 0 | Arm 1 − BuildOak |
|---|---:|---:|---:|---:|---:|---:|
| 2017 | 2,323 | 0.5937 | 0.5915 | 0.5993 | −0.0022 | −0.0078 |
| 2018 | 2,606 | 0.6050 | 0.6035 | 0.6101 | −0.0016 | −0.0066 |
| 2019 | 2,502 | 0.6057 | 0.6064 | 0.6150 | +0.0008 | −0.0085 |
| 2020 | 1,250 | 0.5954 | 0.5936 | 0.5971 | −0.0017 | −0.0035 |
| 2021 | 2,390 | 0.5977 | 0.5965 | 0.6086 | −0.0012 | −0.0121 |
| 2022 | 2,538 | 0.5917 | 0.5920 | 0.5905 | +0.0003 | +0.0015 |
| 2023 | 2,682 | 0.6012 | 0.5987 | 0.6118 | −0.0025 | −0.0131 |
| 2024 | 2,681 | 0.5965 | 0.5956 | 0.6000 | −0.0009 | −0.0045 |

Per-year log loss; the last two columns are paired differences (negative favours Arm 1).
The 2024 row of Arm 0 and BuildOak equals the accepted 2024 comparison exactly.

## Paired contrasts

Match-weighted paired log-loss difference, left minus right, on identical matches.
Intervals are 95% percentile intervals from 5,000 stationary calendar-week bootstrap
draws. Mean block length eight weeks is primary; four and thirteen are sensitivities.

| Contrast | Matches | Difference | Years negative | Block 8 (primary) | Block 4 | Block 13 | Equal-year mean | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1. Arm 1 − Arm 0 | 18,972 | −0.0011 | 6 of 8 | [−0.0018, −0.0004] | [−0.0017, −0.0004] | [−0.0018, −0.0004] | −0.0011 [−0.0017, −0.0006] | ≤ −0.0008 and upper bound < 0: passed |
| 2. Arm 1 − BuildOak | 18,972 | −0.0070 | 7 of 8 | [−0.0100, −0.0040] | [−0.0098, −0.0043] | [−0.0100, −0.0040] | −0.0068 [−0.0092, −0.0044] | interval excludes zero: supported |
| 3a. Blend − Arm 1 | 11,541 (2020–24) | −0.0009 | 3 of 5 | [−0.0021, +0.0003] | [−0.0020, +0.0002] | [−0.0021, +0.0004] | −0.0010 [−0.0020, −0.0001] | both upper bounds < 0: failed |
| 3b. Blend − BuildOak | 11,541 (2020–24) | −0.0076 | 5 of 5 | [−0.0107, −0.0043] | [−0.0105, −0.0046] | [−0.0109, −0.0041] | −0.0074 [−0.0099, −0.0049] | (same gate) |

The equal-year column is the registered secondary: the mean of yearly means, with
independent per-year week grids. The gates use the match-weighted primary interval only.
For blend − Arm 1 the equal-year interval excludes zero while the primary does not. The
gate is not met.

Descriptive companions for the two 18,972-match contrasts, block 8: Brier score difference
−0.0005 [−0.0008, −0.0001] for Arm 1 − Arm 0 and −0.0030 [−0.0043, −0.0017] for Arm 1 −
BuildOak. The winner-accuracy difference is +0.0025 [+0.0003, +0.0046] for Arm 1 − Arm 0
and +0.0057 [+0.0004, +0.0107] for Arm 1 − BuildOak.

## The blend

Blend logit = (1 − w)·logit(Arm 1) + w·logit(BuildOak). For each target year, w is the
value on the grid 0.00, 0.05, …, 0.50 that minimises match-weighted log loss over the
saved forecasts of the preceding three target years, with ties to the smaller w. It is
never fitted on the target year. BuildOak forecasts start in 2017, so 2020–2024 is the
primary blend cohort, 2018–2019 is secondary and 2017 is excluded.

| Target year | Weight on BuildOak | Fitted on | Matches in fit | Role |
|---|---:|---|---:|---|
| 2017 | — | no earlier BuildOak year | — | excluded |
| 2018 | 0.30 | 2017 | 2,323 | secondary |
| 2019 | 0.30 | 2017–2018 | 4,929 | secondary |
| 2020 | 0.25 | 2017–2019 | 7,431 | primary |
| 2021 | 0.30 | 2018–2020 | 6,358 | primary |
| 2022 | 0.20 | 2019–2021 | 6,142 | primary |
| 2023 | 0.35 | 2020–2022 | 6,178 | primary |
| 2024 | 0.25 | 2021–2023 | 7,610 | primary |

On the 11,541 primary matches the log loss is 0.5946 for the blend, 0.5955 for Arm 1 and
0.6021 for BuildOak. Blend − Arm 1 by year: 2020 −0.0020, 2021 +0.0002, 2022 −0.0027, 2023
+0.0010, 2024 −0.0016. The 5,108 secondary matches from 2018–2019 show blend − Arm 1
−0.0010 [−0.0021, +0.0001] and blend − BuildOak −0.0085 [−0.0112, −0.0058]. No other blend
form, grid or fitting cohort was tried.

## Sensitivities and reference line

| Check | Matches | Difference | Block 8 interval | Years negative |
|---|---:|---:|---:|---:|
| Implemented variant (attempt 001, flag counts Q or LL) − Arm 0 | 18,972 | −0.0010 | [−0.0018, −0.0003] | 6 of 8 |
| Implemented variant − BuildOak | 18,972 | −0.0070 | [−0.0100, −0.0040] | 7 of 8 |
| Blend − implemented variant, 2020–24 | 11,541 | −0.0009 | [−0.0021, +0.0003] | 3 of 5 |
| Arm 1 with LL treated as no flag − Arm 0 | 18,972 | −0.0011 | [−0.0018, −0.0004] | 6 of 8 |
| Contrast 1 without Wimbledon and US Open 2022 | 18,727 | −0.0011 | [−0.0018, −0.0003] | 6 of 8 |
| Contrast 2 on the same 18,727 | 18,727 | −0.0074 | [−0.0103, −0.0046] | — |
| Blend − Arm 1, 2020–24 with the same exclusion | — | −0.0008 | [−0.0018, +0.0002] | — |
| Arm 0 − BuildOak (the arm not selected) | 18,972 | −0.0059 | [−0.0087, −0.0032] | 7 of 8 |
| Reference: Arm 1 − normalised Pinnacle closing price | 18,882 priced | +0.0101 | [+0.0078, +0.0125] | 0 of 8 |

The fit records confirm that `entry_ll_diff`, the only column in which the LL-as-no-flag
run differs, is never split on in any fit behind the selected 2017, 2018, 2023 and 2024
forecasts, which is why those four years are byte-identical between the two runs; its only
splits are in the raw-year 2019 fits, which feed the 2019–2022 forecasts.

Wimbledon 2022 and the US Open 2022 carry no entry code on any row in the source, although
both had qualifiers and wild cards. Their 245 targets are encoded as no flag in the
primary analysis and removed in this sensitivity; every gate verdict is unchanged without
them. The Pinnacle line is descriptive, because the quote time is unknown. On the priced
subset Arm 1 scores 0.5974 against 0.5873 for the normalised price.

Not in the attempt 002 scoring output: the registered descriptive completed-only table,
and the optional Arm 1b (same-event qualifying results as history), which was not run.

## Uncertainty and power

All contrasts use one inclusive calendar-Monday grid per contrast. The week label is the
ISO week of the panel's `tourney_anchor_date`. The 2017–2024 grid runs from 2017-01-02 to
2024-11-11 (411 weeks, 271 with matches) and the blend grid from 2020-01-06 to 2024-11-11.
Resampling uses PCG64 with seed 20260922, the match-weighted ratio within each draw, and
the same draws for log loss, Brier score and accuracy. The intervals condition on the
saved forecasts and omit refit, selection and source-choice uncertainty. The three gates
govern three different decisions and are not adjusted for multiplicity. This is disclosed,
not corrected.

The registration planned contrast 2 with an effective per-match SD of 0.1880. That gives a
minimum detectable effect of 0.0038 and 74% power at the 2024 gap of −0.0036. The realised
effective SD was 0.2109. For contrast 1 the planning SD was bracketed between 0.0450 and
0.1097, which gives a minimum detectable effect between 0.0009 and 0.0022 and power at the
−0.0008 gate between 69% and 17%. The realised effective SD was 0.0503.

## Verification and limits

Checked before scoring and recorded in the archive
(`references/ARMS01/buildoak_execution/EXECUTION_NOTES.md` and the archive decision
records):

- The walk-forward controller reproduced the accepted 2024 BuildOak run byte for byte
  before any 2017–2023 forecast was committed.
- Every 2017–2023 BuildOak year exited cleanly and passed verification twice. Its counts
  equal the prepared projection, and its forecast commitment was hashed before any score.
  The panel-oriented files cover exactly the registered membership.
- The Arm 1 runs reproduced every `base` and `full_tier` forecast file of TIER01 attempt
  002 byte for byte.
- One scoring pass ran from a manifest of file paths and hashes, with the frozen scorer.

After scoring, an independent reconstruction reproduced the result with separate code
(`references/ARMS01/reconstruction/attempt_002/RECONSTRUCTION.md`, verdict ACCEPT): the
memberships rebuilt byte-identical, every bound forecast file rehashed identical, every
estimate and interval within 3e-18 against registered tolerances of 1e-12 and 1e-14,
identical blend weights and grid losses, and the same gate verdicts. Attempt 001 was
reconstructed the same way (`references/ARMS01/reconstruction/RECONSTRUCTION.md`). Archive
decisions D131 and D132 record the acceptance.

Not done: an independent rerun of the 2017–2023 BuildOak forecasts. Reconstruction
rescores the committed files; only 2024 has a byte-for-byte reproduction. The WTA
secondary, on its own cohort and gates, is reported in
[BUILDOAK_WTA_2019_2024_RESULTS.md](BUILDOAK_WTA_2019_2024_RESULTS.md) (archive decision
D133). It is never pooled with ATP and does not change this result. The later registered
tuning pass on this cohort found no gain, and the model is frozen at `full_tier_entry`
([TUNE01_RESULTS.md](TUNE01_RESULTS.md), archive decision D134).

This is an exposed retrospective comparison of complete systems with different legitimate
histories. It is not an untouched test, prospective evidence or a market claim. The
registration was not blind to 2024 or to the entry-status signal: the 22 September review
had screened both on the saved forecasts, which shaped the arms, the gate and the blend
grid. The eight-year design, frozen before its scores existed, mitigates that exposure but
does not remove it. BuildOak's recipe was selected by its author on ROC AUC with sight of
2026 data, and `full_tier` was developed on the same 2017–2024 ladder.

Machine-readable aggregates, per-year tables, selection grids, draw hashes and provenance
hashes: [buildoak_2017_2024.json](buildoak_2017_2024.json).
