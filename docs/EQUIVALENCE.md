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
| 1 | bridge | pending | | |
| 2 | archive_panel | explained | 7/9 identical | `archive_panel_launch.json` provenance only (code receipt, launcher id); `quality_report.json` gains three descriptive keys from the WTA02 revision (`tour`, `correction_policy`, `excluded_reason_counts`), all shared keys identical |
| 3 | join | pending | | |
| 4 | event_carry_forward | pending | | |
| 5 | prepare_panel | pending | | |
| 6 | format_corrections | pending | | |
| 7 | rule_mapping | pending | | |
| 8 | sr02_replay | pending | | |
| 9 | sr03_calibration | pending | | |
| 10 | rankings | pending | | |
| 11 | edition_index | pending | | |
| 12 | features | pending | | |
| 13 | sidecar | pending | | |
| 14 | tier_stream | pending | | |
| 15 | tier_elo | pending | | |
| 16 | sr02_tier_replay | pending | | |
| 17 | sr02_tier_noqual_replay | pending | | |
| 18 | tier_block | pending | | |
| 19 | predictor_config | pending | | |
| 20 | preflight | pending | | |
| 21 | pipeline | pending | | |
| 22 | barrier | n/a | no outputs | the barrier hashes the run tree; verified by `chain.runner verify` |
| 23 | reporting_config | pending | | |
| 24 | report | pending | | |

## WTA — `WTA02/attempt_002`

| # | Stage | Status | Data outputs | Cause of difference |
|---|---|---|---|---|
| 1 | bridge | pending | | |
| 2 | archive_panel | explained | 7/9 identical | `archive_panel_launch.json` provenance only (code receipt, launcher id); `quality_report.json` gains three descriptive keys from the WTA02 revision (`tour`, `correction_policy`, `excluded_reason_counts`), all shared keys identical |
| 3 | event_carry_forward | pending | | |
| 4 | join | pending | | |
| 5 | prepare_panel | pending | | |
| 6 | format_corrections | pending | | |
| 7 | rule_mapping | pending | | |
| 8 | sr02_replay | pending | | |
| 9 | sr03_calibration | pending | | |
| 10 | rankings | pending | | |
| 11 | edition_index | pending | | |
| 12 | features | pending | | |
| 13 | sidecar | pending | | |
| 14 | predictor_config | pending | | |
| 15 | preflight | pending | | |
| 16 | pipeline | pending | | |
| 17 | barrier | n/a | no outputs | the barrier hashes the run tree; verified by `chain.runner verify` |
| 18 | reporting_config | pending | | |
| 19 | report | pending | | |

## Elo baseline — `CONFIRM2026/elo_001`

| Artifact | Status | Cause of difference |
|---|---|---|
| forecasts (F2 replay) | pending | |
