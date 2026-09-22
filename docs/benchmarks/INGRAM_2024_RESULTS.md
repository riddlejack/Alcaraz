# ATP 2024: comparison with the Ingram Bayesian point model

Tennis Lab's saved accepted forecast scored better than an unchanged-model
adaptation of the Ingram Bayesian tennis model on the same 2,681 ATP matches.
The difference is large relative to the registered fixed-forecast uncertainty,
but this is exposed retrospective evidence and does not establish prospective
or universal superiority.

| Measure | Tennis Lab, saved accepted forecast | Ingram raw posterior forecast |
|---|---:|---:|
| Matches | 2,681 | 2,681 |
| Log loss — lower is better | 0.596486 | 0.641705 |
| Brier score — lower is better | 0.206223 | 0.222210 |
| Winner accuracy | 66.17% | 63.48% |

The paired log-loss difference, Tennis Lab minus Ingram, is **−0.045219**.
Its registered stationary calendar-week bootstrap intervals exclude zero at
mean block lengths four, eight and thirteen weeks. The primary eight-week 95%
interval is **[−0.056486, −0.035027]**. Leaving out any one of the six fitting
periods also preserves the direction, with differences from −0.040205 to
−0.050942.

## What was compared

This is a full-system comparison, not an equal-input algorithm isolation. The
external side keeps the paper-equation adaptation, priors, sparse
marginalization, six chronological fit boundaries, raw history, source seeds
and no-extra-calibrator choice frozen before recovery. It uses four chains,
1,000 warmup draws and 4,000 retained draws per chain. The increase from the
failed predecessor's 1,000 retained draws was the only sampler change.

Tennis Lab uses its unchanged saved accepted forecast. The two accepted source
columns are byte-identical on this cohort and are therefore one forecast
carrier, not distinct calibrated and raw model results.

The adaptation is not a reproduction of an original-author forecast. Its
historical source and date assumptions, full-system inputs and cleaning differ
from Tennis Lab's. The comparison cannot identify whether model structure,
data, chronology or another system component caused the observed difference.

## Numerical and scoring verification

An independent read-only reconstruction reproduced the six trace diagnostics,
hash chain, exact coverage, point metrics, leave-one-period-out comparisons and
all 15,000 stationary-week bootstrap draws. All six period fits passed the
unchanged hard gates: maximum R-hat was
1.005851, minimum bulk ESS 1,177.976, minimum tail ESS 2,580.956, zero
divergences, maximum prediction MCSE 0.002885, maximum swap-complement error
1.33e-15 and valid probabilities. Each period retained 16,000 post-warmup
transitions. No automatic retry or parameter/period exclusion occurred.

The full forecast was committed before label access. The score uses the fixed
paired log-loss, Brier, half-credit-at-0.5 accuracy and stationary-week
bootstrap plan. The cohort and research process were already outcome-exposed;
the intervals condition on saved forecasts and do not include source-choice or
research-path uncertainty. This is one ATP season, not a live record, WTA
comparison or state-of-the-art claim.

Machine-readable aggregates and evidence hashes: [ingram_2024.json](ingram_2024.json).
