# Lane E campaign v1 executable contract

Status: E01-E08 repaired implementation and generated rehearsal only. No empirical
campaign has been frozen or run, no new real candidate has been fitted, and no
scientific score is reported here. Native T3 integration and the separately qualified
historical bindings remain prerequisites. Passing these checks establishes neither
independent source custody nor predictive validity.

## Frozen procedures

The per-tour population is the unchanged ATP TIER01 aligned primary for 2017–2024 or
the separately qualified WTA01 aligned primary for 2019–2024. S0 is the unchanged
incumbent. S1 is `(S0 + (sigmoid(elo_overall_logit) +
sigmoid(elo_surface_logit))/2)/2` in probability space. S2 has exactly RF50 and RF100
and inherits the incumbent's nonnegative slope fit and candidate selection on the same
three past years. That past criterion is not independent validation. S2's selected or
calibrated probabilities never enter S3.

S3 consumes, in order, result-pooled Elo; HGB 7 leaves/depth 3; HGB 15/depth 4;
ridge C 0.01, 0.1 and 1.0; and random forests with minimum leaves 50 and 100. ATP
tree members use `full_tier`; WTA tree members use `full`; every ridge uses non-tier
`full`. There is no duplicate WTA member. The tree matrix is the existing named
signed/context allowlist. Current or lagged market predictors remain forbidden.

The S3 objective is the equal-year mean Bernoulli log loss plus
`0.001/2 * sum(b^2)`, with `b >= 0`, no intercept, and no sum-to-one constraint.
L-BFGS-B uses float64, initial coefficients 1/8, `maxiter=5000`, `ftol=1e-12`,
`gtol=1e-8`, and a required projected-gradient infinity norm at most `1e-6`. There is
no second slope, penalty search, fallback optimizer, or member dropping.

## Acyclic producer and consumer graph

The executable order is:

`campaign_producer_plan/v1` → `campaign_producer_completion/v1` →
`campaign_consumer_config/v1` → `campaign_forecast_completion/v1` →
`campaign_barrier_completion/v1` → `campaign_report_completion/v1`.

The producer plan is frozen before any member fit. It binds the reviewed anchor,
runtime/code/settings, exact member menu, constructor configurations and their distinct
full `get_params` resolutions, ordered feature
contracts, base windows, raw memberships, selection rules, state/offset requirements,
qualified populations, native disclosure policy, and expected typed inventory. Fits
and caches carry `producer_plan_sha256`; they never carry the later consumer-config
hash. The consumer config is created only after exact producer completion and binds the
plan and completion under distinct names. A real consumer additionally binds a
separate typed independent-review receipt created after those artifacts; that receipt
must name the exact plan, completion, qualification and tour. A status string inside a
locally authored plan is not treated as independent custody.

Every completion has `status=complete` and an exact typed inventory. Keyed artifacts
also carry independently rechecked row counts and membership digests. Missing,
duplicate, failed, extra, escaped, symlinked, untyped, or digest-mismatched artifacts
fail. A local forecast-attempt anchor binds the original forecast completion before the
barrier. This closes ordinary local-rewrite controls; it is not claimed as independent
custody.

Every numerical producer record is parsed and reconciled with the plan and its actual
fit manifest, constructor-config identity and full resolved RF/HGB/ridge settings,
ordered columns, transformed-fit
evidence, training keys/dates, state/offset contents and horizons, model bytes,
prediction keys, and predict-only closure. A failed producer or contradictory wrapper
cannot be admitted. New fits use `origin=new_plan_fit`. Retained HGB/ridge reuse uses
`origin=verified_legacy_native_import` and must bind and parse the original accepted
completion, config/code receipts, unique successful year/member attempt, canonical fit
identity, training keys, fit/model artifacts, exact no-refit primary projection,
truthfully reconstructed transforms, and predict-only replay. It is not relabelled as
a new fit.

`fit_raw_numerical_member(...)` is the production adapter for a new frozen member. Its
caller supplies the validated tour-specific `MemberSpec`, exact `FeatureContract`,
training/prediction tables, labels, actual keyed training dates, the prebound shared
training-membership receipt, fit cutoff, producer-plan hash, state/offset receipts, and
independent prefit-frame assertion. Before cache lookup or fitting, the helper validates
that shared membership's bytes, keys and dates. An observer at the actual
`estimator.fit` call captures the transformed matrix, labels, sample weights and feature
order; cache reuse fails closed if this evidence is absent. The helper then predicts
from that bound model and writes a typed
producer record plus prediction-replay evidence. The campaign command never silently
launches the 40 real RF fits.

## Calendar and fold membership

The exact inherited base window is `max(2011-01-01, s−5-01-01)` through
`s−1-12-30`, inclusive. ATP raw 2014 therefore uses only 2011–2013 and raw 2015 uses
2011–2014; the complete five-calendar-year form begins at raw 2016. Every actual
training key/date and the declared start/end are checked against this window.

