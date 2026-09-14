# Equivalence with the archive's accepted runs

Oracle: every stage of every accepted archive run wrote `stage_manifest.json` with the
SHA-256 of each output file. A ported stage is run on the same frozen inputs and every
output file is compared by hash. Status is one of: **identical**, **explained** (differs
only in named provenance fields, with the cause), or **open** (an unexplained difference,
which blocks the next stage).

Provenance classes that are expected to differ and are not evidence of a numerical
change: the program path and hash of the code that ran, the Python interpreter path,
wall-clock timestamps, and the run root path when it is written into a manifest.

## ATP — `TIER01/attempt_002`

| # | Stage | Status | Data outputs | Cause of difference |
|---|---|---|---|---|
| 1 | bridge | identical | 2/2 identical | provenance leaves; see docs/equivalence/notes |
| 2 | archive_panel | explained | 7/9 identical | `archive_panel_launch.json` provenance only (code receipt, launcher id); `quality_report.json` gains three descriptive keys from the WTA02 revision (`tour`, `correction_policy`, `excluded_reason_counts`), all shared keys identical |
| 3 | join | explained | 10/13 identical | manifest code receipt; openpyxl warning in stderr embeds the interpreter path |
| 4 | event_carry_forward | explained | 3/4 identical | carry_forward_report.json code receipt |
| 5 | prepare_panel | explained | 5/7 identical | manifest.json code receipt; openpyxl warning path in stderr |
| 6 | format_corrections | identical | 4/4 identical |  |
| 7 | rule_mapping | explained | 5/6 identical | manifest.json code receipt and its canonical hash |
| 8 | sr02_replay | explained | 6/7 identical | run_manifest.json code receipts and declared binding |
| 9 | sr03_calibration | explained | 12/13 identical | run_manifest.json code receipt |
| 10 | rankings | explained | 36/38 identical | qualification.json and stdout gain `tour` (WTA02 revision) |
| 11 | edition_index | explained | 1/4 identical | wall-clock stamp removed (RB6); summary.json gains two WTA02 keys and the dependent index hash |
| 12 | features | explained | 7/10 identical | manifest.json code receipt, declared binding, workspace-relative output_dir; summary.json gains one WTA02 key |
| 13 | sidecar | explained | 8/9 identical | manifest.json executed_builder code receipt |
| 14 | tier_stream | pending | | |
| 15 | tier_elo | pending | | |
| 16 | sr02_tier_replay | explained | 8/9 identical | run_manifest.json code receipts and declared binding |
| 17 | sr02_tier_noqual_replay | explained | 8/9 identical | run_manifest.json code receipts and declared binding |
| 18 | tier_block | pending | | |
| 19 | predictor_config | explained | 1/2 identical | provenance leaves; see docs/equivalence/notes |
| 20 | preflight | explained | 1/2 identical | provenance leaves; see docs/equivalence/notes |
| 21 | pipeline | explained | 407/740 identical | every prediction CSV, selection/shared/market record and training-key file identical; differing: fit timing fields, the pickled estimator cache (module path), config_path and code receipts cascading into ledgers |
| 22 | barrier | n/a | no outputs | the barrier hashes the run tree; verified by `chain.runner verify` |
| 23 | reporting_config | explained | 1/2 identical | side config: code receipt, frozen_at_utc |
| 24 | report | explained | 13/16 identical | start.json and result.json timestamps and reporter hash, artifact_manifest follows; primary.json, pooled_metrics.csv, bootstrap.csv, reliability.csv, report.md and stdout identical |

## WTA — `WTA02/attempt_002`

