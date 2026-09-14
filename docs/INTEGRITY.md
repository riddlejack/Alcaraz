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
file; hash-only opens are allowed), "history" (a state replay or panel builder that
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
| tier_block | none | sidecar, tier_elo features, SR02 selected matches | – |
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
