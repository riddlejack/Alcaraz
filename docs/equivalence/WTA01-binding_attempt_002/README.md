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
artifacts. The original builder audit then passed, but an independent reconstruction found
that it did not compare full fit metadata or loaded model state and did not separately
enforce the named `frozen_source` fields. `historical_audit.json` is retained as that
original result; `historical_audit_repaired.json` is the repaired successor audit.

## Reproduction result

- Historical forecast bytes: **288/288 identical** — raw 180, selected 48, shared-base 48,
  market 12.
- Historical final-report bytes: all **10 named result files identical**.
- Fit and selection membership: **180/180** attempt semantics matched, **180/180** training
  key files matched semantically and byte-for-byte, **48/48** model selection records and
  key receipts matched, and all **6/6** new market selection-key receipts verified.
- Fit artifacts: all **180/180** manifests match outside the exact four code/serialization
  receipt fields; all 180 serialized model hashes bind their files. Loaded model state has
  no nonzero difference. The exact allowed difference is 176 signs of zero in 52 HGB models:
  106 bin-threshold and 70 tree-threshold entries, with no signed-zero exception elsewhere.
- Target membership: **12,900** aligned-primary rows; priced projection: **12,785** rows.
- Independent row-wise HGB full-minus-base log-loss: equal-year
  **−0.004568747513453801** and match-weighted **−0.0049116616752896925**. Both match the
  retained report within `2e-15`.
- Source panel, prepared/corrected panel, rules, SR02 history, SR03 predictions/fits/training
  membership, features, labels, dictionary, and sidecar are byte-identical.
- Seventeen access logs containing 2,263 records name no active crawl, `latest`, or WTA02
source path.

The repaired audit also inventories the complete `run`, `inputs`, `predictor_config`, and
`reporting_config` union: 1,849 paths (442 identical, 284 different, 544 missing, 579 extra),
including all stage manifests, both ledgers, and the product-only SR03 component. The 14
generated stage configs are checked separately; three differ only in adjudicated upstream
hash fields. All 18 reconstructed stage manifests and ledger entries pass the product
integrity verifier.

## Explicit semantic exceptions

The generated predictor config differs only in `code` provenance and `created_at_utc`; its
scientific and data contract is otherwise equal. Repaired-product manifests, access logs,
hash ledgers, selection receipts, deferred post-barrier score artifacts, and fit-cache IDs
produce broader differences. `_chain.json` is only a source-manifest-output comparison for
shared stages plus selected side trees; it excludes stage manifests, the chain ledger, and
product-only stages. The complete union inventory is in `historical_audit_repaired.json`.

The repaired join adds one `market_date_basis` column to 42,905 historical market rows. All
48 retained columns match cell-for-cell in the same row order; every added value is
`tennis_data_reported_date`, the maximum season is 2024, and there are zero
`accepted_carried_forward` rows. Its manifest retains the product-era ID
`WTA02-market-join`; this is a metadata/schema exception, not use of WTA02 bridge data. The
repaired runner also emits a product-only, post-barrier `sr03_component` report absent from
the retained WTA01 tree.

Report metadata files differ because they bind the repaired code, timestamps, chain hashes,
and deferred-selection receipts. The ten declared result files remain byte-identical. Exact
different, missing, and extra paths within the complete four-root scope are retained in
`historical_audit_repaired.json`.

The reconstruction workspace was not an operating-system access sandbox. It physically
exposed the archive's complete `data` and `references` roots and most children of
`experiments`; only `work` was narrowed to `work/MULTI01_ranking_lookup`, and the WTA01
design path was replaced in scratch by the exact historical git blob. Access-log and stage
receipt findings describe observed instrumented reads, not proof that physically accessible
files could not be opened.

## Audit-repair controls

`audit_repair_controls.json` runs the independent review's two missed cases through the
actual repaired interfaces. A config whose original-design commit is replaced by forty
zeros is rejected by `frozen_source_exact`. An isolated fit-manifest overlay with HGB
`learning_rate` changed from 0.05 to 0.10 makes both the scientific fit gate and chain
integrity check fail. In-memory controls additionally prove that the loaded-state comparator
detects an estimator learning-rate change and a change in the final structured tree's
numeric-threshold field. These controls do not modify or refit the retained run.

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
