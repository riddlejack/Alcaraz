# Alcaraz

**State of the art among public, statistics-only tennis forecasters: ahead of every one
that could be run against it, and 0.010 log loss behind the betting market.**

Alcaraz predicts professional tennis matches from the public record alone: results,
rankings, serve and return statistics, lower-tier history and the published draw. No
betting price, injury report or scouting note enters the model. On 18,972 ATP matches
from 2017 to 2024 it scores ahead of the strongest public model that could be reproduced,
and every men's-tour comparison that could be built has a 95% interval that excludes zero.
Within that scope it is the state of the art as far as it could be tested; the one model
that could not be run is named below, not assumed beaten.

The sharpest benchmark is the market itself. Against Pinnacle's closing price on the same
matches, Alcaraz trails by 0.010 log loss, about one correct pick in eighty. The leading
hypothesis is that most of that gap is information the public record does not hold:
fitness, injuries, withdrawals and how much a match matters to each player on the day.

The project started with Green Code's *I Trained AI to Predict Sports*. Its first model
reported 85% accuracy and, as its creator later disclosed, had post-match ratings leaking
into pre-match features. That left a question worth answering properly: with every leak
hunted down, how well can public statistics really predict tennis?

![Top: the ATP model built up block by block on one shared set of 18,882 matches, ending with the entry-status block. Bottom: paired log-loss differences against three public systems, each on its own matches, with 95% intervals.](docs/assets/alcaraz-results.svg)

## Results

Log loss scores a probability forecast, and lower is better: a coin flip scores 0.693.
Every comparison below is paired, meaning both systems are scored on exactly the same
matches, with a 95% interval from a calendar-week block bootstrap. Every number is
generated from a committed artifact, and every accepted result was reproduced from
separate code before acceptance. Full tables and per-season values:
[RESULTS.md](docs/RESULTS.md) and [docs/benchmarks](docs/benchmarks).

### Each block of public statistics moved the model closer to the market

The same 18,882 ATP matches from 2017 to 2024, every one with a Pinnacle price. Each row
adds one block of inputs to the row above, and every step's interval excludes zero.

| Model | Log loss | Correct picks |
|---|---:|---:|
| Elo ratings only, no fitting | 0.6237 | 64.6% |
| + boosted model on results, rankings and workload | 0.6121 | 65.4% |
| + player traits and dynamic serve/return states | 0.6053 | 66.2% |
| + qualifying, Challenger and Futures history | 0.5984 | 66.5% |
| **+ entry status and tournament level: Alcaraz** | **0.5974** | **66.8%** |
| Pinnacle closing price, normalised | 0.5873 | 68.0% |

Alcaraz minus Pinnacle: +0.0101 [+0.0080, +0.0122]. The model is refitted for each
season on the five seasons before it and calibrated on the three seasons immediately
before it, so no season is scored by a model that has seen it.

### Head to head with public models

Each row is its own matched comparison, so the public model and Alcaraz share every match
in that row. Alcaraz's own score shifts slightly between rows because the match sets
differ: the 18,972-match set includes 90 matches without a market price, and the 2024
rows were scored with the previous model version, before the entry-status block.