Raw prediction-year coverage and outer selection are separate contracts. For outer
year `t`, the S2/S3 rows are the independently qualified Dec-30 subsets of `t−3`,
`t−2`, and `t−1`. A Dec-31 raw prediction remains in the raw inventory but is excluded
from that fold. Receipts bind the actual selected keys, dates, counts and label reads.

## Barrier, native disclosure, and recomputation

Forecast reads labels only for the three qualified earlier subsets. It emits S0–S3,
complete S2/S3 decisions, memberships, convergence diagnostics, and commitments—not
criterion values, target scores, outcome rates, or objectives. The barrier revalidates
the full producer and forecast inventories, actual native policy, both disclosure
sinks, semantic objective absence, and the original forecast completion before freezing
the complete trees.

The native SR03 config must set
`calibration.fit_disclosure_policy=campaign_commit_objective_defer_value`. Both
`fit_events.jsonl` and `fits.json` omit the numeric objective before either write and
carry the canonical full-record commitment. Campaign-policy sports prediction does not
parse or normalize market quotes and writes no price values. Historical configurations
omit the policy and retain their legacy numerical and serialization behavior.

Native campaign-policy `evaluate` requires `--barrier-completion`. It loads the bound
consumer config from that barrier, reruns barrier verification, checks that the plan
binds the supplied native config and both sinks, reconciles both sink commitments,
then recomputes and discloses objectives. A missing barrier or either-sink drift fails
before component scoring.

Report and verify reconstruct every saved S0–S3 key, edition, probability, S2
selection/slope, and S3 coefficient receipt from the bound incumbent/raw inputs before
scoring. Verification also rederives every persisted report CSV, JSON and Markdown
payload from the bound forecasts, outcomes and quotes, so a coherently rehashed score
or summary is rejected. A coherently rebound local forecast is still rejected by
recomputation.

## Reports, prices, and interpretation

Primary is S3−S0 by tour. S1−S0, S2−S0 and S3−S2 remain visible. The primary estimand
is the arithmetic mean of annual paired mean log-loss deltas. Its interval resamples
whole tournament editions within each year, uses the sampled match-weighted annual
mean, averages years equally, and reports the 2.5% and 97.5% linear quantiles from
2,000 PCG64 replicates at seed 20260914. It is conditional on saved forecasts and
excludes fitting, selection and coefficient uncertainty.

Only S3 can satisfy the descriptive nomination screen: delta at most −0.002, negative
in at least 6/8 ATP or 5/6 WTA years, and interval upper endpoint below zero. This can
only nominate a later manually designed prospective batch; it never promotes a model.

The full sports membership never depends on price availability. A separately qualified
priced subset binds two raw decimal quotes per priced key plus source-path, source-row
and source-hash provenance. Only after the barrier does report validate the quotes,
normalize them, verify the exact priced subset, and compare all displayed models on
the same keys. The full historical population is market-source-conditioned and quote
clocks are unequal or unresolved; these market comparisons remain descriptive.

Persisted outputs include full-sports and priced clip counts, score-only
leave-one-year-out and leave-2020-out sensitivities, annual degrees of freedom, the
complete attempt inventory, fit criteria, exact recomputation receipts, bootstrap rows,
calibration, summaries, exposure, and the short report.

## Public generated rehearsal

The rehearsal creates no real tennis inputs and fits no candidate. It first qualifies
the generated populations, freezes the producer plan, writes deterministic raw
artifacts, completes their exact inventory, then freezes the consumer config. Synthetic
receipts explicitly say local consistency is not independent custody.

```bash
uv run python tools/campaign_rehearsal.py --root work/campaign_e_v1/rehearsal
uv run tennislab campaign forecast --config work/campaign_e_v1/rehearsal/config.json --output work/campaign_e_v1/rehearsal/run
uv run tennislab campaign barrier --config work/campaign_e_v1/rehearsal/config.json --output work/campaign_e_v1/rehearsal/run
uv run tennislab campaign report --config work/campaign_e_v1/rehearsal/config.json --output work/campaign_e_v1/rehearsal/run
uv run tennislab campaign verify --config work/campaign_e_v1/rehearsal/config.json --output work/campaign_e_v1/rehearsal/run
```

Use `--tour WTA` with a fresh root for the exact WTA 2016–2024 raw and 2019–2024
target-year graph. The real interface additionally requires independently qualified
ATP/WTA bindings, a reviewed original producer completion, final empirical freeze, and
`--execute-frozen-real`. A failed stage writes a new numbered receipt and never
overwrites the failed attempt. The bounded real campaign later completed under separate
execution authority and was independently accepted as negative/inconclusive; see
[`CAMPAIGN_E_RESULTS.md`](CAMPAIGN_E_RESULTS.md). It produced no nomination or automatic
promotion.
