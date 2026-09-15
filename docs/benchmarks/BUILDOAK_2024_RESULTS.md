# ATP 2024: comparison with a public XGBoost system

Tennis Lab scored slightly better than a historical adaptation of
[buildoak/tennis-xgboost-autoresearch](https://github.com/buildoak/tennis-xgboost-autoresearch/tree/237d1e7ae020de062a994dd7f987881fa2c9a795)
on the same 2,681 ATP matches. The uncertainty interval includes zero: this test does
**not** establish a decisive advantage over that system.

| Measure | Tennis Lab, accepted full-tier model | External XGBoost adaptation |
|---|---:|---:|
| Matches | 2,681 | 2,681 |
| Log loss — lower is better | 0.596486 | 0.600044 |
| Brier score — lower is better | 0.206223 | 0.207701 |
| Winner accuracy | 66.17% | 66.06% |

The paired log-loss difference, Tennis Lab minus external, is **−0.003558**.
Its 95% interval is **[−0.011207, +0.003013]**, using 5,000 stationary calendar-week
bootstrap samples with mean block length eight. Lengths four and thirteen also produce
intervals crossing zero. These intervals condition on the saved forecasts; they do not
account for the full history of research and source choices.

Every match received a native external prediction; the registered fallback was never
used. Excluding retirements and other non-completed outcomes leaves 2,604 matches, with
log loss 0.592442 versus 0.597154. Removing any single tournament edition preserves the
direction of the overall point estimate. These checks do not turn an inconclusive
interval into proof of superiority.

## What was compared

This compares complete forecasting systems. The external system retains its own
1985–2024 history, feature formulas, augmentation, preprocessing and applicable blend.
It fitted a 900-tree global XGBoost model and an 800-tree tour-level model using data
through December 30, 2023. Its recent-history and additional segment models did not meet
the source code's activation thresholds. There were 126,483 native fitting rows and
447 ordered input columns before native preprocessing. Tennis Lab used its unchanged
accepted, calibrated ATP full-tier forecasts. No extra external calibrator was fitted.

The adaptation makes historical prediction cutoffs explicit. State continues to update
within 2024 when a result becomes eligible. Where sources arrive out of chronological
order, the native state is replayed in chronological order. Neutral player orientation,
a training-only country vocabulary and fit-boundary Elo reference prevent specific
future-information paths in this adaptation.

Some historical dates are reported match-date proxies. Older unresolved events use
explicit delayed-release assumptions. These are not verified match-completion or
publication timestamps, and the two systems retain different source histories and
cleaning. The test is neither an exact reproduction of the author's original result
nor an experiment isolating algorithms on identical inputs.

## Verification and limits

The execution ran in a restricted container with no network or host filesystem mounts.
Before scoring, an independent check verified the frozen source/input hashes, exact
match memberships, fitted constructor settings, ordered feature columns and resource
receipts. A separate implementation then reproduced the headline scores, orientation
joins and all three uncertainty intervals.

The cohort and model development were already outcome-exposed. This is one historical
season, not a live forecast record, an untouched final test, a WTA comparison or a
state-of-the-art claim. Other shortlisted comparisons remain pending.

Machine-readable aggregates and evidence hashes: [buildoak_2024.json](buildoak_2024.json).
