# Alcaraz

**A calibrated model for tennis matchup probabilities.** Alcaraz estimates a
player's chance to win before a match using histogram gradient boosting. Its
inputs combine overall and surface Elo, ranking and recent workload, player
traits, and dynamic opponent-adjusted serve/return strength. The ATP route also
uses qualifying, Challenger, and Futures history—the matches that often explain
where a player's current level came from before it appears on the main tour.

The project tests a concrete question: do richer, time-appropriate histories
produce better calibrated probabilities than a simpler rating baseline? It keeps
the positive results, the nulls, and the failed implementation paths together.
The released models are retrospective research artifacts—not a proven edge or a
demonstrated pre-play forecasting service.

![How Alcaraz turns tennis histories into a calibrated matchup probability: match and ranking history feed Elo, form and workload features plus dynamic opponent-adjusted serve-return strength; ATP adds lower-tier state; a histogram-gradient-boosting model and past-only calibration produce the probability.](docs/assets/alcaraz-evidence-pipeline.svg)

## How a forecast is made

The men's pipeline uses **51,222 main-tour matches from 2005–2024**,
**480,012 eligible lower-tier results**, and **24.2 million service points
aggregated from match-level serve statistics**. The separate women's history
covers **2007–2026**, including a partial 2026 season. These are source-record
and aggregate-point counts, not 24.2 million independent point sequences.

- **Ratings establish the matchup.** Overall and surface Elo summarize the
  strength of each player and the court context.
- **Match history makes that rating more specific.** Rankings, recent form,
  workload, and player traits describe the setting around the matchup.
- **Serve and return states add a different signal.** They update from prior
  match statistics and adjust for the strength of opponents, separating a
  strong performance from an easy schedule as far as the saved history allows.
- **ATP lower-tier history fills in early and off-main-tour development.** It
  is not simply more rows: it changes a player's available history and is
  therefore evaluated as part of a full feature bundle.

The final model is selected and calibrated on earlier seasons, then writes a
probability for the later matchup. Historical comparisons use those saved
pre-match probabilities; timing and independent checks keep a strong score from
being mistaken for evidence of live readiness.

## What improved on one shared ATP population

The clearest development result is a four-rung ATP feature ladder: **18,882
matched 2017–2024 targets** at every rung. Log loss measures probability
quality (lower is better); accuracy is the share of correct winner picks. This
is not a timeline or a claim that any single feature caused the gain—it is a
same-match comparison of progressively richer, bundled models.

![Four-rung ATP feature ladder on the same 18,882 2017 to 2024 targets: Elo only has log loss 0.62369 and accuracy 64.55 percent; base statistics plus HGB 0.61210 and 65.40 percent; adding traits and dynamic serve-return 0.60534 and 66.22 percent; ATP lower-tier history 0.59843 and 66.51 percent.](docs/assets/atp-feature-ladder.svg)

The matched results support testing opponent-adjusted serve/return state and
lower-tier history as useful additions to this model family. They do not prove a
single mechanism, a universal advantage over every predictor, or future
performance. [Annual values and the full ladder →](docs/RESULTS.md)

## Independent comparisons and difficult results

Every row below is a separate historical comparison on the listed matches.
Different rows use different data histories and should not be collapsed into one
headline score.

| Comparison | Matches | Probability result | Winner-pick result | What it supports |
|---|---:|---|---|---|
| [Five ranking/Elo baselines](docs/benchmarks/G_L_RESULTS.md) | ATP 18,972; WTA 12,900 | Alcaraz lower log loss than all five on each tour | Reported separately by tour | A bounded, independently reconstructed historical benchmark |
| [buildoak XGBoost adaptation — ATP](docs/benchmarks/BUILDOAK_2024_RESULTS.md) | 2,681 ATP, 2024 | 0.596486 vs 0.600044 | 66.17% vs 66.06% | Alcaraz point lead; log-loss interval crosses zero |
| [buildoak XGBoost adaptation — WTA](docs/benchmarks/BUILDOAK_WTA_2024_RESULTS.md) | 2,404 WTA / 55 editions, 2024 | 0.604022 vs 0.605039 | 1,575 vs 1,589 correct | Inconclusive; external system has 14 more correct picks |
| [Ingram Bayesian point-model adaptation](docs/benchmarks/INGRAM_2024_RESULTS.md) | 2,681 ATP, 2024 | 0.596486 vs 0.641705 | 66.17% vs 63.48%; 72 more correct | Alcaraz log-loss advantage; primary 95% interval [−0.056486, −0.035027] |

