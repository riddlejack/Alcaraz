# Outcome access and the report barrier

Lane B2 repair design, written before the code (archive brief
`docs/reviews/rebuild_2026-09-13/LANE_B2_integrity_integration.md`; archive decisions
R9, R15, R17; product decisions RB3, RB9, RB11, RB14). This page states the contract the
chain enforces at run time, what each stage actually reads, and which artifacts were
moved behind the barrier. `tests/test_label_barrier.py` and `tests/test_barrier_gate.py`
demonstrate the clean and the planted-leak behaviour on the synthetic sample.

## 1. The wording conflict and its resolution

Archive protocol point 4 (2026-09-14 rewording) says every past-only reader goes through
"one label loader that refuses any row dated on or after the earliest outer target year".
Read literally that is a *global* ceiling: with target years 2017–2024 no stage before the
report could see a 2017 outcome. The frozen walk-forward estimand contradicts it: the
2018 fold trains on 2013–2017, the 2018 selection window is 2015–2017, and the SR03 slope
for 2018 is fitted on 2015–2017. Those are development years of the fold that consumes
them and target years of an earlier fold. RB11 resolves the conflict: **horizons are
fold-specific.** A reader may consume an outcome only when the outcome's season is below
the fold's own ceiling (the outer year minus one, or the D−2 cursor of a state replay),
and no stage before the barrier may *emit a score* of any outer year, whichever fold it
belongs to. R9's "zero pre-barrier scores of any outer year" (T8b) is kept verbatim;
R9's "one loader with a global ceiling" is read as "one accessor per read, each with the
fold's ceiling".

Two things the earlier tests conflated are now separate:

| Notion | Meaning | Where it is recorded |
|---|---|---|
| bytes accessible | the file the stage opened; a CSV reader parses every row | `stage_manifest.json: outcome_access.observed[]` (audit-hook record of every read-open of an outcome-bearing file) |
| rows returned | the keys the accessor handed back after its ceiling check | accessor receipt `rows_returned`, `max_season_returned`, `year_ceiling`, `fold_outer_year` |
| rows used | the training / selection membership the fit consumed | `training_membership.csv`, `training_by_calendar_year`, `selection_membership_sha256` |
| predictions emitted | forecasts written before the barrier | `predictions.csv`, `pipeline/raw`, `pipeline/selected`, `pipeline/market/*/*.csv` |
| metrics emitted | proper scores, paired deltas, outcome rates | **none before the barrier** (§3); `report/` afterwards |

The accessor receipt never claims that the rows it did not return were physically
unavailable. `LabelHistory.selected` parses the whole file and filters; its receipt says
so (`rows_parsed`).

## 2. Reader inventory (product chain, both tours)

Derived from the audit hook on the synthetic chain and re-checked against the code.
Four declarations: "none" (the runner fails the stage if it parses any outcome-bearing
file; hash-only opens and `projected_rows` opens, which drop the outcome columns, are allowed), "history" (a state replay or panel builder that
parses whole outcome files as past history), "fold" (a fit or selection stage: every
parse of an outcome-bearing file must go through `chain.labels` -- `LabelHistory`,
`PanelOutcomeHistory` or the metadata projection `projected_rows`, which drops the
outcome columns -- and every outcome receipt must name its fold and a ceiling before
it), and "target" (a post-barrier stage).

| Stage | Declared | What is actually opened | Horizon and how it is enforced |
|---|---|---|---|
| bridge, archive_panel, join, event_carry_forward, prepare_panel, format_corrections | history | source result files, workbooks, the panel | whole seasons; these build the panel, nothing is fitted or scored |
| rule_mapping | history | the panel (parsed; `a_won` unused) | none needed; format rules only |
| sr02_replay, sr02_tier_replay, sr02_tier_noqual_replay | history | the panel (parsed; `dynamic.SOURCE_ROW_FIELDS` projects `a_won` out) | the SR02 state cursor; serve counts are history by construction |
| sr03_calibration | fold | the panel's metadata through `projected_rows` (outcome columns dropped), then the panel's `a_won` through `PanelOutcomeHistory`, one read per outer year | ceiling = outer year − 1 by `source_season`, cutoff = 30 December by `match_date`; receipt per fold |
| rankings | history | the Sackmann tarball (`winner_id`/`loser_id` qualify the ranking stream) | archive seasons only |
| edition_index | none | ranking stream | – |
| features | history | the panel (`a_won` updates the result-Elo state under D−2 and is copied into `labels.csv`) | D−2 cursor; `elo_latest_source_date` per row |
| sidecar | history | the panel is parsed (the audit hook records it) and projected to `PANEL_MEASUREMENT_FIELDS` before use; `labels.csv` is never opened | none needed; no outcome value is used or emitted |
| tier_stream | history | the Sackmann tarball's lower-tier members | archive seasons only |
| tier_elo | history | `labels.csv` through `EloStateHistory`, `tier_results.csv.gz` | D−2 cursor inside the replay; ceiling = panel end year (state history, no fit) |
| tier_block | none | sidecar, tier_elo features, SR02 selected matches; the panel through `projected_rows` (outcome columns dropped) for the prior tour-match counts | D−2 lag on the counts; no outcome value reaches the module |
| predictor_config | none | hashes `labels.csv` (bytes, never parsed) | recorded as a hash-only open |
| preflight | none | – | – |
| pipeline | fold | `labels.csv` through `LabelHistory` per fold: `training_fit`, `past_selection_calibration`, `past_market_calibration` | ceiling = outer year − 1; the runner refuses a receipt whose ceiling reaches its fold's outer year, a receipt without a fold, or a parse outside the accessors |
| barrier | none | pre-barrier stage directories (content scan, §3) | – |
| reporting_config | none | selection ledger | – |
| report | target | `labels.csv`, all outer years | after the barrier only |
| sr03_component | target | the panel's `a_won` for the persisted SR03 predictions (`component_scoring`) | after the barrier only |

