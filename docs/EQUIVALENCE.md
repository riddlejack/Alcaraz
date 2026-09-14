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
| 14 | tier_stream | explained | 7/8 identical | summary.json code receipts |
| 15 | tier_elo | explained | 5/6 identical | summary.json code receipts, the recorded elo_engine binding and the label-accessor receipt |
| 16 | sr02_tier_replay | explained | 8/9 identical | run_manifest.json code receipts and declared binding |
| 17 | sr02_tier_noqual_replay | explained | 8/9 identical | run_manifest.json code receipts and declared binding |
| 18 | tier_block | explained | 7/8 identical | summary.json code receipts |
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
`docs/equivalence/<run>/_chain.json`. Tracked records are host-portable representations of
local originals; `docs/equivalence/LOCAL_EVIDENCE.md` records the placeholders and hashes.

| Run | Result | Differences and causes |
|---|---|---|
| WTA02/attempt_002 | all 136 prediction CSVs, `primary.json`, `pooled_metrics.csv`, `annual_metrics.csv`, `annual_contrasts.csv`, `contrast_summary.csv`, `bootstrap.csv`, `reliability.csv`, `report.md` byte-identical; rankings 38/38, sr03 12/14, sidecar 8/9 | the rewritten 2026 workbook has normalized ZIP/created times but retains a wall-clock modified property reset by openpyxl (B2 correction to RB6); its hash differs and cascades under RB7: one provenance column in `market_rows.csv` and both `panel.csv` (2,095 and 1,945 rows, no other cell differs), then every config, manifest and receipt that binds the panel hash, the edition-index hash (no wall clock, RB6) and the fit-cache directory names (keyed by config hash; 300 cache files renamed, contents equivalent bar the pickled module path). Attempt records differ in fit timing and those hashes. Code receipts throughout. |
| TIER01/attempt_002 | all 206 prediction CSVs (five bundles, 2014–2024 raw and 2017–2024 selected, market), `primary.json`, `pooled_metrics.csv`, `annual_metrics.csv`, `annual_contrasts.csv`, `contrast_summary.csv`, `bootstrap.csv`, `reliability.csv`, `report.md` byte-identical; both `panel.csv` files, `rules.csv`, all three SR02 replays' `selected_matches.csv`, the rankings, feature, label, sidecar and tier tables identical | composed tarball gzip-header mtime (stream identical) and the provenance CSV's three added columns; edition-index hash (RB6) and code receipts cascading into configs, manifests, receipts and the 330 fit-cache directory names; attempt records differ in fit timing |

## Repaired chain (decision RB14, Lane B2) against the same frozen runs

The historical baseline `180cb2d` (tag `historical-baseline-180cb2d`) reproduced the
archive's pre-barrier SR03 scoring and selection-score artifacts and stays the
reconstructor's oracle for that. The repaired chain (`b2-integrity`) was run through the
same driver against the same frozen inputs and configs on 2026-09-14
(`tools/equivalence.py chain`; TIER01 resumed from `tier_block` after two integrity
refusals that the gate itself raised and that were fixed by routing `tier_block`'s panel
read through the metadata projection). Records: `docs/equivalence/<run>/_chain.json`
(placeholder representations; originals under `local/evidence/`). `verify` passes on
both workspaces with zero integrity problems; the barrier scanned 767 (ATP) and 567
(WTA) pre-barrier files and found no metric-shaped content.

**Unchanged (byte-identical to the archive):** every prediction CSV (206 ATP, 136 WTA),
`sr03_calibration/predictions.csv`, `fits.json` and `training_membership.csv`, and the
report's `primary.json`, `pooled_metrics.csv`, `annual_metrics.csv`,
`annual_contrasts.csv`, `contrast_summary.csv`, `bootstrap.csv`, `reliability.csv`,
`report.md`, `coverage.csv` and `selection_diagnostics.csv`. ATP primary equal-year
full_tier − full −0.006768047240019573 (n 18,972); WTA full − base
−0.0044273519249091045 (n 4,296). Every stage's classification against the archive is
the baseline's except the intentional changes below (`fit_cache` directory renames and
the per-stage `access_log.jsonl` receipts aside).

**Intentionally moved or deleted (an artifact change, not explained provenance):**

