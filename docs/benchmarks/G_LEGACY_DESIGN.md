# Lane G legacy benchmark design

Status: `implementation_rehearsal_only`  
Lane: `G-L` (legacy aligned benchmark)  
Decision authority: a later, explicit freeze by Lane 0  
Real fit/report status: **not authorized and not run**

## 1. Question and estimand

Lane G-L asks whether the frozen Tennis Research Lab incumbent forecast has lower
pre-match log loss than a small, interpretable set of public-method comparators on the
same market-source-conditioned aligned cohorts:

- ATP TIER01 `attempt_002`, primary targets, 2017--2024; and
- WTA WTA01 `attempt_001/primary`, primary targets, 2019--2024.

WTA02 is not an eligible substitute. ATP and WTA are reported separately. The primary
estimand is the arithmetic mean of calendar-year mean log loss, so each target year has
equal weight regardless of match count. The secondary estimand repeats that calculation
on the already frozen priced subset. It is not described as an equal-cutoff comparison.
G-U is a separate extension and is not implemented here.

This document binds the executable design before implementation. Nothing in this branch
is evidence about which model wins: only synthetic fits/reports and real structural
projections are permitted while the proposal status is `implementation_rehearsal_only`.

## 2. Frozen populations and input roles

Each tour has four input roles. The forecast process may read only the first three:

1. `features`: neutral match identifiers, target membership, dates, ranks, and already
   past-only public sports features. Target membership is `primary_target == 1`,
   `identity_tier == primary`, and year in the declared target years.
2. `history_panel`: the main-tour family history. Outcomes and score strings may be read
   only for records whose conservative completion upper bound is no later than a target's
   `eligible_through_date`. Price columns are forbidden inputs even if physically present.
3. `incumbent_forecasts`: opaque saved forecasts, filtered to the exact target membership.
4. `labels_and_prices`: report-only target outcomes and prices. The forecast executable
   must not open these paths. The barrier commits forecast bytes before report access.

The family-specific history is named honestly. The incumbent retains its frozen native
history, including TIER01's lower-tier signal where applicable. Reconstructed Kovalchik,
FiveThirtyEight, and WElo services receive the same frozen main-tour prepared-panel
opportunity; they are not claimed to have the incumbent's lower-tier history. Rank inputs
are the already prepared D-2 feature values. No comparator gets a later information set.

Neutral IDs are the archived integer entity IDs, rendered as decimal strings. Every row
must have two distinct IDs, and the adapter canonicalizes orientation to ascending numeric
ID. Swapping source orientation complements the outcome and every probability. Duplicate
`(tour, match_id)` keys are fatal. File order, target round, and target outcome never define
history order or availability.

### Bound real structural artifacts

The tracked proposal config contains the exact paths, SHA-256 digests, row counts, annual
counts, and membership hashes observed in the read-only archive. The key bindings are:

- ATP features: `7f4205318c204049e32efdc9c690be00b91bec72361f6f049cfa6c2985a37a2a`
  (51,222 rows); prepared panel:
  `026f95589c5fe891ad67b643efa1184b33a53139ab4860f9b12e2acd41946c47`
  (51,222 rows); frozen target total 18,972.
- WTA features: `08be99583ee8b06ab07222e017231b79d03d74506e4a4c724a97488c0eb8d6d1`
  (42,485 rows); prepared panel:
  `d0dfe86fa614e9a3e233201f6ce6834d3fb4a21287030b47799828945cb1e1a3`
  (42,485 rows); frozen target total 12,900.

The implementation-only structural projector may verify hashes, headers, row counts,
incumbent forecast coverage, and membership. It may not parse target outcomes, prices, or
probability values and may not emit row-level archive data.

## 3. Chronology and same-day batches

For a target row with match date `d`, the bound cutoff is the archived
`eligible_through_date`, expected to be `d - 2 calendar days`. A history record is eligible
only when its conservative completion upper bound is at or before that cutoff. In this
adapter, `match_date` is the conservative upper bound; `tourney_anchor_date` is never
promoted to a match timestamp.

All rating updates are pre-update date batches:

1. Sort eligible history by `(match_date, match_id)` only for deterministic serialization.
2. Compute every forecast on a date from the state at the start of that date.
3. Aggregate all rating deltas for that date and then apply them once.

This makes predictions invariant to within-day row order and prevents a later-listed
same-day match from becoming history for an earlier-listed one. A target forecast is read
from the state after the last eligible batch and before any target-date result.