The runner derives `outcome_access.observed` from the audit hook, not from the table
above; a stage that opens an outcome-bearing file it is not declared for fails, and a
declared reader whose accessor receipt exceeds its fold's ceiling fails.

## 3. Nothing scored before the barrier

The barrier stage scans every earlier stage directory (CSV, CSV.GZ, JSON, JSONL;
recursive; header names and nested keys) for metric-shaped content and refuses to freeze
the run tree if it finds any. `verify` repeats the scan. The historical baseline
`180cb2d` wrote these before the barrier; the repaired chain moves them:

| Was (before the barrier) | Now (after the barrier) | Values |
|---|---|---|
| `sr03_calibration/metrics.csv`, `reliability.csv`, `comparisons.json`, `cohort_counts.json` | `sr03_component/` (stage after `report`): the same four files computed by `dynamics.calibrate evaluate` from the persisted `predictions.csv` and the panel | identical rows for every year the archive scored; the component stage scores every outer year with a resolved outcome, so where a frozen config carried `score_years_max` (WTA02) the post-barrier files are a superset |
| `pipeline/selection/<y>/<learner>/<block>.json: candidate_trials[*].annual[*].mean_log_loss`, `equal_year_mean_log_loss`, `selection.ranked[*].score`, `minimum_equal_year_mean_log_loss`, `runner_up_gap` | `report/selection_trials.json`: recomputed by the reporter from the persisted raw predictions, the persisted selection keys and the labels, and checked against the pipeline's commitment hash | identical numbers; the selected candidate, slope and every forecast are unchanged |
| `pipeline/market/<y>/calibration.json: slope_fit.annual[*].mean_log_loss`, `equal_year_mean_log_loss` | `report/selection_trials.json` (market section), same recomputation | identical |
| `pipeline/selection_complete.json` (copies of the above) | same | identical |
| `report/selection_receipts.json` (copied the scored records) | copies the public records and points at `selection_trials.json` | changed bytes; `selection_diagnostics.csv` and the eight named outputs are unchanged |

Before the barrier the pipeline writes, per fold, the decision (selected candidate,
slope, ranked candidate order), the membership hashes, the selection keys
(`selection/<y>/selection_keys.csv`) and `criterion_sha256`, the canonical hash of the
full trial table including the scores. The reporter recomputes the table, verifies the
hash and verifies that the recorded decision is its argmin. A pipeline that emitted a
decision inconsistent with the recomputed criterion fails the report.

## 4. What this does not establish

The audit hook sees `open` calls in the stage's own process; it does not prove dataflow
inside a process, and a stage could in principle read outcomes through a channel that is
not a file open. The planted-leak tests cover the channels the chain has: an undeclared
opener, a nested metric writer, an accessor asked for a later season. Historical
equivalence is a separate verdict (`docs/EQUIVALENCE.md`); the relocation above is an
intentional artifact change, listed there, not an explained provenance difference.

## 5. Ported Lane C2 gates

