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
- the complete bound-history schema, typed publication/receipt timestamps and admitted
  completion bases;
- counts withheld for unresolved overlap, unadmitted completion basis, non-played status
  or duplicate match identity;
- the latest version pointer, manifest, normalized tables and acquisition-receipt hashes;
- tour coverage in results, serve state and rankings, with observed frontiers;
- the accepted release identity, manifest hash, complete payload inventory, exact per-rung
  target-year inventory and each declared rung's prepared-row runner;
- one deterministic asymmetric, outcome-free interface probe at the latest accepted year
  for each trained rung, with its feature-row hash and probabilities;
- the ledger chain, including a valid empty genesis state; and
- the existing settlement barrier and estimand.

With the committed configuration, the honest result remains `pending`: ATP and WTA
history are `PENDING`, no real snapshot version exists, and the five trained rungs have
no snapshot-to-feature route. Their accepted artifact release and prepared-row interface
are now pinned. Supplying the exact bundle verifies its complete payload inventory and all
40 model records, then probes the five latest-year interfaces, but it does not promote the
rungs to live-ready. The ATP release ends at target year 2024; choosing a checkpoint for a
2026 ATP fixture is a separate scientific deployment decision. The ledger and settlement
implementation are present; none of this makes a rehearsal prospective evidence.

## Data qualification rule

History becomes eligible only from a hash-bound table in the existing
`bound-history-1` contract. A row with unresolved overlap or no completion bound is
withheld. A row whose `completion_basis` is not explicitly admitted by that tour's
binding is also withheld. The readiness profile reports these rows rather than converting
an event anchor, an aggregate count or a local receipt time into a match clock.

For the staged TennisMyLife material, existing result/count qualification does not settle
historical availability. Negative date offsets in retained comparisons prevent a general
"supplied date is a completion upper bound" rule. D2 must bind a separately corroborated
completion bound or quarantine the row. Tennis Abstract event anchors likewise do not
become match dates. The completed crawl will establish acquisition coverage, not this
chronology rule.

## Exact work after the remaining inputs arrive

1. Finish the TAPLAYER01 acquisition and run its terminal offline audit. Export only the
   parsed, attributed feed and its manifest; keep raw pages, receipts and private permission
   evidence outside public Git.
2. Build the two bound-history tables from already qualified source fields. Record the
   source version, row grain, SHA-256, admitted completion bases and every withheld reason.
   Quarantine unresolved TML/TA chronology instead of applying an inferred date shift.
3. Run one explicit `update` with the qualified two-tour results, Tennis Abstract serve
   feed and last-known rankings. Verify the new version and rerun `readiness`; results,
   serve state and rankings must each cover ATP and WTA at their stated frontiers.
4. Complete the exact snapshot-to-chain feature replay for the five now artifact-bound
   trained rungs. Append the fixture to the live panel and run the existing feature stages
   with its fixture-year label blank; pass only the emitted estimator fields to the pinned
   `tennislab.models.release.predict_feature_row` interface. This applies existing fits;
   it does not refit, tune or select. For ATP after 2024, first approve and record either a
   frozen-2024 deployment horizon or a separately accepted later checkpoint. The accepted
   incumbent remains the default.
5. Exercise Elo plus those five trained rungs on outcome-free synthetic ATP/WTA fixtures
   from the real snapshot. Require deterministic feature, Elo, workload, ranking, dynamic
   serve/return and tier-state hashes; an `unavailable` placeholder is not a pass.
6. Verify fixture manifests and the ledger chain, then rehearse start verification,
   two-capture finality and settlement. No 2025/2026 outcome may be joined as a new
   confirmation result, and no retrospective rehearsal may be described as issued evidence.
7. Independently reconstruct receipt-to-panel bytes, all six forecasts and the ledger/
   settlement barriers before naming the dated snapshot accepted.

The crawl is therefore one dependency, not the only blocker. Per-match chronology and the
five trained-rung runtime bindings remain independent acceptance work.