| Artifact | Baseline `180cb2d` | Repaired chain | Values |
|---|---|---|---|
| `sr03_calibration/metrics.csv`, `reliability.csv`, `comparisons.json`, `cohort_counts.json` | identical to the archive, written before the barrier | absent; written by stage `sr03_component` after the report | ATP: all four byte-identical to the archive's. WTA: 93 annual metric rows and 12 annual comparison entries for 2022–2024 identical; 2025–2026 rows added because the component stage scores every outer year with a resolved outcome, where the frozen WTA02 config capped scoring at 2024. The larger scoring population also changes pooled metric rows, cohort totals and 58 of 60 pooled reliability rows (2 unchanged). This is an intentional scoring-population change in component diagnostics; the ten final report files remain byte-identical |
| `sr03_calibration/scoring_boundary.json` | ATP absent, WTA identical | present on both: nothing scored, every outer year deferred, the historical `score_years_max` recorded | – |
| `pipeline/selection/<y>/<learner>/<block>.json` (40 ATP, 16 WTA), `pipeline/market/<y>/calibration.json` (8, 2) | identical | different: `candidate_trials[*].equal_year_mean_log_loss`, `annual[*].mean_log_loss`, `selection.ranked[*].score`, `minimum_equal_year_mean_log_loss`, `runner_up_gap` and `slope_fit` scores removed; `criterion_sha256` and `selection_keys_path` added | selected candidate, slope, ranked order, membership hashes unchanged |
| `pipeline/selection/<y>/selection_keys.csv`, `pipeline/market/<y>/selection_keys.csv` | – | added (8+8 ATP, 2+2 WTA) | membership hash equals the record's `selection_membership_sha256` |
| `report/selection_trials.json` | – | added: the recomputed criterion tables | every value equals the archive's pre-barrier value (ATP 128 of 128 compared: 80 candidate trials' equal-year and annual losses, 40 runner-up gaps, 8 market fits; WTA checked on the first record and gap) |
| `report/selection_receipts.json` | different (provenance) | different (copies the public records; points at `selection_trials.json`) | – |
| `<stage>/access_log.jsonl`, `stage_manifest.json: outcome_access`, `integrity_violations`, barrier `content_scan` | – | added on every stage | – |


## Independent B2 follow-up reconstruction

The [fresh reconstruction review](equivalence/b2_review/reconstruction.md) and
[machine summary](equivalence/b2_review/reconstruction.json) supersede builder-only
claims for the B2 repair. Both full historical chains were rerun from immutable source
`89de382`, with the same frozen archive configs and lock hash
`00be4f800e7f0da7e89b29ad6f032a8bda5a2cb2ff072a1965e21b6b5b794764`.
The original B2 run trees were preserved. A briefly started editable-source attempt
was stopped and retained before restarting in a separate immutable-source workspace.

| Check | ATP TIER01 | WTA WTA02 |
|---|---:|---:|
| Forecast CSVs, identical to archive and saved B2 | 206 / 206 | 136 / 136 |
| Named final report files, identical | 10 / 10 | 10 / 10 |
| Training-key files and membership hashes, identical | 110 / 110 | 100 / 100 |
| Fitted model files byte-identical | 37 / 110 | 69 / 100 |
| Remaining model files, signed-zero differences only (R27) | 73; 95 entries | 31; 39 entries |
| Completed stages passing snapshot and final verification | 25 | 20 |
| Scanned pre-barrier artifacts / metric findings | 767 / 0 | 567 / 0 |

All changed files and renamed caches were adjudicated, including complete fitted-object
state. Forecasts, SR03 predictions/fits/training membership and all final report values
are unchanged. Cache names, audit schema, code/config/manifest/ledger hashes and timing
receipts differ as expected. No raw archive artifact or frozen source/config was edited.

WTA retains one pre-existing provenance nondeterminism: openpyxl overwrites
`docProps/core.xml`'s modified property at save time. All other workbook members and ZIP
times match; only `market_source_sha256` changes in 2,095 of 47,505 market rows and 1,945
of 46,827 rows in each panel. This is an explicit RB7 exception, not workbook byte
identity. A separate serialization repair should test and remove that variation.
The WTA SR03 expanded-population aggregate differences are listed above, separately.

The final verifier also passed both fresh trees after `907b79e` tightened the date
receipt ceiling. AST comparison of all 60 package Python modules found only that
validation behavior changed after the immutable run source; formatting and the corrected
bridge docstring have no behavioral difference. This avoids mislabelling the execution
commit as the final documentation/integration commit. Exposure is recorded as
`REBUILD-B2-ASTRA-001`; these remain retrospective development results.


## WTA01 historical campaign input

The additional WTA01 2019–2024 binding was independently reconstructed at `87448ab`,
then its audit helper was independently repaired and checked at `41b8204`. All 288
forecast files, ten final reports and 180 training-key files matched exactly. The
independently derived populations are 12,900 primary and 12,785 priced matches. Fitted
state uses a specifically adjudicated serialization/signed-zero allowance.

The [binding receipt](equivalence/WTA01-binding_attempt_002/README.md) retains attempts,
commands, complete inventory and audit controls. The original audit missed changes in
fitted-parameter and frozen-source metadata; the successor rejects those changes and
checks actual fitted state, complete artifact inventory and the 18-stage ledger using
the retained run. No second historical run was needed for that audit repair.

This is a mechanically verified historical input for the proposed E/G work, not its
acceptance or empirical freeze. Its market-source-conditioned population, mostly
score-assisted WTA rule provenance, constant dynamic training feature in 2016 and
unknown quote clocks remain explicit limits. It does not replace the WTA02 results
presented on the front page. Independent review records in the separate archive are
`LANE_WTA01_BINDING_RECONSTRUCTION.md` (SHA-256
`7b234748cf60c87a3999a5bfdbff2b5ea9c2a8201ec6262d25ca398c47f48ba8`) and
`LANE_WTA01_AUDIT_REPAIR.md`, which links the focused independent successor review.