For learned rank slopes, the outer-year raw-forecast generator fits only on the preceding
five complete calendar years. For calibration year `c`, its slope is fit on `c-5` through
`c-1`; therefore the outer target's calibration rows are honest out-of-fold forecasts.
No parameter, fallback rate, calibration coefficient, model admission, or procedure
selection is tuned on a target year.

## 4. Admitted procedures and constants

All probabilities are for canonical player A. Numerical output is clipped to
`[1e-6, 1 - 1e-6]` only at serialization/scoring; internal Elo probabilities use their
unclipped values.

### 4.1 Frozen incumbent (`incumbent`)

Import the saved selected HGB forecast for each target year as an opaque probability.
Filter it to the exact frozen primary target keys; missing, duplicate, nonfinite, or extra
keys after filtering are fatal. No refit occurs. The procedure retains the frozen TIER01
or WTA01 selection history and is not relabeled as a reconstruction.

Native dispatch is part of that binding: TIER01's predictor settings intentionally omit
the `tour` key, which activates its ATP tier-capable contract, while WTA01 explicitly sets
`tour=WTA` and uses the non-tier `full` block. The adapter verifies this asymmetry and must
not add an explicit ATP tour setting to the legacy configuration.

### 4.2 K32 Elo (`k32_pooled`)

Initial rating 1500, scale 400, constant `K=32`. Maintain overall and surface ratings.
The raw prediction is a probability-space mean:

`p = 0.5 * p_overall + 0.5 * p_surface`, where
`p_x = 1 / (1 + 10 ** ((R_b,x - R_a,x) / 400))`.

Both overall and the match-surface rating receive the standard Elo delta. Unseen players
and unseen player-surfaces start at 1500. Unknown/empty surface uses the overall
probability twice and receives no distinct surface update.

### 4.3 Rank logistic (`rank_logistic`)

Following the rank-only form summarized by Kovalchik from Klaassen and Magnus,

`logit(p_A) = theta * log(rank_B / rank_A)`.

`theta >= 0` is fit without an intercept by mean Bernoulli log loss on the preceding five
complete calendar years, using the exact frozen target-like public-feature membership for
those years. The candidate set is the singleton fitted procedure; no grid is searched.
Ranks must be finite positive values. If either rank is missing/invalid, the raw forecast
is 0.5. If the fit predictor is identically zero, `theta=1` is the declared fallback. A
failed optimizer, empty five-year window, or absent represented year is an admission
failure, not a reason to fit on the target year.

Primary equation source: Stephanie Kovalchik, *Searching for the GOAT of tennis win
prediction*, JQAS 2016, equation (1):
<https://vuir.vu.edu.au/34652/1/jqas-2015-0059.pdf>.

### 4.4 Kovalchik decaying-K overall Elo (`kovalchik_overall_major`)

Initial rating 1500 and scale 400. Before player i's update:

`K_i = 250 / (N_i + 5) ** 0.4`,

where `N_i` is that player's prior admitted match count. The ordinary player-specific
delta is `K_i * (S_i - p_i)`. Matches with the configured major level code `G` multiply
each player's K by 1.1. This procedure is overall-only. The multiplier is bound to the
Kovalchik paper's reported reconstruction and is not imported into FiveThirtyEight.

Primary source: Kovalchik 2016, equations (2)--(4) and text reporting the 1.1 Grand Slam
adjustment: <https://vuir.vu.edu.au/34652/1/jqas-2015-0059.pdf>.

### 4.5 FiveThirtyEight surface Elo adaptation (`fivethirtyeight_surface`)

Maintain separate overall and surface Elo services, each with initial rating 1500, scale
400, and player-specific `250 / (N_i + 5) ** 0.4`. `N_i` is the prior count in that
service: all admitted matches for overall and prior admitted matches on the given surface
for surface Elo. The raw rating is

`R_blend = 0.71 * R_overall + 0.29 * R_surface`,

and the match probability is computed from the two players' blended ratings at scale 400.
There is no major multiplier: FiveThirtyEight's public method article says that its tested
major extra weight was rejected. Unknown surface falls back to overall-only.

This is labeled an **adaptation**, because the public article supplies the blend and K
formula but not production source code or every edge-case convention. It must not be
described as an exact reproduction.

Primary source: Carl Bialik, *How We're Forecasting The 2016 U.S. Open*,
FiveThirtyEight, 2016: <https://fivethirtyeight.com/features/how-were-forecasting-the-2016-us-open/>.