The external adaptations retain their own forecasting methods and different
source histories. They are neither reproductions of the source author's
headline results nor equal-input algorithm contests. All are exposed
historical comparisons with uncertainty calculated from fixed forecasts.
The Ingram result supports a clear log-loss advantage over that specified
adaptation; its accuracy advantage is a point estimate. The buildoak comparisons
remain inconclusive, so these results do not establish state-of-the-art status.

A separate [shared-data WTA control](docs/benchmarks/BUILDOAK_FAIRNESS_AUDIT.md)
matched qualified observations and final training membership. Alcaraz made **39
more correct picks** and reduced log loss by **0.022913** (95% interval
[−0.032487, −0.013962]). Buildoak improved substantially when its own broader
input policy was restored. This supports a scoped modeling-pipeline advantage
on the shared data; the full-system comparisons above retain each model's
legitimate data advantages and remain the primary results.

![Two evidence-backed public-XGBoost comparisons shown as separate ATP and WTA cards. Each card uses its own cohort, log-loss difference, accuracy result, and interval conclusion.](docs/assets/public-xgboost-comparisons.svg)

The early work produced plausible backtests. Review found why that was not
enough: draw-page rounds had become invented match dates, a learned constant
could see future outcomes, and one calibration stage scored before its barrier.
The rebuild fixed those paths, but the more important change was practical: a
new idea now has to beat its matched comparison and survive an uncertainty check
before it can replace the accepted model.

| Tested idea | Exact retrospective result | What it changed |
|---|---|---|
| [Uncertainty through the final predictor](docs/experiments/RECENT_EXPERIMENTS.md#uncertainty-through-the-final-predictor) | 7,610 ATP targets; log loss +0.000157 and eight more correct picks; intervals cross zero; exposed 2024 extension also inconclusive | Retain the incumbent |
| [Larger HGB head + expanded training window](docs/experiments/RECENT_EXPERIMENTS.md#learner-capacity-and-training-window) | 7,610 ATP targets; log loss worsened by 0.003328, 95% interval wholly adverse; 35 fewer correct picks | Retain the smaller incumbent |
| [Eight-member stack and alternatives](docs/CAMPAIGN_E_RESULTS.md) | ATP stack delta −0.000419 log loss, 95% interval crosses zero; WTA point estimate worse | No default replacement |
| [Serve-component representation](docs/experiments/RECENT_EXPERIMENTS.md#serve-components) | 7,610 ATP 2021–2023 targets; primary delta −0.000076780, interval crosses zero | No component promotion |
| [WTA downstream selection](docs/experiments/RECENT_EXPERIMENTS.md#wta-selection) | 7,140 targets; delta −0.000082, interval crosses zero; one net correct pick | Defer the tested policy |
| [Richer state geometry](docs/experiments/RECENT_EXPERIMENTS.md#richer-state-geometry) | 7,610 targets; log loss worsened by 0.000146803, interval includes zero | No state-feature promotion |

Those results are not a claim that feature development has stopped. They say
the tested additions did not earn a default change under their stated
populations and methods.

## Run the project

For a clean, synthetic reproduction of the core path:

```sh
make setup
make reproduce-small
```

The synthetic scenario validates the runnable path; it is not a performance
reproduction. The accepted checkpoints and their inference requirements are in
the release guide below.

[**Download accepted models**](https://github.com/riddlejack/alcaraz/releases/tag/models-2026-09-14)
· [Experimental model bundle](https://github.com/riddlejack/alcaraz/releases/tag/campaign-e-research-models-2026-09-15)
· [Inference guide](docs/MODEL_RELEASE.md)
· [Methods](docs/METHODS.md)
· [System design and development](docs/PROCESS.md)
· [Data scale and table provenance](docs/benchmarks/LANDING_PAGE_FACTS.json)

The accepted download includes 40 trained checkpoints and calibration parameters;
the experimental bundle preserves 140 fitted estimators and combination
decisions. Private source rows are excluded. Player-level forecasting requires
the [qualified history workflow](docs/live/README.md), and the repository does
not represent that unfinished workflow as an available live service. No batch
of real forecasts has yet been verified as issued before play and later scored
under a predeclared plan.

Code: **MIT**. Match, ranking, and player data: **Jeff Sackmann / Tennis
Abstract**, with source terms and additional attribution in
[DATA_LICENSES.md](DATA_LICENSES.md). The public XGBoost comparison is an
adaptation of [buildoak/tennis-xgboost-autoresearch](https://github.com/buildoak/tennis-xgboost-autoresearch/tree/237d1e7ae020de062a994dd7f987881fa2c9a795);
its code and research story remain separately attributed.
