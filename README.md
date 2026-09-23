# Alcaraz

**How close can public statistics get to the betting market at predicting tennis?**

Close, but not all the way. On 18,882 ATP matches from 2017 to 2024, Alcaraz scores a log
loss of **0.5974** against **0.5873** for Pinnacle's closing price. Alcaraz scores ahead
of every public model we could run, with intervals excluding zero: the BuildOak XGBoost
adaptation on 18,972 ATP matches from 2017 to 2024 (paired log loss −0.0070, 95% interval
[−0.0100, −0.0040], 7 of 8 years), and the Ultimate Tennis Statistics formula and the
Ingram point model on 2,681 ATP matches from 2024. Paired log loss, stationary
calendar-week bootstrap. It does not beat the market, and after a long search, every step
of it logged, we think most of the remaining gap is information the market has and the
public record does not.

> **Independently reconstructed (archive decisions D131 and D132).** The
> `full_tier_entry` rung, the eight-year BuildOak comparison and the blend result come
> from the registered ARMS01 experiment, attempt 002
> ([details](docs/benchmarks/BUILDOAK_2017_2024_RESULTS.md)). Rows marked † below come
> from it.

![Top: the ATP feature ladder on one shared cohort of 18,882 matches, ending with the entry-status rung. Bottom: paired log-loss differences against three public systems: BuildOak on 18,972 ATP matches from 2017 to 2024, the other two on 2,681 ATP matches from 2024.](docs/assets/alcaraz-results.svg)

## The result in one table

| System | Matches | Log loss | Correct picks | Compared how |
|---|---:|---:|---:|---|
| Pinnacle closing price | 18,882 ATP, 2017–24 | **0.5873** | 68.0% | market reference, quote time unknown |
| **Alcaraz full_tier_entry** † | 18,882 ATP, 2017–24 | **0.5974** | 66.8% | walk-forward, calibrated on earlier seasons |
| Alcaraz full-tier (previous rung) | 18,882 ATP, 2017–24 | 0.5984 | 66.5% | same matches |
| Elo only | 18,882 ATP, 2017–24 | 0.6237 | 64.6% | same matches, no fitting |
| BuildOak XGBoost † | 18,972 ATP, 2017–24 | 0.6046 vs 0.5976 | 66.2% vs 66.8% | paired, walk-forward; interval excludes zero |
| Ultimate Tennis Statistics formula | 2,681 ATP, 2024 | 0.6209 vs 0.5965 | 64.6% vs 66.2% | paired with full-tier; Alcaraz ahead |
| Ingram Bayesian point model | 2,681 ATP, 2024 | 0.6417 vs 0.5965 | 63.5% vs 66.2% | paired with full-tier; Alcaraz ahead |
| Five Elo and ranking baselines | 18,972 ATP; 12,900 WTA | Alcaraz lowest on both tours | reported per tour | all five intervals exclude zero; scored before the entry rung |

Women's tennis runs through the same trunk with its own history and gets the same shape
of result: Alcaraz 0.6153, Pinnacle 0.5953 on 2,344 priced WTA matches from 2025–26.
The same registered test on 12,900 WTA matches from 2019 to 2024 is in progress.
Full tables, intervals and per-year values: [RESULTS.md](docs/RESULTS.md),
[BUILDOAK_2017_2024_RESULTS.md](docs/benchmarks/BUILDOAK_2017_2024_RESULTS.md) and
[docs/benchmarks](docs/benchmarks).

## What is in the model

Alcaraz is a histogram gradient-boosting classifier over 57 inputs, refitted each season
on a five-year window and calibrated on the three seasons before the target. The inputs
come in five blocks, and the ladder adds them one at a time:

- **Ratings.** Overall and surface Elo from tour results.
- **Match history.** Rankings, recent workload and rest, match format, player traits.
- **Serve and return states.** A dynamic model of each player's serve and return
  strength, updated match by match and adjusted for who they played. This is the block
  that separates a strong run from an easy draw.
- **Lower-tier history (ATP).** Qualifying, Challenger and Futures results and serve
  statistics. It is the largest single gain on the ladder because it fills in the years
  before a player reaches the main tour.
- **Draw context (ATP).** Each player's entry status (qualifier, lucky loser, wild card,
  protected ranking) and the tournament level, both published with the draw. Round and
  seeding are not used.

The fifth block came out of review. A post-hoc screen in the independent review of
22 September found that the model underrated qualifiers: in matches with exactly one
qualifier, qualifiers won 39.5% and the model gave them 34.6%. Entry status had never been
an input, and the qualifying wins behind it are not yet visible at the two-day cutoff.
The registered ARMS01 experiment then added the block and refitted all eight seasons:

> full_tier_entry: full_tier plus entry status (Q, LL, WC, PR) and tournament-level
> context; −0.0011 versus full_tier [−0.0018, −0.0004], 6 of 8 years negative.

