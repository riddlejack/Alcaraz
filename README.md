# Alcaraz

**Gradient-boosted tennis forecasts, built from 20 years of match history.** Alcaraz predicts men's (ATP) and women's (WTA) match outcomes with calibrated histogram gradient boosting. It combines opponent-adjusted Elo ratings, rankings, surface and workload with dynamic serve/return strength—and brings qualifying, Challenger and Futures results into the men's model.

The men's pipeline uses **51,222 main-tour matches from 2005–2024**, **480,012 eligible lower-tier results**, and **24.2 million service points** reconstructed from match-level serve statistics. The separate women's history covers **2007–2026**, including a partial 2026 season.

Models are trained and selected on earlier seasons, then tested on later matches. Alcaraz recorded lower log loss than all five tested ranking/Elo baselines on **18,972 ATP and 12,900 WTA matches**. The code, full trained weights and comparison results are available below. These are retrospective backtests; broader comparisons are still underway.

## Model comparisons

**Accuracy** is the percentage of correct winner picks. **Log loss** also grades confidence and penalizes confident mistakes; **lower is better**. Every comparison below uses the same matches for both systems. Different tables cover different test populations.

### ATP 2024 · 2,681 matches

| System | Accuracy ↑ | Log loss ↓ |
|---|---:|---:|
| **Alcaraz · gradient boosting + full-tier history** | **66.17%** | **0.59649** |
| [buildoak XGBoost system · historical adaptation](docs/benchmarks/BUILDOAK_2024_RESULTS.md) | 66.06% | 0.60004 |
| [Ultimate Tennis Statistics · formula adaptation](docs/benchmarks/EXTERNAL_2024_2025_RESULTS.md) | 64.60% | 0.62087 |

The XGBoost lead is small and statistically inconclusive. These adaptations retain their own forecasting methods and documented source histories; they do not reproduce the authors' original headline experiments.

### ATP clay events, 2025 · 99 matches

| System | Accuracy ↑ | Log loss ↓ |
|---|---:|---:|
| **Alcaraz · reconstructed historical forecasts** | **62.63%** | **0.63330** |
| [Faxulous TennisGNN · retained dated forecasts](docs/benchmarks/EXTERNAL_2024_2025_RESULTS.md) | 52.53% | 0.72061 |

A dated subset of Monte Carlo, Madrid, Rome and Roland-Garros—not the GNN author's full reported test set. The small sample and source-timing limits constrain the conclusion.

### Multi-season ranking and Elo benchmarks

ATP: **2017–2024, 18,972 matches**. WTA: **2019–2024, 12,900 matches**. Accuracy counts matches; log loss gives each season equal weight. Baseline probabilities are calibrated using earlier seasons.

| System | ATP accuracy ↑ | ATP log loss ↓ | WTA accuracy ↑ | WTA log loss ↓ |
|---|---:|---:|---:|---:|
| **Alcaraz · accepted model** | **66.51%** | **0.59836** | **65.79%** | **0.61106** |
| Pooled Elo | 64.57% | 0.62222 | 64.44% | 0.62548 |
| Ranking logistic model | 63.26% | 0.63343 | 63.60% | 0.63814 |
| Kovalchik Elo reconstruction | 64.30% | 0.62682 | 64.79% | 0.62289 |
| FiveThirtyEight surface-Elo adaptation | 64.77% | 0.62295 | 65.05% | 0.62123 |
| Weighted Elo reconstruction | 64.32% | 0.62608 | 64.61% | 0.62326 |

[Methods, uncertainty and exact results →](docs/benchmarks/G_L_RESULTS.md)

<details>
<summary>Additional models and feature-layer experiments</summary>

Same multi-season populations and weighting as above. These are completed Alcaraz experiments, separate from external systems.

| Model | ATP accuracy ↑ | ATP log loss ↓ | WTA accuracy ↑ | WTA log loss ↓ |
|---|---:|---:|---:|---:|
| Accepted gradient-boosted model | 66.51% | 0.59836 | 65.79% | 0.61106 |
| Fixed model + Elo blend | 66.09% | 0.60513 | 65.72% | 0.61477 |
| Selected random forest | 66.62% | 0.59961 | 65.63% | 0.61300 |
| Eight-member learned ensemble | 66.58% | 0.59794 | 66.03% | 0.61174 |

No alternative met the predeclared replacement criteria. The ensemble's small ATP log-loss improvement was inconclusive; higher winner accuracy alone did not determine the default. [Full experiment →](docs/CAMPAIGN_E_RESULTS.md)

#### Feature ladder

These older matched cohorts contain 18,882 ATP matches (2017–2024) and 2,344 WTA matches (2025–2026). Both metrics weight matches equally. The WTA 2026 contribution is only 101 matches.

| Tour | Model inputs | Accuracy ↑ | Log loss ↓ |
|---|---|---:|---:|
| ATP | Elo only | 64.55% | 0.62369 |
| ATP | Base statistics + gradient boosting | 65.40% | 0.61210 |
| ATP | + player traits and dynamic serve/return strength | 66.22% | 0.60534 |
| ATP | + lower-tier history | 66.51% | 0.59843 |
| WTA | Elo only | 64.61% | 0.62648 |
| WTA | Base statistics + gradient boosting | 64.63% | 0.62301 |
| WTA | + player traits and dynamic serve/return strength | 66.13% | 0.61531 |

[Annual accuracy](docs/winner_accuracy.csv) · [Full ladder](docs/RESULTS.md)

</details>

## Use the models

[**Download accepted models**](https://github.com/riddlejack/alcaraz/releases/tag/models-2026-09-14) · [Experimental model bundle](https://github.com/riddlejack/alcaraz/releases/tag/campaign-e-research-models-2026-09-15) · [Inference guide](docs/MODEL_RELEASE.md)

The accepted download includes all 40 trained checkpoints and calibration parameters. The experimental bundle preserves all 140 fitted estimators and combination decisions. Private source rows are excluded; model weights are not reduced. Player-level forecasting requires the [qualified history workflow](docs/live/README.md).

[Methodology](docs/METHODS.md) · [System design and development](docs/PROCESS.md) · [Data scale and table provenance](docs/benchmarks/LANDING_PAGE_FACTS.json)

Inspired by Green Code’s tennis-prediction videos. Code: **MIT**. Match, ranking and player data: **Jeff Sackmann / Tennis Abstract**, with source terms and additional attribution in [DATA_LICENSES.md](DATA_LICENSES.md).