### 4.6 Weighted Elo (`welo`)

Initial rating 1500, scale 400, and player-specific
`K_i = 250 / (N_i + 5) ** 0.4`. For a result with winner games `G_w` and loser games
`G_l`, multiply both players' ordinary Elo deltas by

`f = G_w / (G_w + G_l)`.

This implements the paper's equation: for a player, the numerator is the winner's games
whether that player won or lost. Conventional completed-set and partial retired-set games
are counted; tiebreak point scores and bracketed match-tiebreak points are not games. A
started retired match is included when at least one conventional game is parseable. A
completed/retired row without parseable conventional games updates the standard decaying-K
Elo fallback (`f=1`) and increments a declared missing-score counter. Walkovers, defaults
without play, abandonments without play, and other unstarted records do not update any
service. This inclusion policy matches the frozen service cohort rather than the paper's
own completed-match cleaning and is therefore reported as a cohort adaptation.

Primary source: Angelini, Candila, and De Angelis, *Weighted Elo rating predictions in
tennis*, 2021, equations (1)--(4):
<https://cris.unibo.it/retrieve/e1dcb337-ea48-7715-e053-1705fe0a6cc9/Weighted%20ELO%20rating%20predictions%20in%20tennis.pdf>.

### 4.7 Explicit non-admissions

- Ingram neural-network forecasts require an exact public feature construction,
  preprocessing, training-data opportunity, architecture, and released weights or a
  faithful retraining contract. Those prerequisites are not bound, so Ingram is not
  admitted.
- Universal Tennis Rating/UTS requires a dated, redistributable historical rating feed
  or a fully specified public reconstruction with identity and timing provenance. Those
  prerequisites are not present, so UTR/UTS is not admitted.
- A generic regularized-logistic or boosted public-feature model could be useful, but
  without a separately frozen feature set and nested selection contract it would be a new
  Tennis Research Lab adaptation, not an author model. It is deferred from this core.

These are admission failures retained in the report, not silently omitted rows.

## 5. Common calibration and fallback

Each reconstructed comparator exposes a raw probability. Separately for each tour,
comparator, and outer year
`y`, fit one nonnegative slope with no intercept on the pooled matches from the three
complete calendar years `y-3..y-1`:

`p_cal = logistic(alpha * logit(p_raw))`, with `alpha >= 0`.

This reproduces the incumbent SR03 calibration opportunity and match-weighted pooled fit;
the final evaluation, not this fit, is year-equal. Calibration-year raw forecasts must be
generated out of fold under section 3. The optimizer, tolerance, and boundary behavior are
the existing `tennislab.dynamics.market.fit` implementation. An all-zero raw-logit window
uses its fixed unit-slope rule. A valid boundary optimum at `alpha=0` is retained and emits
0.5 for every target. Empty/incomplete calibration years, nonfinite inputs, or optimizer
failure are fatal for that service/year and retained as a failed attempt.

The frozen incumbent is not post-hoc recalibrated: its selected HGB probabilities are the
comparison anchor and pass through unchanged. The `raw_incumbent` and
`calibrated_incumbent` columns are therefore byte-equivalent aliases. This avoids a new
nuisance fit that was not part of the frozen incumbent procedure while giving every
reconstruction the same three-prior-year calibration opportunity used in the legacy
selection machinery.

There is no last-minute substitution. The only per-match missingness fallbacks are the
declared rank 0.5 rule, fresh-player 1500 ratings, FiveThirtyEight unknown-surface overall
rule, and WElo missing-score standard-update rule. Every fallback count is reported by
tour, year, and service.

## 6. Separation, manifests, and failure retention

The workflow has four separate entrypoints:

1. `benchmark project`: structure-only validation; never reads outcome or price values.
2. `benchmark forecast`: sports-only forecasts and calibration; refuses proposal configs
   unless explicitly frozen for real execution. It writes no metric-named field.
3. `benchmark barrier`: recursively scans and hashes the closed forecast tree, then writes
   a commitment that binds config, code, source, and forecast artifact hashes.
4. `benchmark report`: verifies the barrier byte for byte before opening labels/prices.

All paths resolve under `TENNISLAB_WORKSPACE`; output paths reject symlink components.
Each attempt ID is immutable. An existing attempt directory is never overwritten. Any
exception writes a failure receipt in that attempt when possible; a retry requires a new
attempt ID, preserving the failed one. Manifests include config hash, code receipt, input
hashes, membership hashes/counts, artifact hashes, procedure constants, dependency
versions, fallback counts, and proposal/execution status.

