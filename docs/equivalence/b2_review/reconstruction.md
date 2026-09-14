# Independent fresh B2 historical reconstruction

**Disposition: accepted for historical output preservation, with the explicit artifact exceptions below.** This is a development-only reconstruction of previously observed outcomes, not prospective or confirmatory evidence.

Both full chains ran from an immutable `git archive 89de382` source snapshot. Driver and stage children inherited `PYTHONPATH=source_89de382/src`; the existing pinned product interpreter was used without package installation. Separate output trees preserved the saved Fable runs. An initial mutable-source attempt was deliberately interrupted before further edits and remains preserved with `INTERRUPTED.json`; it is not counted as acceptance evidence.

| Frozen execution input | Value |
|---|---|
| Commit | `89de38207e85e1f700da576ccde3db20487f16b6` |
| `uv.lock` SHA-256 | `00be4f800e7f0da7e89b29ad6f032a8bda5a2cb2ff072a1965e21b6b5b794764` |
| Canonical source-hash inventory SHA-256 | `5ded2f1119859c280f426cab549c9bcfa837f1705fa523e8553574681fff59bd` |
| TIER01 original archive chain config SHA-256 | `93c3a58ea195b0905987b12c0a512c6970764cc19debecd340fed6da4705eda9` |
| WTA02 original archive chain config SHA-256 | `e62333697e8d6bcdca2118dd3193b11c457b0367c9c21217de0ccad514fc9d01` |

The inventory digest hashes the sorted, compact JSON mapping of relative `src/` and `tools/` Python paths to SHA-256 values, retained in `frozen_execution.json`. Source bytes, lock and original chain config hashes remained unchanged through both runs.

| Verified comparison | ATP TIER01/attempt_002 | WTA WTA02/attempt_002 |
|---|---|---|
| Forecast CSVs against archive and saved B2 | 206/206 byte-identical; equal path sets | 136/136 byte-identical; equal path sets |
| Eight named report outputs plus coverage and selection diagnostics | 10/10 byte-identical | 10/10 byte-identical |
| SR03 predictions, fits and training membership against archive | 3/3 byte-identical | 3/3 byte-identical |
| Four SR03 component files against saved B2 | 4/4 byte-identical | 4/4 byte-identical |
| Full chain, snapshot verify and final verify | all exit 0; 25 stages | all exit 0; 20 stages |
| Semantically paired fit caches | 110/110 | 100/100 |
| Training-key bytes and membership hashes | 110/110 identical | 100/100 identical |
| Estimator bytes / explicit signed-zero exception | 37 identical; 73 differ only in 95 HGB threshold signed zeros | 69 identical; 31 differ only in 39 HGB threshold signed zeros |

The estimator exception was checked by recursively comparing the entire fitted object state, including array values/dtypes/shapes, configuration, tree state and serialized Cython loss state. Only positive/negative zero representations differ in HGB bin thresholds (ATP columns 16/17/24/32; WTA 16/17); no changed nonzero numerical state was found. This retains the previously declared R27 exception.

Final verification used the strengthened current verifier. Both final runs used byte-identical `src/` files, although their recorded HEAD contexts were `7caa216` and `50d9fba` (the same source bytes before/after committing documentation). Independently comparing all source ASTs after removing docstrings shows only `chain/runner.py` differs behaviorally from the execution snapshot: the final receipt cutoff guard. Exact source hashes are retained in both final-verifier receipts.

Complete fresh-versus-saved B2 artifact accounting: ATP run tree 496 identical, 173 changed, 330 removed plus 330 added fit-cache paths; all 8 input files identical. WTA run tree 297 identical, 171 changed, 300 removed plus 300 added fit-cache paths; inputs 7 identical and 3 changed. Each side has one changed predictor config and one reporting config. Every renamed fit cache is paired by its unchanged year/learner/block/candidate attempt path. Changes are fully inventoried and adjudicated as runtime access/schema/projection receipts, hash bindings, execution time/path provenance, fit-cache identity and the explicit estimator/workbook exceptions. No unadjudicated artifact remains.

**Residual WTA workbook nondeterminism:** only ZIP member `docProps/core.xml` differs, only its `dcterms:modified` property: saved `2026-09-14T19:45:25Z`, fresh `2026-09-14T20:27:38Z`. ZIP member names and entry timestamps match, as do all other member bytes. This changes only `market_source_sha256` on 2,095 of 47,505 `join/market_rows.csv` rows and 1,945 of 46,827 rows in each of `prepare_panel/panel.csv` and `format_corrections/panel.csv`. All other CSV cells are equal. Workbook metadata determinism is not established; a future byte-deterministic workbook requirement should reopen the bridge writer. No bridge behavior was changed during this reconstruction.

Relative evidence locators under `local/review_b2/fresh_89de382_snapshot/`:

- `frozen_execution.json`: exact commands, environment, source/lock/config hashes and dependency versions.
- `TIER01.result.json`, `WTA02.result.json`: completed run and snapshot-verifier results.
- `TIER01.verify_final.json`, `WTA02.verify_final.json`: final-verifier results and source inventories.
- `comparison.json`: every forecast/report hash and complete artifact delta inventory.
- `adjudication_TIER01.json`, `adjudication_WTA02.json`: every fit-cache pairing, estimator-state exception, CSV/XML difference and file disposition.
- `acceptance_summary.json`: compact machine-readable results.

Original saved forecast/report hashes were rechecked and remained unchanged. No tracked product file, archive file or original run output was changed by the reconstruction.