Archive decision R15/R17 admitted five of Lane C2's thirteen checks as gates (C2 report
table, `docs/reviews/rebuild_2026-09-13/LANE_C2_report.md`); product decision RB12 requires
each to be ported with the negative control that proves it fails on its planted defect.
The five modules below run on the session's synthetic run (`tests/conftest.py:
sample_run`), fail rather than skip when the sample cannot be built, share only
`tests/gate_support.py`, and use the standard library plus numpy. T8 is not ported: it
is the barrier gate itself (§3, `tests/test_barrier_gate.py`). T1, T3–T7 and T12 stay
`not_a_gate` (C2 addendum) and are not turned into acceptance claims here.

| Gate | Product test | Criterion on the synthetic run | Negative controls (same assertion function) | Not covered here |
|---|---|---|---|---|
| T2 feature dates | `tests/test_gate_t02_feature_dates.py` | Date columns discovered from the header and the dictionary's names, groups and roles; `match_date` target, `eligible_through_date` cutoff, `date_basis` / `archive_date_basis` textual; every other date is a source/snapshot date and must be ≤ cutoff on every row (unknown roles fail closed); cutoff precedes target. Sample: 5,350 rows, 5 source columns (`ranking_snapshot_date`, `elo_/count_/workload_/lagged_market_latest_source_date`), 0 violations, min lag 0 days. | A new future source date, a renamed one, an opaque column with dictionary role `source_date`, an opaque column in a `source_date_columns` group, one real row's `elo_latest_source_date` moved one day past its cutoff, and a cutoff equal to the target date each fail and name the column. | T2b satellite circuit dating and T2c base/tier Elo replay at 1e-12: the base sample runs no tier stages. Dates inside serialized free text. |
| T9 learned constants | `tests/test_gate_t09_learned_constants.py` | Every raw fit, candidate trial, selected slope, shared-base slope, market slope and SR03 family slope has a non-empty receipt; fit and selection horizons ≤ 30 December of the year before application; selection window is exactly the configured past years; every training key a fitted model consumed carries a season before its application year and inside the training window; selected/shared slopes equal a recorded trial; per-use receipt files equal the completion inventory with no orphans; learned model and training-key bytes re-hash. Sample: 62 receipts (20 fits, 12 candidate slopes, 6 selected, 6 shared, 3 market, 15 SR03). | Empty selection / market / shared-base inventories, an application-year selection cutoff, a missing candidate trial, a shared slope without a trial, a selected slope without a trial, a missing market receipt, a missing fit manifest, an application-year fit cutoff, an application-year training key (byte hashes rebound), empty raw fits, an application-year SR03 horizon and empty SR03 fits: 14 plants, each rejected. | Annual tier offsets and the retired 2016-12-31 offset counterfactual (no tier stages in the base sample). Metadata horizons only, not a numerical replay of the estimators. |
| T10 manifest integrity | `tests/test_gate_t10_manifest_integrity.py` | Every stage manifest's output table re-hashes from disk with exact membership; `outputs_sha256` is the canonical hash of that table and equals the ledger entry; the ledger chains from genesis; the barrier's `run_tree` names exactly the pre-barrier stages, agrees with each stage's manifest, every leaf re-hashes, and `run_tree_sha256` is non-placeholder and canonical; the report artifact manifest and SR03 run manifest re-hash. A placeholder digest is a defect only over non-empty content (empty `stderr.txt`, empty barrier output map are accurate). Sample: 14 ledger links, 262 manifest files, 233 run-tree leaves, 21 artifact-manifest files. | A changed byte in `features/features.csv`, a broken ledger link, a placeholder `run_tree_sha256`, and a run-tree leaf with its hash omitted (first caught as disagreement with the stage manifest, then as a malformed leaf once the manifest is made to agree): each rejected. | Source truth: matching hashes show the tree is the one the chain froze, not that its inputs were correct. |
| T11 estimand consistency | `tests/test_gate_t11_estimand.py` | (a) Selection records are a complete, duplicate-free inventory with positive primary populations and identical membership per year across blocks. (b) For the primary and priced cohorts the annual and pooled log-loss and Brier deltas of the primary contrast, annual n and membership hashes, pooled n and per-block scores, the raw market score and every number in `primary.json` reproduce from `pipeline/selected/*`, `labels.csv` and `features.csv` within 1e-12. Sample: n = 1,578 / 1,497, 34 comparisons, max error 1.1e-16; primary equal-year / pooled delta 0.0010578 / 0.0010575. | A 1e-8 shift of the priced pooled delta, of an annual delta and of a pooled block score; a corrupted annual membership hash; a NaN pooled market score; a dropped prediction row; a wrong priced n in `primary.json`; a corrupted primary-population hash and a duplicated selection identity: 9 plants, each rejected. | The archive leaderboard rows (`registries/leaderboard.csv`); the product publishes no leaderboard. WTA scoring, as in C2. |
| T13 univariate screen | `tests/test_gate_t13_univariate_screen.py` | Every numeric column except the dictionary's identifier/split columns, in each target year, against the aligned-primary outcome and against each player's next-match outcome: max(AUC, 1 − AUC) ≤ 0.85 (Mann-Whitney AUC with average tie ranks; equals `roc_auc_score` to 1e-16). Sample: 1,578 rows, 221 columns × 3 years × 3 targets = 1,971 scored records, 18 unscorable, 0 alarms; the largest discrimination is the contemporaneous market (0.78). | The true label, its reversed orientation and player A's next-match outcome (orientation-corrected) planted as columns score 1.0 in every year against their own target and are the only alarms; the next-outcome copy's current-label discrimination stays ordinary, so only the temporal sentinel catches it. A four-row oracle checks the shifted-target construction. | The SR02-eligibility half of the archive's `aligned_primary` predicate (sidecar not joined); the cohort is the reporter's label-based primary cohort, asserted equal to the pipeline's committed membership on the sample. A monotone numeric copy alarm is not a general future-data detector. |
