# tennis-lab

**How far can public tennis statistics take a pre-match forecast?** tennis-lab builds a
chronological answer: start with a simple rating, add recent match context and
serve/return history, then test whether richer player and lower-tour histories improve
the probabilities.

On the same priced retrospective matches, the final ATP model picked 12,559 of 18,882
winners (66.51%) and the final WTA model picked 1,550 of 2,344 (66.13%). The richer models
also improved pooled probability quality at every step of the accepted ladder, but the
observed Pinnacle market reference still had lower log loss. These are exposed development
results, not a betting system, a claim of state-of-the-art performance, or prospective
evidence.

## How often did the model pick the winner?

A forecast picks player A when its probability is above 50% and player B when it is below
50%. An exact 50% forecast is reported as a tie. The final ATP and WTA sports models had
no ties on these matched cohorts, so accuracy here is simply `correct / n`.

### ATP — men's tour, full-tier model

| Target year | Matches | Correct | Ties | Accuracy |
|---|---:|---:|---:|---:|
| 2017 | 2,311 | 1,543 | 0 | 66.77% |
| 2018 | 2,587 | 1,708 | 0 | 66.02% |
| 2019 | 2,491 | 1,645 | 0 | 66.04% |
| 2020 | 1,241 | 835 | 0 | 67.28% |
| 2021 | 2,384 | 1,597 | 0 | 66.99% |
| 2022 | 2,525 | 1,694 | 0 | 67.09% |
| 2023 | 2,672 | 1,771 | 0 | 66.28% |
| 2024 | 2,671 | 1,766 | 0 | 66.12% |
| **Overall** | **18,882** | **12,559** | **0** | **66.51%** |

### WTA — women's tour, full model

| Target year | Matches | Correct | Ties | Accuracy |
|---|---:|---:|---:|---:|
| 2025 | 2,243 | 1,477 | 0 | 65.85% |
| 2026 partial sample | 101 | 73 | 0 | 72.28% |
| **Overall** | **2,344** | **1,550** | **0** | **66.13%** |

The 2026 row is only 101 priced matches from an incomplete, already-exposed development
window—not a full season or a fresh test. Accuracy was calculated from saved forecasts
and labels on the exact same annual cohorts as the accepted model ladder; nothing was
refit or reselected. [`docs/winner_accuracy.csv`](docs/winner_accuracy.csv) and
[`docs/winner_accuracy.json`](docs/winner_accuracy.json) report every ladder rung and the
market reference with `n`, correct picks, exact ties, and accuracy. For models with ties,
the generated reports preserve the full cohort and give each tie half credit.

Regenerate those aggregate-only files from a local copy of the research archive:

```sh
TENNISLAB_ARCHIVE=/path/to/tennis-research-lab-archive \
  uv run python tools/render_winner_accuracy.py
```

## Why log loss is still the main score

Accuracy only asks which side of 50% a forecast chose: 51% and 99% are the same winner
pick. Log loss also grades confidence, rewarding well-calibrated probabilities and
penalising confident mistakes. A model that says 50/50 for every match scores
`ln(2) ≈ 0.693`; lower is better.

| Tour and target years | Matched matches | Elo | base | full | full tier | Pinnacle |
|---|---:|---:|---:|---:|---:|---:|
| ATP, 2017–2024 | 18,882 | 0.6237 | 0.6121 | 0.6053 | 0.5984 | 0.5873 |
| WTA, 2025–2026 | 2,344 | 0.6265 | 0.6230 | 0.6153 | — | 0.5953 |

These are match-weighted log losses on identical priced cohorts. Pinnacle is an observed
market reference: annual bookmaker odds were converted to probabilities and rescaled to
remove the quoted overround. The underlying files do not contain verified quote times,
so the market observation may include information that arrived later than the model's
cutoff. This is a useful comparison, not a synchronized contest or evidence of market
efficiency.

![ATP full-tier model and normalised Pinnacle log loss by year](docs/assets/atp_full_tier_vs_market.svg)

The full generated log-loss report is in [`docs/RESULTS.md`](docs/RESULTS.md), with
machine-readable values in [`docs/ladder.json`](docs/ladder.json).

## What the model names mean

- **ATP** is the men's tour; **WTA** is the women's tour.
- **Elo** is a rolling strength rating. This version averages overall and
  surface-specific win probabilities and does not fit a machine-learning model.
- **base** combines past ratings, rankings, workload, match context, and available
  serve/return counts with a boosted set of decision trees.
- **full** adds player traits and serve/return states that update match by match.
- **full tier** is ATP-only. It adds qualifying, Challenger, and Futures history to the
  full model.

Each target year is walked forward using earlier seasons for fitting and selection. The
years share players, data, and model ancestry, so they show stability across seasons—not
independent replications.

## What is reproducible today

The public repository includes the full model-building and evaluation code,
configurations, aggregate results, and synthetic acceptance samples. It is not yet a
ready-to-use prediction app. A local release package is being assembled for 40 accepted
year-specific boosted-tree checkpoints, their learned calibration slopes, and the Elo
state, but that package has not been uploaded. Even with those weights, forecasting a
match from two player names still requires prepared history, ratings, rankings,
serve/return dynamics, and ATP lower-tier feature state that are not bundled today.

Exact historical reconstruction therefore still requires the separate research archive.
The accepted manual workflow currently demonstrates Elo issuance on synthetic controls
only; a bound real-history, six-rung package remains pending. See
[`docs/ARCHIVE.md`](docs/ARCHIVE.md) and [`docs/live/README.md`](docs/live/README.md).

The reconstruction also records outcome reads, separates forecasting from scoring,
re-hashes evidence manifests, and tests selected integrity rules with planted defects.
Those checks are deliberately scoped. [`docs/METHODS.md`](docs/METHODS.md),
[`docs/PROCESS.md`](docs/PROCESS.md), and [`docs/INTEGRITY.md`](docs/INTEGRITY.md) explain
the chronology, failures, repairs, and remaining limits.

## Current evidence status

- **Retrospective results:** reconstructed and accepted within the documented scope.
- **Prospective results:** none. No real forecast batch has been issued before play and
  later scored under a frozen rule.
- **Data horizons:** ATP uses a 2005–2024 panel with 2017–2024 targets. WTA uses a
  2007–2026 panel with 2025–2026 targets; that short, exposed window includes known
  chronology limitations. [`docs/DATA.md`](docs/DATA.md) separates acquisition,
  qualification, and actual model use.
- **Hosted CI:** GitHub Actions run
  [`34909582080`](https://github.com/riddlejack/tennis-lab/actions/runs/34909582080)
  passed on exact commit `db7ff2cfa26fe68f420cb1cdbb5531ac2d8c3557`. A later commit
  should not be inferred green until its own run completes.

## Run the engineering harness

Python 3.14.6 is required by the locked environment.

```sh
make setup
make test
make reproduce-small
make reproduce-tier
```

The two reproduction samples invoked above are synthetic engineering checks; they do not
measure predictive performance on real tennis.

## Data and licence

Code is MIT-licensed. Historical match, ranking, and player data is credited to
[Jeff Sackmann / Tennis Abstract](https://github.com/JeffSackmann) under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Other source and
redistribution boundaries are listed in [`DATA_LICENSES.md`](DATA_LICENSES.md).