| # | Stage | Status | Data outputs | Cause of difference |
|---|---|---|---|---|
| 1 | bridge | explained | stage outputs 2/2 identical; inputs tree 5/8: composed tarball gzip-header mtime only (stream identical), bridge_summary.json code receipts and WTA02-revision descriptive keys, provenance CSV gains three columns (archive columns identical on all 2,703 rows) |
| 2 | archive_panel | explained | 7/9 identical | `archive_panel_launch.json` provenance only (code receipt, launcher id); `quality_report.json` gains three descriptive keys from the WTA02 revision (`tour`, `correction_policy`, `excluded_reason_counts`), all shared keys identical |
| 3 | event_carry_forward | explained | 3/4 identical | carry_forward_report.json code receipt |
| 4 | join | explained | 4/6 identical | manifest code receipt; openpyxl warning in stderr embeds the interpreter path |
| 5 | prepare_panel | explained | 6/7 identical | manifest.json code receipt; openpyxl warning path in stderr |
| 6 | format_corrections | identical | 4/4 identical |  |
| 7 | rule_mapping | explained | 6/7 identical | manifest.json code receipt and its canonical hash |
| 8 | sr02_replay | explained | 6/7 identical | run_manifest.json code receipts and declared binding |
| 9 | sr03_calibration | explained | 13/14 identical | run_manifest.json code receipt |
| 10 | rankings | identical | 38/38 identical | qualification.json and stdout gain `tour` (WTA02 revision) |
| 11 | edition_index | explained | 1/4 identical | wall-clock stamp removed (RB6); summary.json gains two WTA02 keys and the dependent index hash |
| 12 | features | explained | 8/10 identical | manifest.json code receipt, declared binding, workspace-relative output_dir; summary.json gains one WTA02 key |
| 13 | sidecar | explained | 8/9 identical | manifest.json executed_builder code receipt |
| 14 | predictor_config | explained | 1/2 identical | side config: code receipt, created_at_utc; every binding and count identical |
| 15 | preflight | explained | 1/2 identical | stdout: relative config_path, declared binding and code receipt replace two hash leaves; membership identical |
| 16 | pipeline | explained | 273/576 identical | every prediction CSV, selection/shared/market record and training-key file identical; differing: fit timing fields, the pickled estimator cache (module path), config_path and code receipts cascading into ledgers |
| 17 | barrier | n/a | no outputs | the barrier hashes the run tree; verified by `chain.runner verify` |
| 18 | reporting_config | explained | 1/2 identical | side config: code receipt, frozen_at_utc |
| 19 | report | explained | 13/16 identical | start.json and result.json timestamps and reporter hash, artifact_manifest follows; primary.json, pooled_metrics.csv, bootstrap.csv, reliability.csv, report.md and stdout identical |

## Elo baseline — `CONFIRM2026/elo_001`

| Artifact | Status | Cause of difference |
|---|---|---|
| stage-1 forecasts (7,528 rows) and f2 forecasts (8,428 rows), replayed from the archive's `results_stream.csv` through `tennislab.ratings.elo` | identical | none; state hashes through 2026-09-10 match for both tours (`docs/equivalence/notes/elo_baseline.md`) |

## Full chain runs through the ported driver

Stage-by-stage checks run each ported stage on the archive's frozen *inputs*. The full
chain run (`tools/equivalence.py chain`) runs the ported driver from the bridge to the
report in a fresh workspace, so every stage consumes the rebuild's own upstream outputs,
and then compares every stage against the frozen run. Results in
`docs/equivalence/<run>/_chain.json`.

| Run | Result | Differences and causes |
|---|---|---|
| WTA02/attempt_002 | all 136 prediction CSVs, `primary.json`, `pooled_metrics.csv`, `annual_metrics.csv`, `annual_contrasts.csv`, `contrast_summary.csv`, `bootstrap.csv`, `reliability.csv`, `report.md` byte-identical; rankings 38/38, sr03 12/14, sidecar 8/9 | the rewritten 2026 workbook is timestamp-free (RB6), so its hash differs and cascades (RB7): one provenance column in `market_rows.csv` and both `panel.csv` (2,095 and 1,945 rows, no other cell differs), then every config, manifest and receipt that binds the panel hash, the edition-index hash (no wall clock, RB6) and the fit-cache directory names (keyed by config hash; 300 cache files renamed, contents equivalent bar the pickled module path). Attempt records differ in fit timing and those hashes. Code receipts throughout. |
| TIER01/attempt_002 | pending the tier stages | |
