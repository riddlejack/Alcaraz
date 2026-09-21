# WTA 2024: comparison with a public XGBoost system

Alcaraz and a historical adaptation of
[buildoak/tennis-xgboost-autoresearch](https://github.com/buildoak/tennis-xgboost-autoresearch/tree/237d1e7ae020de062a994dd7f987881fa2c9a795)
were scored on the same **2,404 WTA 2024 matches from 55 event editions**.
The comparison is **inconclusive**: Alcaraz has the lower log-loss and Brier
point estimates, while the external adaptation makes 14 more correct winner
picks. Every primary paired interval crosses zero. No model or default changed.

| Measure | Alcaraz WTA01 full | External XGBoost adaptation |
|---|---:|---:|
| Matches | 2,404 | 2,404 |
| Log loss — lower is better | 0.604022 | 0.605039 |
| Brier score — lower is better | 0.209406 | 0.209741 |
| Winner accuracy | 65.5158% | 66.0982% |
| Correct picks | 1,575 | 1,589 |

Differences are Alcaraz minus external: negative favors Alcaraz for loss scores;
positive favors Alcaraz for accuracy.

| Paired difference | Estimate | 95% interval |
|---|---:|---:|
| Log loss (primary) | -0.001017 | [-0.005715, +0.003742] |
| Brier score | -0.000335 | [-0.002418, +0.001748] |
| Accuracy, percentage points | -0.582363 | [-1.932586, +0.685692] |

Intervals use 5,000 paired stationary calendar-week bootstrap draws with a
mean block length of eight weeks. Four- and thirteen-week sensitivity intervals
also cross zero for all three measures. They condition on the saved forecasts;
they omit refitting, source-choice, recipe-selection, and accumulated
research/selection uncertainty.

## Scope and limits

Every qualified match received a native external prediction; no fallback was
used. The two systems retain different source histories and cleaning, so this
is a complete-system comparison—not an equal-input algorithm experiment or a
reproduction of the source author's published headline result. The external
recipe selection, and this historical cohort, were already outcome-exposed.
Historical release timing partly relies on reported-date and delayed-release
proxies rather than verified pre-play publication times.

An independent implementation reconstructed the key membership, orientations,
headline metrics, and all registered interval endpoints from committed
forecasts. That supports this bounded retrospective result; it does not create
prospective evidence, a market claim, or a state-of-the-art claim.

Machine-readable public-safe aggregate: [buildoak_wta_2024.json](buildoak_wta_2024.json).
