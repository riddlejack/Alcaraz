# WTA 2019–2024: BuildOak comparison, entry status and a blend (ARMS01 WTA secondary)

> **Independently reconstructed (archive decision D133).** Every number on this page
> comes from the single registered scoring pass of the ARMS01 WTA secondary, attempt 002
> ([buildoak_wta_2019_2024.json](buildoak_wta_2019_2024.json)). A separate implementation
> reproduced every registered estimate and interval before acceptance. This is the
> secondary analysis of ARMS01. It has its own cohort and gates, it is never pooled with
> the ATP result ([BUILDOAK_2017_2024_RESULTS.md](BUILDOAK_2017_2024_RESULTS.md)), and it
> cannot change it.

Extended to WTA 2019–2025 with the frozen model, as exposed retrospective data (EXT2025):
[BUILDOAK_2017_2025_RESULTS.md](BUILDOAK_2017_2025_RESULTS.md). This page stays the registered
result; nothing on it changes.

## Registered outcomes

ARMS01 registered the WTA secondary with the ATP design on 22 September 2026, before any
WTA fit of the new rung or any 2019–2023 BuildOak WTA forecast existed. The WTA level map
was declared before the first fit. The reporting sentences are the registered ones, with
the WTA cohorts filled in from the JSON:

- **Gate 1, covariate block: passed (new WTA rung).** full_entry: full plus entry status
  (Q, LL, WC, PR) and tournament-level context; −0.0012 versus full [−0.0020, −0.0005], 6
  of 6 years negative.
- **Gate 2, public comparison: not supported, inconclusive.** On 12,900 WTA matches from
  2019 to 2024 the BuildOak margin is −0.0026 [−0.0058, +0.0004]; at the 2024 gap this
  comparison had 16% power.
- **Gate 3, blend: passed.** A logit blend of Alcaraz with the BuildOak adaptation, with
  the weight chosen on the three preceding seasons and never the target season, scores
  0.0024 below Alcaraz alone [−0.0040, −0.0008] and 0.0053 below BuildOak alone [−0.0078,
  −0.0028] on 7,181 WTA matches from 2022 to 2024. It is a research artefact, not the
  default model; the BuildOak component is buildoak/tennis-xgboost-autoresearch at 237d1e7.

Log loss is the only gated metric; Brier score and winner accuracy are descriptive. The
bracketed intervals are those of the paired difference, left minus right, so the gate 3
intervals are for blend − Alcaraz and blend − BuildOak.

What the research lead accepted (archive decision D133): `full_entry` is the WTA incumbent
rung for the WTA01 2019–2024 cohort; the scoped public-model sentence is **not** claimed
for WTA; the WTA blend is released as an attributed research artefact. The artefact is the
blend recipe, its past-only weights and its registered scores on this page. It is not the
default model, and no forecast path in this repository issues it. The WTA02 2025–2026
window is untouched: nothing was refitted there, and its rung stays `full`.

### Why this is attempt 002

The first WTA Arm 1 run used the attempt 001 definition of the any-qualifier flag (Q or
LL), the same implementation difference found on ATP. Arm 1 was rerun exactly as
registered: the flag counts Q only and the LL signed difference is kept. The WTA secondary
then had a single scoring pass, which scored both runs. Attempt 002 is primary; attempt 001
is reported below as the disclosed implemented variant. Both runs reproduced every WTA01
`base` and `full` forecast file byte for byte.

## What was compared

Three complete forecasting systems on the same 12,900 WTA primary targets from 2019 to
2024: the all-target cohort of the accepted WTA01 attempt 001 run, with its 244
provisional-identity rows excluded and retirements retained.

| Year | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| Targets | 2,337 | 1,019 | 2,363 | 2,324 | 2,453 | 2,404 | **12,900** |

- **Arm 0, `full`.** The saved, accepted WTA01 forecasts. No refit.
- **Arm 1, `full_entry`.** `full` plus the nine declared model columns of the ATP block,
  refitted on the unchanged trunk: the same boosting menu, five-year training window,
  past-only selection and calibration, and D−2 history rule. WTA has no lower-tier block,
  so the WTA rung is `full_entry`, not `full_tier_entry`. The nine columns are the signed
  A−B differences of the Q, LL, WC and PR entry codes, a symmetric any-qualifier flag
  (Q only, as registered), and one-hot Grand Slam, Masters-level, other tour-level and
  Finals flags read through the declared WTA level map.