| Public model | Matches | Their log loss | Alcaraz | Alcaraz minus theirs [95% interval] | Seasons ahead |
|---|---|---:|---:|---:|---:|
| [BuildOak XGBoost](https://github.com/buildoak/tennis-xgboost-autoresearch), replayed season by season | 18,972 ATP, 2017–24 | 0.6046 | 0.5976 | −0.0070 [−0.0100, −0.0040] | 7 of 8 |
| [Ultimate Tennis Statistics](https://github.com/mcekovic/tennis-crystal-ball) formula | 2,681 ATP, 2024 | 0.6209 | 0.5965 | −0.0244 [−0.0311, −0.0176] | 1 of 1 |
| Ingram's Bayesian point model | 2,681 ATP, 2024 | 0.6417 | 0.5965 | −0.0452 [−0.0565, −0.0350] | 1 of 1 |
| IBM Match Insights, archived pre-match forecasts | 29 Grand Slam matches, 2022–23, both tours | 0.6285 | 0.4550 | −0.1735 [−0.2383, −0.1074] | — |
| Five Elo and ranking baselines (FiveThirtyEight, Kovalchik, WElo, pooled Elo, ranking logistic) | 18,972 ATP; 12,900 WTA | 0.6222 to 0.6334 (ATP) | 0.5984 (ATP) | every interval excludes zero, on both tours | — |

BuildOak is the closest, and the interval says the lead is real, not one lucky season:

![Alcaraz minus BuildOak, paired log loss by season on the same 18,972 ATP matches: ahead in seven of eight seasons.](docs/assets/alcaraz-by-season.svg)

The women's tour runs through the same pipeline with its own history, and the same
registered test ran on 12,900 WTA matches from 2019 to 2024, never pooled with the men's
result. The entry-status block passed again (−0.0012 against the previous version
[−0.0020, −0.0005], 6 of 6 seasons). The BuildOak comparison is inconclusive: −0.0026
[−0.0058, +0.0004], a test with 16% power at the margin seen in 2024. A logit blend of the
two systems, weighted on the three preceding seasons only, scores 0.0024 below Alcaraz
alone [−0.0040, −0.0008] on 7,181 WTA matches from 2022 to 2024; it is published as a
research result, not the default model. Against the market, the women's model trails
Pinnacle by 0.020 on 2,344 matches from 2025–26 (0.6153 against 0.5953).

The IBM row is the smallest sample and the largest gap. IBM does not archive its Grand
Slam "Likelihood to Win" files, but the Internet Archive holds the 37 that visitors saved
(Wimbledon 2023 and 2024, US Open 2022 and 2023); 29 were published before the first
ball, as fixed from the archived order-of-play and point-by-point feeds before any score
was read. On those 29, Pinnacle scores 0.4394. The gap is sharpness, not picks: IBM's
favourite averages 58% and never exceeds 72%, against 68% for Alcaraz, so IBM picks
nearly as well (22 of 29 against 23) while its probabilities score far worse
([details](docs/benchmarks/IBM01_RESULTS.md)). One system could not be run: Green Code's
second model, which its creator reports at 66.3% winner accuracy on the Wimbledon 2025
men's draw; it publishes no match list or probabilities, so a matched comparison is open
work.

## What is in the model

Alcaraz is a histogram gradient-boosting classifier over 57 inputs, refitted each season
on a five-year window and calibrated on the three seasons before the target. The inputs
come in five blocks, and the table above adds them one at a time:

- **Ratings.** Overall and surface Elo from tour results.
- **Match history.** Rankings, recent workload and rest, match format, player traits.
- **Serve and return states.** A dynamic model of each player's serve and return
  strength, updated match by match and adjusted for who they played. This is the block
  that separates a strong run from an easy draw.
- **Lower-tier history (ATP).** Qualifying, Challenger and Futures results and serve
  statistics. It is the largest single gain in the table above because it fills in the years
  before a player reaches the main tour.
- **Draw context.** Each player's entry status (qualifier, lucky loser, wild card,
  protected ranking) and the tournament level, both published with the draw. Round and
  seeding are not used.

The fifth block came out of review. A screen in the independent review of 22 September
found that the model underrated qualifiers: in matches with exactly one qualifier,
qualifiers won 39.5% and the model gave them 34.6%. Entry status had never been an input,
and the qualifying wins behind it are not yet visible at the two-day cutoff. A registered
experiment then added the block and refitted all eight seasons: −0.0011 against the
previous version [−0.0018, −0.0004], 6 of 8 seasons negative.

No price, odds or market field enters the model. Every result, rating and statistic must
be knowable two days before the match date; draw facts such as surface, format, entry
status and level come with the pairing itself. The pipeline records which outcomes each
fold read and refuses anything later.

## Where the lead over public models comes from

The rival forecasts are on disk, so the lead can be taken apart match by match. An
exploratory decomposition of the saved forecasts (post hoc, on development data, no new
model; [details](docs/benchmarks/WHY01_LEAD_DECOMPOSITION.md)) gives four findings.

**The lead is concentrated where a player's main-tour record is thin.** Against BuildOak,
matches with a qualifier, lucky loser or wild card are 35% of the sample and carry 58% of
the gap (−0.0117 [−0.0165, −0.0070]); matches whose lower-ranked player sits at 101–200
carry 45%; matches where a player has fewer than 10 prior main-tour matches carry 29% on
12% of the sample (−0.0164 [−0.0255, −0.0075]). These overlap, because they describe the
same match: a qualifier from outside the top 100 with little tour record. Alcaraz still
leads in the remaining 56% of matches (−0.0041 [−0.0071, −0.0010]) and is level with
BuildOak from the quarter-finals on. The same pattern holds against Ultimate Tennis
Statistics, Ingram and the Elo baselines; the ranking-only baseline is the exception,
because a ranking already reflects lower-tier results.

![Alcaraz minus BuildOak, and the gain from the lower-tier history block, by the less-experienced player's prior main-tour matches: both are largest below 10 matches and fade above 50.](docs/assets/alcaraz-lead-by-history.svg)

**That is the lower-tier history block at work.** On the same matches, the model one step
below it (ratings, match history, serve and return states) is level with BuildOak
(+0.0008 [−0.0013, +0.0030]) and behind it when a player has fewer than 10 tour matches
(+0.0085 [+0.0004, +0.0164]). Adding qualifying, Challenger and Futures history gains
−0.0239 [−0.0321, −0.0158] in those matches and nothing from the quarter-finals on. BuildOak
reads main-tour files only and drops entry status, so neither block has a counterpart
there. The entry-status block's smaller gain sits where expected: matches with a qualifier,
lucky loser or wild card (−0.0025 [−0.0038, −0.0011]) and Grand Slams (−0.0021
[−0.0031, −0.0011]).

**The lead is better ranking of matches, not better calibration, except against Ingram.**
If each rival were perfectly recalibrated on the very outcomes it is scored on, an upper
bound rather than a legitimate forecast, BuildOak's gap would shrink by 14%, Ultimate
Tennis Statistics' by 19% and Ingram's by 48%. What remains is discrimination: Alcaraz's
AUC is higher by 0.008 against BuildOak and by about 0.03 against the other two. BuildOak
is overconfident (recalibration slope 0.89), consistent with a recipe its author selected
on ROC AUC, which rewards ordering and ignores calibration; Ingram's point model is
strongly overconfident (slope 0.62); the Elo baselines are well scaled but over-rate the
older player, as ratings that lag rising players would. Alcaraz's own slope is 1.01. The
past-only calibration stage does its job.

**When the systems disagree, Alcaraz is right slightly more often and pays less when
wrong.** Alcaraz and BuildOak pick different winners in 2,186 matches, 11.5% of the
sample; Alcaraz is right in 1,147, BuildOak in 1,039, and those matches carry a third of
the gap. Where the two probabilities differ by 0.15 or more, BuildOak is the more
confident side and loses more when wrong, and such disagreements are almost twice as
common in thin-history matches. The market is the mirror image: Pinnacle's edge over
Alcaraz is also discrimination, and it concentrates after a long absence from the tour,
in first and second rounds and at Grand Slams, which is where the next section starts.

## Where the remaining gap to the market comes from

Adding any weight of Alcaraz to Pinnacle's price makes the price worse, so the market
already holds everything the model knows. Using the price as a training signal, never as
an input, recovered −0.0007, below the registered gate. An exploratory screen of the gap, not
a registered result, found it concentrated where private information is richest: matches
involving a qualifier, Grand Slams, and players returning from a long absence. Before the
final experiments the estimate was that public statistics could close 0.002 to 0.003 of
the 0.011 gap; the entry-status block took 0.0011 of that, and a registered tuning pass over
110 candidate models found nothing more. The rest is acquisition, not modelling.

For scale, Green Code's Wimbledon 2025 test put the bookmakers' picks at 72% against his
model's 66.3%, by his account. Alcaraz's gap to Pinnacle over eight seasons is 1.2 points
of accuracy and 0.010 of log loss. Different matches, but the same benchmark.

## Registered before scored, reproduced before accepted

Every accepted result was registered before it was scored: the matches, the cutoff, the
inputs, the primary contrast and the pass rule were frozen and hashed first, then scored
once. A second implementation, written separately, reproduced every estimate and interval
before acceptance. Leak detectors enter CI only after failing a planted leak. The
145-entry leaderboard and the 125-entry experiment ledger are published in
`data/registries`, so every attempt, including the failures, is visible. Nothing on disk
is an untouched test set: the 2025–26 seasons were opened once and are development data.

The discipline came out of review. The first version of this project produced plausible
backtests, and independent review found four ways they were wrong:

| What review found | What it would have done | What changed |
|---|---|---|
| Draw-page round order was being turned into match dates | A 2026 Canada final leaked into two later Cincinnati rows | Every date now carries a typed basis: anchor, bound or clock |
| A learned constant was fitted through 2016 and used inside 2014–16 folds | Selection data influenced a "past-only" parameter | Every learned constant carries a horizon receipt |
| A calibration stage wrote scores before the report barrier | Downstream barriers could not stop an upstream scorer | Forecasts are emitted before the barrier, scores after |
| A 24-test leakage suite stayed green when leaks were planted | "All green" meant nothing | A detector enters CI only after it fails its planted control |

[PROCESS.md](docs/PROCESS.md) records each failure and the rule it produced.

## Experiments that did not improve the model

Each was a registered comparison on matched matches. A null here is a result, not an
abandoned idea.

| Tried | Result | Outcome |
|---|---|---|
| Larger boosting head, longer training window | +0.0033 log loss, interval wholly adverse | keep the small model |
| Eight-member stack over the incumbent and alternatives | −0.0004, interval crosses zero | not adopted |
| Uncertainty-aware serve/return states through the final model | +0.0002 | not adopted |
| Serve sub-components, richer state geometry, WTA selection policy | all within ±0.0002 | not adopted |
| Market-as-teacher distillation | −0.0007 against outcome-only | below the 0.003 gate |
| Model + Pinnacle residual | worse than calibrated Pinnacle alone | market already contains the model |
| Past-only logit blend with BuildOak, ATP 2020–24 | −0.0009 [−0.0021, +0.0003] against Alcaraz alone | no ATP blend released |
| One registered tuning pass over the boosted head: 110 candidates with early stopping, tree size, minimum leaf, L2 and bagging | −0.0000 [−0.0004, +0.0003] on 18,972 ATP matches | model frozen |
| Weather, fatigue, point-by-point states | worse or null | retired |

## Run it

```sh
make setup
make reproduce-small
```

That reproduces the full pipeline on a synthetic sample in about a minute, and CI does
the same on every push. The codebase is 53k lines of Python in one pipeline, with 731
tests and a locked environment. Real match history is governed by source terms and stays
out of Git; the accepted model checkpoints are a
[GitHub release](https://github.com/riddlejack/Alcaraz/releases/tag/models-2026-09-14)
with an [inference guide](docs/MODEL_RELEASE.md).

## Scope and limits

- Retrospective research. Two real forecasts have been issued before their scheduled
  start under a [hash-chained ledger](docs/live/README.md); no scored prospective record
  exists yet.
- The model is frozen. The registered tuning pass could have detected a gain of about
  0.0005 and found none, so no further feature or learner search runs on these matches.
  One registration–implementation deviation in the entry-status experiment was caught by
  checking the code against the registration and rerun exactly as registered; both
  attempts are reported
  ([details](docs/benchmarks/BUILDOAK_2017_2024_RESULTS.md)).
- Pinnacle's quote time is unknown, so the market comparison is descriptive.
- The head-to-head rows compare complete systems with different legitimate histories,
  not one algorithm against another on identical inputs. BuildOak's recipe was selected
  by its author with sight of later data; the eight-season design was frozen before its
  scores existed but was not blind to the 2024 result.
- The women's public-model comparison is inconclusive at its sample size, and the
  women's 2025–26 model was not refitted with the entry-status block.

Methods: [METHODS.md](docs/METHODS.md) · Data and licences:
[DATA.md](docs/DATA.md), [DATA_LICENSES.md](DATA_LICENSES.md) · Decisions:
[DECISIONS.md](docs/DECISIONS.md)

Code is MIT. Match, ranking and player data are from Jeff Sackmann / Tennis Abstract
under CC BY-NC-SA 4.0. The XGBoost comparison adapts
[buildoak/tennis-xgboost-autoresearch](https://github.com/buildoak/tennis-xgboost-autoresearch).
