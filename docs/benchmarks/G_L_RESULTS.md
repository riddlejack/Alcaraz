# Historical comparison with ranking and Elo models

**Tennis Lab had lower log loss than all five tested baselines on both tours.** A separate
review implementation reproduced the saved scores and uncertainty calculations. This is a
comparison of specified implementations on historical data, not a claim to lead every public
tennis model or reproduce the forecasts originally published by those services.

Men: 18,972 ATP matches, 2017–2024, using the accepted full-tier model. Women: 12,900 WTA
matches, 2019–2024, using accepted WTA01 full. All models within each column use the same
matches. Each season has equal weight, so a busier year cannot dominate the result. These
women’s years and this averaging rule differ from the newer priced-match table in the README.

Lower log loss is better: it rewards probabilities that put more confidence on the eventual
winner and penalizes confident mistakes. Earlier seasons determine each model’s calibration.

| Implemented model | ATP log loss | WTA log loss |
|---|---:|---:|
| Tennis Lab: ATP full-tier / WTA full | 0.5984 | 0.6111 |
| Pooled Elo (K=32) | 0.6222 | 0.6255 |
| Ranking-based logistic model | 0.6334 | 0.6381 |
| Kovalchik overall/major Elo reconstruction | 0.6268 | 0.6229 |
| FiveThirtyEight surface-Elo adaptation | 0.6230 | 0.6212 |
| Weighted Elo (WElo) reconstruction | 0.6261 | 0.6233 |

## What the comparison establishes

The five probability-score differences favor Tennis Lab on each tour. The planned 95%
intervals account for the five comparisons together and resample consecutive calendar weeks
to reflect some dependence between matches. Every interval excludes zero, including the
declared 4-, 8- and 13-week settings. Removing any one season from the saved predictions
keeps the direction of every comparison. Brier scores also favor Tennis Lab; no separate
Brier significance test was performed.

The comparison evaluates complete systems with different inputs. ATP full-tier includes
lower-tier history, while the rating baselines receive the declared main-tour history. This
does not isolate the effect of the learning algorithm from the benefit of additional history.
The earlier full-tier experiment separately compared adding that history within our own
pipeline. Neither result identifies a universal advantage over other modeling approaches.

The intervals condition on the already fitted forecasts and the chosen week-based dependence
model. They do not include uncertainty from fitting, choosing features/models, or source
selection. The historical periods are exposed development data; independent arithmetic
reconstruction does not make them a new holdout.

## Pinnacle and models outside this benchmark

On the separate priced subsets (18,882 ATP and 12,785 WTA), probabilities derived from
Pinnacle’s odds still score better than Tennis Lab. Pinnacle is a sportsbook; the recorded
quotes lack verified timestamps and may contain later information. Those comparisons are
descriptive and are excluded from the five-baseline uncertainty tests.

Ingram’s point-based Bayesian model, other public-feature machine-learning systems, and
Ultimate Tennis Statistics were not admitted with a complete dated reconstruction contract.
Their absence is not evidence that Tennis Lab beats them. This bounded result supports
“better than the five tested ranking/Elo baselines,” not “state of the art.”

## Evidence and reproduction

The [machine-readable result](G_L_RESULTS.json) is the exact aggregate report, including
annual/pooled raw and calibrated scores, matched priced results, intervals, exclusions,
fallback counts and season-removal checks. It contains no raw match or odds rows.

The frozen [design](G_LEGACY_DESIGN.md), [repair contract](G_REPAIR_CONTRACT.md) and
[successor corrections](G_REPAIR_SUCCESSOR_ADDENDUM.md) describe the procedures and source
equations. Those documents preserve their pre-execution status; this accepted result is the
later disposition. Models and input contracts were frozen before this single comparison.

The independent reviewer used a standalone script importing no Tennis Lab calculation
helpers. All eight score tables matched exactly; twelve bootstrap streams matched within
4.30e-13 with identical seeds, draw counts and interval signs. Its 1,927 scoped checks include
byte/arithmetic negative controls, membership and receipt consistency. This was a separate
coding-agent reconstruction in the same local project, not external peer review or
independent holdout custody. It did not refit models.

| Evidence identity | SHA-256 / Git commit |
|---|---|
| Execution source commit | `250220af578c4ca6251dfa204eba71df597de8a5` |
| Frozen invocation config | `b315eaef74ec63b5b89afff4d9ddfa77c5103465f4a9be2351bbda3b0db1163f` |
| Effective config | `8228d2756572dc03e78abfab54989de8c30fa844b9c1f1d95ac746cb3da87945` |
| Saved aggregate report | `734b1234b07823744c2323d95d8ea81a4fae18b59b564ec44a0f0a9094986d2f` |
| Independent result review | `7a84d26c3db5ae84ec46ddea04e34a1623851605880d68580f16ff2abeb1660b` |
| Standalone review script | `c6946733390ec1c6b04965878da99497a5519a61a35b0bf60440af1b2d1be6cc` |

The full source data and row-level reconstruction inputs remain in the private research
archive under their source terms. Hashes identify retained evidence; they do not grant
access to that archive or prove source timing. No new real benchmark run is part of this
publication. No model was promoted or replaced.