- **BuildOak WTA adaptation.**
  [buildoak/tennis-xgboost-autoresearch](https://github.com/buildoak/tennis-xgboost-autoresearch/tree/237d1e7ae020de062a994dd7f987881fa2c9a795)
  at `237d1e7`, under the WTA adapter accepted for 2024
  ([BUILDOAK_WTA_2024_RESULTS.md](BUILDOAK_WTA_2024_RESULTS.md)), replayed walk-forward.
  There is one fit per 30 December boundary, from 2018-12-30 for the 2019 targets to
  2022-12-30 for 2023, each with its own fit-boundary Elo reference and D−2 releases. The
  accepted 2024 forecasts are reused byte for byte, and the walk-forward controller
  reproduced them byte for byte before any 2019–2023 forecast was committed. Every target
  received a native forecast; the fallback was never used.

## Level map and source disclosures

The design says WTA levels "map to the product's WTA level codes, declared at execution
before any fit". The map was declared at 2026-09-23T01:50Z, before any WTA Arm 1 fit
(`references/ARMS01/wta/LEVEL_MAPPING.md`, `level_map.wta.json`, sha256 `16e88b71…`):

| Source `tourney_level` | Flag | Cohort rows |
|---|---|---:|
| `G` | Grand Slam (`level_context_g`) | 2,858 |
| `PM` | Masters level (`level_context_m`) | 1,405 |
| `P`, `I`, `W` | other tour level (`level_context_a`) | 8,534 |
| `F` | Finals (`level_context_f`) | 103 |
| anything else | all four zero | 0 |

Disclosures recorded at execution (`references/ARMS01/wta/WTA_EXECUTION_DECLARATIONS.md`):

- **The source's WTA level codes are inconsistent.** Premier 5 events are always coded `P`,
  and Premier Mandatory / WTA 1000 events are coded `P` in 2016 and 2022 and partly in
  2021, 2023 and 2024. `level_context_m` therefore means "coded `PM`", not "is a WTA 1000".
  A consistent flag would need an external event table, which would be a design change;
  none was made.
- **`W` maps to the other tour-level flag.** 270 of its 285 rows are 2021 WTA 250/500
  events; the other 15 are the 2015 Finals, which train as tour level, not Finals.
- **SR is unflagged.** The registered rule flags PR only. SR, the WTA's protected ranking,
  carries no flag (68 cohort sides). PR occurs only in 2024 (12 sides), so
  `entry_pr_diff` never varies in any WTA training window.
- **Missing entry codes.** Eight Grand Slams carry no entry code on any row: 996 targets,
  7.7% of the cohort, encoded as no flag in the primary analysis. They are removed in the
  declared sensitivity below. 74 Finals rows are also blank, which is plausible for a
  direct-entry field.

## Scores on the 12,900 matches

| Measure | Arm 0 `full` | Arm 1 `full_entry` | BuildOak adaptation |
|---|---:|---:|---:|
| Log loss, match-weighted (lower is better) | 0.6104 | 0.6092 | 0.6118 |
| Log loss, equal-year mean | 0.6111 | 0.6097 | 0.6122 |
| Brier score, match-weighted | 0.2116 | 0.2111 | 0.2124 |
| Winner accuracy | 65.8% | 66.2% | 66.1% |

| Year | Matches | Arm 0 | Arm 1 | BuildOak | Arm 1 − Arm 0 | Arm 1 − BuildOak | Arm 0 − BuildOak |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2019 | 2,337 | 0.6190 | 0.6177 | 0.6251 | −0.0012 | −0.0074 | −0.0062 |
| 2020 | 1,019 | 0.6168 | 0.6138 | 0.6148 | −0.0030 | −0.0009 | +0.0021 |
| 2021 | 2,363 | 0.6005 | 0.6000 | 0.5978 | −0.0005 | +0.0022 | +0.0027 |
| 2022 | 2,324 | 0.6132 | 0.6110 | 0.6183 | −0.0023 | −0.0074 | −0.0051 |
| 2023 | 2,453 | 0.6128 | 0.6127 | 0.6120 | −0.00005 | +0.0007 | +0.0008 |
| 2024 | 2,404 | 0.6040 | 0.6028 | 0.6050 | −0.0012 | −0.0022 | −0.0010 |

Per-year log loss; the last three columns are paired differences (negative favours the
left). The 2024 row of Arm 0 and BuildOak equals the accepted WTA 2024 comparison
(Arm 0 − BuildOak −0.0010).

## Paired contrasts

Match-weighted paired log-loss difference, left minus right, on identical matches.
Intervals are 95% percentile intervals from 5,000 stationary calendar-week bootstrap
draws. Mean block length eight weeks is primary; four and thirteen are sensitivities.

| Contrast | Matches | Difference | Years negative | Block 8 (primary) | Block 4 | Block 13 | Equal-year mean | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1. Arm 1 − Arm 0 | 12,900 | −0.0012 | 6 of 6 | [−0.0020, −0.0005] | [−0.0020, −0.0005] | [−0.0020, −0.0005] | −0.0014 [−0.0020, −0.0007] | ≤ −0.0008 and upper bound < 0: passed |
| 2. Arm 1 − BuildOak | 12,900 | −0.0026 | 4 of 6 | [−0.0058, +0.0004] | [−0.0058, +0.0004] | [−0.0059, +0.0004] | −0.0025 [−0.0049, −0.00004] | interval excludes zero: not supported |
| 3a. Blend − Arm 1 | 7,181 (2022–24) | −0.0024 | 3 of 3 | [−0.0040, −0.0008] | [−0.0040, −0.0008] | [−0.0040, −0.0008] | −0.0024 [−0.0036, −0.0012] | both upper bounds < 0: passed |
| 3b. Blend − BuildOak | 7,181 (2022–24) | −0.0053 | 3 of 3 | [−0.0078, −0.0028] | [−0.0078, −0.0028] | [−0.0079, −0.0028] | −0.0053 [−0.0072, −0.0034] | (same gate) |

The equal-year column is the registered secondary: the mean of yearly means, with
independent per-year week grids. The gates use the match-weighted primary interval only.
For contrast 2 the equal-year interval just excludes zero while the primary does not; the
gate is not met, and the registered reading is inconclusive, not parity.

Descriptive companions, block 8: Brier score difference −0.0005 [−0.0009, −0.0002] for
Arm 1 − Arm 0 and −0.0013 [−0.0026, −0.0001] for Arm 1 − BuildOak. The winner-accuracy
difference is +0.0036 [+0.0012, +0.0060] for Arm 1 − Arm 0 and +0.0009 [−0.0055, +0.0070]
for Arm 1 − BuildOak.

## The blend

Blend logit = (1 − w)·logit(Arm 1) + w·logit(BuildOak). For each target year, w is the
value on the grid 0.00, 0.05, …, 0.50 that minimises match-weighted log loss over the
saved forecasts of the preceding three target years, with ties to the smaller w. It is
never fitted on the target year. BuildOak WTA forecasts start in 2019, so 2022–2024 is the
primary blend cohort, 2020–2021 is secondary and 2019 is excluded.

| Target year | Weight on BuildOak | Fitted on | Matches in fit | Role |
|---|---:|---|---:|---|
| 2019 | — | no earlier BuildOak year | — | excluded |
| 2020 | 0.30 | 2019 | 2,337 | secondary |
| 2021 | 0.35 | 2019–2020 | 3,356 | secondary |
| 2022 | 0.40 | 2019–2021 | 5,719 | primary |
| 2023 | 0.40 | 2020–2022 | 5,706 | primary |
| 2024 | 0.45 | 2021–2023 | 7,140 | primary |

On the 7,181 primary matches the log loss is 0.6064 for the blend, 0.6088 for Arm 1 and
0.6117 for BuildOak. Blend − Arm 1 by year: 2022 −0.0010, 2023 −0.0042, 2024 −0.0020.
Blend − BuildOak by year: 2022 −0.0083, 2023 −0.0035, 2024 −0.0042. The 3,382 secondary
matches from 2020–2021 show blend − Arm 1 −0.0040 [−0.0054, −0.0026] and blend − BuildOak
−0.0027 [−0.0056, −0.0001]. No other blend form, grid or fitting cohort was tried.

The WTA and ATP blends reached different verdicts on their own registered gates; the ATP
blend failed gate 3 and is not released. The two tours are never pooled.

## BuildOak's 2024 structural break

The BuildOak recipe adds a recent-era WTA model to its ensemble only when the training
data hold at least 15,000 recent rows. At the 2019–2023 boundaries the count was 5,624,
8,330, 9,637, 12,234 and 14,828 (2023 missed by 172 rows), so those years fitted four
members: two global models blended 0.65/0.35 (800 and 650 trees), a hard-court specialist
and a level-I specialist (900 trees each). At the 2024 boundary it was 17,638, so 2024
fitted six members, adding the recent-era global pair (800 and 650 trees, weight 0.35). The 2019–2023 BuildOak forecasts therefore come
from a structurally different recipe than the 2024 forecasts that the accepted 2024
comparison scored.

Every pooled contrast involving BuildOak mixes both regimes. Arm 0 − BuildOak by year is
−0.0062, +0.0021, +0.0027, −0.0051, +0.0008 and −0.0010 (3 of 6 negative). The registered
contrasts do not depend on the break, and nothing in the scoring changes with it, but it
limits what the pooled BuildOak margin says about the 2024 recipe.

## Sensitivities

| Check | Matches | Difference | Block 8 interval | Years negative |
|---|---:|---:|---:|---:|
| Implemented variant (attempt 001, flag counts Q or LL) − Arm 0 | 12,900 | −0.0013 | [−0.0021, −0.0006] | 6 of 6 |
| Contrast 1 without the eight uncoded Grand Slams | 11,904 | −0.0012 | [−0.0020, −0.0004] | 6 of 6 |
| Contrast 2 on the same 11,904 | 11,904 | −0.0025 | [−0.0058, +0.0006] | 4 of 6 |
| Blend − Arm 1, 2022–24, same exclusion | 6,681 | −0.0026 | [−0.0042, −0.0009] | 3 of 3 |
| Blend − BuildOak, 2022–24, same exclusion | 6,681 | −0.0052 | [−0.0081, −0.0027] | 3 of 3 |
| Arm 0 − BuildOak (the arm not selected) | 12,900 | −0.0014 | [−0.0046, +0.0017] | 3 of 6 |

Every gate verdict is unchanged without the 996 uncoded Grand Slam targets. The
lucky-loser (LL as no flag) refit and the optional Arm 1b were not run for WTA, and the
WTA secondary registered no market reference line. The ladder view of this cohort, with the
Pinnacle line on the 12,785 priced matches, is the WTA01 section of
[RESULTS.md](../RESULTS.md); it uses the ladder's own match-level interval and is
descriptive.

## Uncertainty and power

All contrasts use one inclusive calendar-Monday grid per contrast. The week label is the
ISO week of the panel's `tourney_anchor_date`. The 2019–2024 grid runs from 2018-12-31 to
2024-11-04 (306 weeks, 192 with matches) and the primary blend grid from 2022-01-03 to
2024-11-04 (149 weeks, 104 with matches). Resampling uses PCG64 with seed 20260922, the
match-weighted ratio within each draw, and the same draws for log loss, Brier score and
accuracy. The intervals condition on the saved forecasts and omit refit, selection and
source-choice uncertainty. The three gates govern three different decisions and are not
adjusted for multiplicity. This is disclosed, not corrected.

The registration planned WTA contrast 2 with an effective per-match SD of 0.118. That gives
an expected half-width of ±0.0020, a minimum detectable effect of 0.0029 and **16% power at
the 2024 gap of −0.0010**, so the design registered this comparison as underpowered. The
realised effective SD was 0.180, which makes the interval wider than planned. For contrast
1 the planning SD was bracketed between 0.045 and 0.1097 (minimum detectable effect
0.0011–0.0027; power at the −0.0008 gate 52% to 13%). The realised effective SD was
0.044, at the optimistic end of the bracket. The realised SDs of the primary blend
contrasts were 0.071 (blend − Arm 1) and 0.109 (blend − BuildOak).

## Verification and limits

Checked before scoring and recorded in the archive
(`references/ARMS01/buildoak_wta_execution/EXECUTION_NOTES.md`,
`references/ARMS01/wta/WTA_EXECUTION_DECLARATIONS.md` and the archive decision records):

- The walk-forward controller reproduced the accepted WTA 2024 BuildOak run byte for byte
  before any 2019–2023 forecast was committed. The first reproduction attempt was
  interrupted by a host power loss before any fit and is retained; the second completed.
- Every 2019–2023 BuildOak year exited cleanly and passed verification twice. Its counts
  equal the prepared projection, its forecast commitment was hashed before any score, and
  the panel-oriented files cover exactly the registered membership.
- Both WTA Arm 1 runs reproduced all 60 WTA01 `base` and `full` forecast files and the 12
  market files byte for byte.
- One scoring pass ran from a manifest of file paths and hashes, with the frozen scorer.

After scoring, an independent reconstruction reproduced the result with separate code
(`references/ARMS01/reconstruction/wta_attempt_002/RECONSTRUCTION.md`, verdict ACCEPT):
the membership rebuilt byte-identical, all 24 bound forecast files rehashed identical,
every point estimate within 1e-18 and every gate interval within 3e-18 against
registered tolerances of 1e-12 and 1e-14, identical blend weights and grid losses, and
the same gate verdicts. It also confirmed that the 2024 BuildOak file equals the accepted
WTA 2024 paired rows on all 2,404 rows and that the week labels equal the accepted
`tournament_week`. Archive decision D133 records the acceptance.

Not done: an independent rerun of the 2019–2023 BuildOak forecasts. Reconstruction
rescores the committed files; only 2024 has a byte-for-byte reproduction.

This is an exposed retrospective comparison of complete systems with different legitimate
histories. It is not an untouched test, prospective evidence or a market claim. The
registration was not blind to 2024: the 22 September review had screened WTA 2024 blends
and the WTA 2024 gap before drafting. The six-year design, frozen before its scores
existed, mitigates that exposure but does not remove it. BuildOak's recipe was selected by
its author on ROC AUC with sight of 2026 data, so the released blend carries that exposure,
and the WTA01 cohort is exposed development data on which the `full` rung was scored
before this registration. No claim here extends beyond the named systems, this cohort and
paired log loss.

Machine-readable aggregates, per-year tables, selection grids, draw hashes and provenance
hashes: [buildoak_wta_2019_2024.json](buildoak_wta_2019_2024.json).
