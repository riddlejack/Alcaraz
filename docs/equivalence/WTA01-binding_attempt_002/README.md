# WTA01 historical product binding — attempt 002

Status: **reconstruction passed**. This is a retrospective reconstruction of WTA01
2019–2024 under the repaired `tennis-lab` product. It is not a new experiment, does not
accept rebuild lanes E or G, and is not prospective evidence.

## Attempts and commands

`WTA01-BINDING-001` failed during structural freeze before any model stage, outcome-label
read, or score. The copied chain config omitted the retained `chain.python` field. The
failure is preserved in `../WTA01-binding_attempt_001/failure.json`; the corrected binding
therefore uses the new ID `WTA01-BINDING-002`.

Attempt 002 was frozen before execution with:

```sh
TENNISLAB_ARCHIVE=<ARCHIVE_ROOT> uv run python tools/wta01_binding.py freeze
```

The generated sequence was rehearsed with `tennislab.chain.runner dry-run
--include-report`; it returned `PASS`, listed no absent inputs or stage-order problems, and
opened no outcome file. The reconstruction command was:

```sh
TENNISLAB_ARCHIVE=<ARCHIVE_ROOT> uv run python tools/equivalence.py chain \
  --run WTA01-binding/attempt_002 \
  --chain-config configs/chains/wta01_2019_2024.json
```

The resulting 18-entry chain ledger was checked with `tennislab.chain.runner verify`, then
audited independently with:

```sh
TENNISLAB_ARCHIVE=<ARCHIVE_ROOT> uv run python tools/wta01_binding.py audit
```

The first audit revision raised a type error while reading the report's year-to-delta
mapping. The second over-broadly counted six new `selection_keys.csv` receipts as market
forecasts. Both failures are preserved; neither changed the already-verified chain
artifacts. The final corrected read-only audit passed.

## Reproduction result

- Historical forecast bytes: **288/288 identical** — raw 180, selected 48, shared-base 48,
  market 12.
- Historical final-report bytes: all **10 named result files identical**.
- Fit and selection membership: **180/180** attempt semantics matched, **180/180** training
  key files matched semantically and byte-for-byte, **48/48** model selection records and
  key receipts matched, and all **6/6** new market selection-key receipts verified.
- Target membership: **12,900** aligned-primary rows; priced projection: **12,785** rows.
- Independent row-wise HGB full-minus-base log-loss: equal-year
  **−0.004568747513453801** and match-weighted **−0.0049116616752896925**. Both match the
  retained report within `2e-15`.
- Source panel, prepared/corrected panel, rules, SR02 history, SR03 predictions/fits/training
  membership, features, labels, dictionary, and sidecar are byte-identical.
- Seventeen access logs containing 2,263 records name no active crawl, `latest`, or WTA02
  source path.

## Explicit semantic exceptions

The generated predictor config differs only in `code` provenance and `created_at_utc`; its
scientific and data contract is otherwise equal. Repaired-product manifests, access logs,
hash ledgers, selection receipts, deferred post-barrier score artifacts, and fit-cache IDs
produce the broader differences catalogued in `_chain.json`.

The repaired join adds one `market_date_basis` column to 42,905 historical market rows. All
48 retained columns match cell-for-cell in the same row order; every added value is
`tennis_data_reported_date`, the maximum season is 2024, and there are zero
`accepted_carried_forward` rows. Its manifest retains the product-era ID
`WTA02-market-join`; this is a metadata/schema exception, not use of WTA02 bridge data. The
repaired runner also emits a product-only, post-barrier `sr03_component` report absent from
the retained WTA01 tree.

Report metadata files differ because they bind the repaired code, timestamps, chain hashes,
and deferred-selection receipts. The ten declared result files remain byte-identical. Exact
different, missing, and extra paths are retained in `_chain.json` and
`historical_audit.json`.

## Bound history and limits

The run uses the original design blob at git commit
`1f18978828293c745b93879ea7fae41c821b2900`, sha256
`0428751403cbd8b1d52ef65f83a1a630d0b61d94f446a3ea5e286354071950f0`, while leaving the
archive's later amended/withdrawal design untouched. The original secondary failures remain
retained and withdrawn.

The 2016 dynamic raw fit has a wholly constant training window. Most scoring-rule eras were
inferred from same-season outcome-bearing scores; only Wimbledon 2019–2021 has retained
dated announcement custody. Market price clocks remain unknown and the priced cohort is
market-source-conditioned. Passing bytes, membership, arithmetic, and access checks proves
reconstruction under the tested scope—not source truth, comprehensive leak freedom,
scientific validity, market efficiency, value, or prospective edge.