No price, odds or market field enters the model. Every result, rating and statistic must
be knowable two days before the match date; draw facts such as surface, format, entry
status and level come with the pairing itself. The pipeline records which outcomes each
fold read and refuses anything later.

## Why the numbers are trustworthy

The first version of this project produced plausible backtests. Independent review then
found four ways they were wrong, and the fixes are the reason the current numbers hold:

| What review found | What it would have done | What changed |
|---|---|---|
| Draw-page round order was being turned into match dates | A 2026 Canada final leaked into two later Cincinnati rows | Every date now carries a typed basis: anchor, bound or clock |
| A learned constant was fitted through 2016 and used inside 2014–16 folds | Selection data influenced a "past-only" parameter | Every learned constant carries a horizon receipt |
| A calibration stage wrote scores before the report barrier | Downstream barriers could not stop an upstream scorer | Forecasts are emitted before the barrier, scores after |
| A 24-test leakage suite stayed green when leaks were planted | "All green" meant nothing | A detector enters CI only after it fails its planted control |

Beyond that: every published number is generated from a hashed artifact, a different
model reconstructed the arithmetic before anything was accepted, and the 145-entry
leaderboard and the experiment ledger are published in `data/registries` so the search
history is visible. Nothing on disk is holdout; the 2025–26 window has been opened and is
development data.

## What did not work

These are honest nulls on matched cohorts, not abandoned ideas.

| Tried | Result | Verdict |
|---|---|---|
| Larger boosting head, longer training window | +0.0033 log loss, interval wholly adverse | keep the small model |
| Eight-member stack over the incumbent and alternatives | −0.0004, interval crosses zero | no promotion |
| Uncertainty-aware serve/return states through the final model | +0.0002 | no promotion |
| Serve sub-components, richer state geometry, WTA selection policy | all within ±0.0002 | no promotion |
| Market-as-teacher distillation | −0.0007 vs outcome-only | below the 0.003 gate |
| Model + Pinnacle residual | worse than calibrated Pinnacle alone | market already contains the model |
| Past-only logit blend with BuildOak, 2020–24 † | −0.0009 [−0.0021, +0.0003] vs Alcaraz alone | no blend is released |
| Weather, fatigue, point-by-point states | worse or null | retired |

## How the work was done

One person, no data-science background, set the question, the scope and the licence
boundaries, and decided when to stop. Four LLM roles did the rest under narrow briefs
with explicit write boundaries: one built, one reviewed adversarially, one reconstructed
accepted results from scratch, one handled bounded data acquisition. No builder accepted
its own claims. The archive keeps every failed attempt, and
[PROCESS.md](docs/PROCESS.md) records what each failure changed.

The product is 51k lines of Python in one trunk, 687 tests, a locked environment
and CI that reproduces a synthetic end-to-end run on every push.

## Run it

```sh
make setup
make reproduce-small
```

Reproduces the full pipeline on a synthetic sample in about a minute. Real history is
governed by source terms and stays out of Git; the accepted model checkpoints are a
[GitHub release](https://github.com/riddlejack/Alcaraz/releases/tag/models-2026-09-14)
with an [inference guide](docs/MODEL_RELEASE.md).

## Status and limits

- Retrospective research. Two real forecasts have been issued before their scheduled
  start under a [hash-chained ledger](docs/live/README.md); no scored prospective
  record exists yet.
- ARMS01 was registered and frozen on 22 September 2026, before any of its scores existed.
  It ran the BuildOak comparison over all eight seasons, added entry status and tournament
  level, and tested a past-only blend. Attempt 001 implemented the any-qualifier flag as Q
  or LL, while the registration says Q; attempt 002 reran the block exactly as registered,
  and attempt 001 is reported as a disclosed sensitivity. Attempt 002 was independently
  reconstructed (archive decisions D131 and D132). A past-only logit blend with BuildOak
  did not beat both components with intervals excluding zero (blend − Alcaraz −0.0009
  [−0.0021, +0.0003]; blend − BuildOak −0.0076 [−0.0107, −0.0043]); no blend is released.
  The WTA secondary is in progress.
- Pinnacle's quote time is unknown, so the market comparison is descriptive.

Methods: [METHODS.md](docs/METHODS.md) · Data and licences:
[DATA.md](docs/DATA.md), [DATA_LICENSES.md](DATA_LICENSES.md) · Decisions:
[DECISIONS.md](docs/DECISIONS.md)

Code is MIT. Match, ranking and player data are from Jeff Sackmann / Tennis Abstract
under CC BY-NC-SA 4.0. The XGBoost comparison adapts
[buildoak/tennis-xgboost-autoresearch](https://github.com/buildoak/tennis-xgboost-autoresearch).
