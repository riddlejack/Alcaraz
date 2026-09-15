# D2 real-snapshot readiness

This is a preparation boundary, not a snapshot acceptance. `tennislab readiness` is a
read-only check: it does not acquire a source, advance `latest.json`, fit or select a
model, issue a forecast, or write to the prospective ledger.

## Reproducible check

```sh
uv run tennislab readiness --config configs/live/live.json
```

To verify the separately distributed accepted incumbent package and exercise each bound
prepared-row interface without outcomes:

```sh
uv run tennislab readiness \
  --config configs/live/live.json \
  --model-bundle /path/to/tennislab-accepted-models-2026-09-14-r2
```

The report verifies what is present and names what is absent:

- each ATP/WTA history path and SHA-256 binding;
- the corrected-panel replay schema, typed publication/receipt timestamps and admitted
  completion bases;
- counts withheld for unresolved overlap, unadmitted completion basis, non-played status
  or duplicate match identity;
- the latest version pointer, normalized tables, acquisition receipts and tour coverage;
- the accepted release identity, complete payload inventory and exact per-rung years;
- one asymmetric, outcome-free prepared-row interface probe for every trained rung;
- each trained route's history, BIO, ranking, SR02 selection and lower-tier bindings;
- the ledger chain, settlement barrier and estimand.

The five trained snapshot-to-feature routes are implemented. The committed configuration
still reports `pending` because the public repository deliberately leaves the real
history, ranking, BIO, SR02 and tier paths unbound, no accepted live snapshot version is
present, and the model bundle is distributed separately. `route_implemented` records
working code; it does not promote a rung to live-ready.

The ATP routes apply the accepted 2024 checkpoint to a 2026 fixture under frozen decision
D100. They retain the checkpoint's original fit and selection cutoffs, calibration slope,
model hash and fit-manifest hash. They do not relabel the fit as 2026. WTA uses the
accepted 2026 checkpoint. In both tours, replay applies fixed state updates and a saved
SR02 candidate; it performs no HGB fit, calibration fit, candidate scoring or selection.

## Exact replay contract

History carries two clocks under D101. `model_event_date` is the accepted annual reported
date proxy used by the native chain for ordering, decay, workload and rest. It is not
claimed as an exact historical match date. `completion_upper_bound`,
`publication_upper_bound_utc` and `receipt_time_utc` independently decide whether the row
was available by the forecast cutoff and issue time. A shared archive receipt can never
replace `model_event_date` or define duplicate identity.

Before replay, the route hash-loads both the D101 review receipt and the reviewed input
manifest, then matches the consumed history and applicable ranking, BIO and tier hashes
to that manifest. A changed input plus a changed live config cannot continue citing the
older review.

Serve-state freshness follows the same separation. New normalized serve rows retain
`model_event_date` for state age and report the completion bound's age separately as
availability age. A legacy row without that field is labeled
`legacy_completion_upper_bound`; its acquisition age is not silently presented as tennis
history freshness.

The target row is neutrally oriented by numeric player ID and contains no result, status,
score, market price or serve-count block. The route rejects an outcome/stat-bearing
fixture. Base features reuse the accepted Elo, serve/return decay, workload and exact-ID
ranking code. Full features reuse the BIO trait sidecar, fixed SR02 state assimilation and
saved selection. Full-tier adds the accepted tier Elo, experience and tier count stream.
Its initial offset is read from the hash-bound accepted ATP chain configuration and must
equal the frozen per-training-window 2024 value.
An accepted event-edition rule-map match takes precedence; an explicit sourced fixture
rule is allowed only when the map cannot resolve the event. `best_of` alone is never used
to invent a deciding-set rule.

The retained D101 input candidates were exercised in a private, generated-fixture
rehearsal. That check used 54,035 ATP rows and withheld 10 rows with unresolved completion;
it used 45,321 WTA rows and withheld 332 inferred-date/overlap rows. Both ranking streams
ended on 2026-06-08, 99 days old on the 2026-09-15 readiness date. The full-tier result
state ended on 2024-12-23 and its count state on 2024-12-02. These are explicit freshness
limits, not supplements. The rehearsal used no real future schedule, did not write the
prospective ledger and is not prospective evidence.

## Remaining acceptance work

1. Bind the independently reviewed D101 history, ranking, player, rule, saved-selection
   and lower-tier bytes in a private live configuration. Preserve the source receipts and
   all withheld counts.
2. Build and verify a two-tour versioned live snapshot. Results, serve state and rankings
   must each report their actual coverage and frontier; missing or stale feeds remain
   visible. An empty incremental-results table is explicitly reported as
   `bound_history_no_live_delta`; the reviewed histories supply result coverage without
   being duplicated into `results.csv`.
3. Generate outcome-free ATP and WTA fixture controls from that snapshot and run Elo plus
   all five trained configurations. Require stable feature-order, feature-row, Elo,
   serve/return, workload, ranking, dynamic and tier hashes.
4. Verify fixture manifests and the isolated rehearsal ledger, then rehearse start
   verification, two-capture finality and settlement. Do not join a 2025/2026 outcome as a
   new confirmation result or describe the rehearsal as issued evidence.
5. Independently reconstruct receipt-to-panel bytes, all six forecasts and the ledger/
   settlement barriers before accepting the dated snapshot.

The unfinished Tennis Abstract acquisition is an independent coverage dependency. It is
not required to prove these routes, and completing it would not cure missing chronology,
ranking freshness or lower-tier freshness.
