# D2 real-snapshot readiness

This is a preparation boundary, not a snapshot acceptance. `tennislab readiness` is a
read-only check: it does not acquire a source, advance `latest.json`, fit or select a
model, issue a forecast, or write to the prospective ledger.

## Reproducible check

```sh
uv run tennislab readiness --config configs/live/live.json
```

The report verifies what is present and names what is absent:

- each ATP/WTA history path and SHA-256 binding;
- the complete bound-history schema, typed publication/receipt timestamps and admitted
  completion bases;
- counts withheld for unresolved overlap, unadmitted completion basis, non-played status
  or duplicate match identity;
- the latest version pointer, manifest, normalized tables and acquisition-receipt hashes;
- tour coverage in results, serve state and rankings, with observed frontiers;
- each declared rung's live runner and fitted-artifact binding;
- the ledger chain, including a valid empty genesis state; and
- the existing settlement barrier and estimand.

With the committed configuration, the honest result remains `pending`: ATP and WTA
history are `PENDING`, no real snapshot version exists, and the five trained rungs have
no live runner/artifact binding. The ledger and settlement implementation are present;
that does not make them prospective evidence.

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
4. Bind the release package's exact accepted incumbent artifacts and an exact
   `features`→`pipeline` replay for `atp_p0`, `atp_p1`, `atp_full_tier`, `wta_base` and
   `wta_full`. Fixture-year labels remain blank. This is application of existing fits, not
   refitting, tuning or selecting a model. The accepted incumbent remains the default.
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