The forecast barrier forbids target labels, outcomes, result/status/score fields, prices,
odds, implied probabilities, losses, deltas, confidence intervals, and summary metrics.
The real report is single-use per immutable attempt.

## 7. Evaluation and inference

Log loss is `-y*log(p) - (1-y)*log(1-p)` with `p` clipped at `1e-15` only for scoring.
For each tour/service/year calculate the match mean; the primary aggregate is the simple
mean of those annual means. The contrast is

`Delta(service) = LL(incumbent) - LL(service)`;

negative values favor the incumbent. Report raw and calibrated service columns, but the
predeclared multiplicity family is the calibrated incumbent contrast against each of the
five admitted comparators, separately by tour. No ATP/WTA pooling is used.

Uncertainty uses a shared resample across every procedure and contrast. The grid is every
chronological ISO week from the first through last tournament-start week within each
tour-year, including weeks with zero selected matches. The representative week comes from
the archived tournament start/anchor date, never target outcome order. For every tour-year
and replicate, use a circular stationary bootstrap: first index uniform on the full grid;
thereafter restart uniformly with probability `1/L`, otherwise advance one week modulo
grid length. Primary mean block length `L=8`; sensitivity `L in {4, 13}`.

- Replicates: 5,000 valid shared replicates per L.
- Seed: 20260914, with one declared NumPy `PCG64` stream per `(tour, L)`.
- Annual weighting: recompute each annual match mean, then equally average years.
- Degeneracy: discard a draw if any required annual resample has zero matches; continue the
  same RNG stream until 5,000 valid draws or 50,000 total draws, then fail.
- Simultaneous intervals: calculate bootstrap standard errors for each calibrated contrast;
  for nondegenerate contrasts use the 95th percentile of the replicate-wise maximum
  absolute centered studentized statistic across the fixed five-contrast family. Apply
  that one critical value to every family member. A contrast with standard error at or
  below `1e-15` gets the point interval, is marked degenerate, and is excluded from the
  max-t maximum. The empirical quantile uses NumPy's deterministic `linear` method. If
  every contrast is degenerate, the critical value is zero.
- Missing service rows are fatal; fallback rules ensure matched populations rather than
  changing denominators.

The priced secondary subset uses the frozen valid-price membership after the barrier:
ATP 18,882 rows; WTA 12,785 rows. It repeats point estimates and the same inference recipe
on its own full week grids and is labeled secondary.

## 8. Required controls and acceptance

Synthetic fixtures must exercise all admitted procedures and both tours. Acceptance
requires:

- analytic first-update checks for K32, decaying-K, major multiplier, surface blend, and
  WElo game share;
- identical predictions and state after same-day row shuffles;
- swap complementarity under A/B reversal;
- exact duplicate rejection;
- target outcomes changed only after a cutoff leave all earlier forecasts unchanged;
- target price changes leave sports predictions and frozen target membership unchanged;
- planted future rows leave earlier forecasts unchanged;
- zero-slope calibration lands on the nonnegative boundary and emits 0.5;
- forecast tree rejects outcome/price/metric-shaped leakage before commitment;
- a post-barrier forecast-byte mutation blocks reporting;
- stationary-bootstrap draws are shared across models and deterministic from the seed;
- output/config/source/code hashes and failed attempts persist; and
- real structural projection matches every bound header, file digest, count, incumbent
  coverage, annual target count, and membership hash without reading target values.

Passing these controls establishes implementation conformance only. It does not establish
scientific validity, a performance improvement, or readiness for prospective claims.

## 9. Proposed real invocation (not authorized)

After an explicit Lane 0 freeze, create a fresh workspace with a read-only `inputs/archive`
binding to the archive and copy the tracked proposal config into `configs/`. Then:

```bash
export TENNISLAB_WORKSPACE=/path/to/fresh-g-workspace
tennislab benchmark project --config configs/g_legacy.json
tennislab benchmark forecast --config configs/g_legacy.json --attempt G-L-attempt_001
tennislab benchmark barrier --config configs/g_legacy.json --attempt G-L-attempt_001
tennislab benchmark report --config configs/g_legacy.json --attempt G-L-attempt_001
```

The current proposal status makes the three real data-consuming commands refuse. Freezing
requires a reviewed config-hash change; editing only a command-line flag cannot bypass it.
