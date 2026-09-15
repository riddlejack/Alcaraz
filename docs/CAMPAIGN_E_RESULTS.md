# Lane E four-arm campaign result

Status: independently accepted historical result; campaign closed negative/inconclusive.
The incumbent remains the default. No model was nominated or promoted.

## What was tested

The frozen campaign compared four saved forecast arms on outcome-exposed historical
development populations:

- **S0:** the unchanged incumbent selected and calibrated HGB forecast;
- **S1:** a fixed equal-probability blend of S0 and result Elo;
- **S2:** one of two random-forest candidates, selected and calibrated on the preceding
  three years only;
- **S3:** a nonnegative logit stack over eight fixed raw members, fitted on the preceding
  three years only.

The registered primary contrast was S3 minus S0. Negative score differences favor S3.
The primary estimand gives each target year equal weight; the interval resamples whole
tournament editions within each year while holding all saved forecasts fixed.

## Verified result

| Tour / target years | Paired matches | Equal-year log-loss delta | Match-weighted delta | Negative years | Conditional 95% interval | Nomination |
|---|---:|---:|---:|---:|---|---|
| ATP / 2017-2024 | 18,972 | -0.0004187360339825443 | -0.0004471044027305742 | 7/8 | [-0.001059224503677754, 0.0001928662692131596] | No |
| WTA / 2019-2024 | 12,900 | 0.0006742605931336596 | 0.0002339609152100709 | 4/6 | [-0.0005395152406032511, 0.002251420502405363] | No |

ATP's S3 point estimate is slightly better than S0, but the interval crosses zero and
the effect misses the registered `-0.002` threshold. WTA's S3 point estimate is worse
than S0. Neither tour passes the complete effect, annual-sign, and interval screen.

The secondary equal-year log-loss contrasts remain visible:

| Contrast | ATP | WTA |
|---|---:|---:|
| S1 minus S0 | 0.00677196868571675 | 0.003711525723424865 |
| S2 minus S0 | 0.001255922151620988 | 0.001938032855702627 |
| S3 minus S2 | -0.001674658185603532 | -0.001263772262568967 |

S1 and S2 underperform S0 on both tours. S3 improves on S2 on both tours, but S3 versus
S0 was the registered primary question.

On the separate priced subsets, normalized Pinnacle log loss was lower than S3 by
`0.01126747882807921` for ATP (18,882 matches) and `0.0203026354502378` for WTA
(12,785 matches), using the equal-year grain. Those comparisons are descriptive: quote
clocks are unequal or unresolved and the population is conditioned on market-source
coverage.

## Independent acceptance

Root decision D95 accepts and closes this bounded campaign as negative/inconclusive,
retains the incumbent default, and permits this aggregate-only public integration.
The independent reviewer reproduced the exact D93/D94 result with separate arithmetic,
without importing the production scorer, loading the base models, refitting, or rerunning
an optimizer. The review covered all 4,000 bootstrap replicates, 28 S2/S3 criterion
commitments, 42 selection memberships, and 127,488 recombined target probabilities.
It also used a coherently rehashed altered-summary control: file hashes passed while the
independent score calculation rejected the planted value.

- Independent review: `LANE_E_D93_D94_RESULT_REVIEW.md`, SHA-256
  `4e872a983d79721d3262924b0367c655c2d290c44608ddcf10fae84f7b9d8119`.
- Executor report: `LANE_E_D93_D94_CONSUMER_EXECUTION_RESULT.md`, SHA-256
  `9de71fc5de09289912fe7da12376cab1340838c84ce64d645bbcc35845432d66`.

The original execution chronology is part of the result. D93 completed ATP forecast and
barrier, then failed closed at report because the retained source workbooks were absent
from the isolated consumer workspace. The 210-byte failure receipt and invocation remain
preserved. D94 materialized the exact 14 source files, ran the sole authorized ATP report
retry, verified ATP, and then completed the four WTA stages. It did not refit or change a
model, configuration, quote, or source.

## Interpretation limits

This is a verified retrospective campaign result, not prospective evidence. The target
populations were already exposed during development. Years share players and training
histories, and the interval conditions on saved forecasts: it excludes uncertainty from
base fitting, nuisance calibration, S2 selection, and S3 coefficients. Historical source
availability, inherited reported-date uncertainty, and outcome-assisted WTA rule
provenance remain material limitations.

The result closes this bounded campaign. It does not support a betting edge, worldwide
or state-of-the-art superiority, another search, or a new default. The evaluated weights
may later be distributed as separately labeled research artifacts, but they are not a
promoted model release.
