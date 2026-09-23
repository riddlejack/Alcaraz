# Changelog

## 2026-09-23 — ARMS01 ATP result (attempt 002), independently reconstructed

- Added the `full_tier_entry` bundle variant: `full_tier` plus signed Q, LL, WC and PR
  entry-status differences, a symmetric any-qualifier flag and G/M/A/F tournament-level
  flags. The features stage emits the block only when a chain declares
  `entry_level_block`. Raw entry codes, seeds and draw size are forbidden model columns.
  Bundles that do not read the block are unchanged byte for byte. The change also adds
  the `tier_entry` synthetic scenario and the ARMS01 chain configurations (`fb749a1`,
  `f1211d6`).
- Added two declared switches: `entry_level_block_ll_as_no_flag` for the lucky-loser
  sensitivity (`6603b20`) and `entry_any_qualifier_counts_ll` (`d37cbd5`). With `false`,
  the second switch gives the registered any-qualifier definition, which counts Q only.
  The default stays Q or LL, so existing configurations write identical bytes.
- Documented the registered ARMS01 comparison on 18,972 ATP matches from 2017 to 2024 in
  `docs/benchmarks/BUILDOAK_2017_2024_RESULTS.md` and `buildoak_2017_2024.json`. It covers
  `full_tier`, `full_tier_entry` and a walk-forward BuildOak adaptation, the past-only
  blend, the sensitivities, power and provenance hashes. Attempt 002 is primary.
  Attempt 001 counted Q or LL in the any-qualifier flag, which is not the registered
  definition, and is reported as a disclosed sensitivity. Both attempts were
  independently reconstructed (archive decisions D131 and D132).
- Regenerated `docs/RESULTS.md`, `docs/ladder.json`, `docs/ladder.csv`,
  `docs/winner_accuracy.json` and `docs/winner_accuracy.csv` with the new
  `atp_full_tier_entry` rung. The run root is a composed ATP root: TIER01 attempt 002
  features, market and earlier rungs, plus the attempt 002 `full_tier_entry` forecasts.
  Every earlier ATP and WTA value is unchanged.
- The README figure now has six rungs. Its comparison panel shows the eight-year BuildOak
  result beside the 2024 Ultimate Tennis Statistics and Ingram results, and labels each
  row with its cohort and the Alcaraz rung it used.
- The README's lead paragraph, results table, model description and status use only the
  registered ARMS01 sentences (gate 2 supported, gate 1 passed, gate 3 failed). The
  qualifier finding of the 22 September review is told in one paragraph. The stale
  ledger count is dropped and the test count updated.
- Proposed decision RB34: adopt `full_tier_entry` as the ATP incumbent, allow the scoped
  public-comparison claim, and release no blend.

## 2026-09-22 — README rebuilt around the result

- Rebuilt the README around the research question and its answer, with one results figure
  generated from the committed ladder, accuracy and benchmark JSON artifacts by
  `tools/render_results_figure.py` (`make results-figure`, system `python3` with
  matplotlib). Removed the three superseded README figures.
- An independent review of the project and the README draft is recorded in the research
  archive (`docs/reviews/fable_2026-09-22/`).
- `docs/live/README.md` now cites the archive's record of the September 21 pilot
  (issued, unscored).
- No model, data, result table or dependency changed.

## 2026-09-15 — exact live feature replay

- Completed the private two-tour snapshot rehearsal and independent native-feature
  reconstruction for all five trained routes; retained explicit stale-data frontiers.
- Published the independently scored ATP2024 XGBoost comparison: a small numerical
  advantage with inconclusive superiority, without changing the accepted model.

- Added outcome-free snapshot-to-feature replay for ATP P0, P1 and full-tier plus WTA
  base and full, using the accepted feature, sidecar, dynamic and tier state functions.
- Bound ATP 2026 use to the accepted 2024 checkpoint while preserving its original fit,
  calibration and selection metadata; WTA remains on its accepted 2026 checkpoint.
- Separated modeled event chronology from completion, publication and receipt eligibility
  bounds in both trained replay and the fixed Elo baseline.
- Added accepted rule-map reuse, hash-bound SR02 saved-selection checks, state and feature
  receipts, fixture outcome/stat refusal, and honest pending input readiness.
- Recorded the retained ranking and lower-tier freshness limits and simplified public
  Jeff Sackmann / Tennis Abstract attribution.

## 2026-09-14 — portable numerical regression

- Replaced the single synthetic seed after Linux correctly revealed that it did not
  trigger the legacy failure there. The bounded synthetic bank selects on legacy failure
  and independent BFGS qualification before testing the repaired solver.
- Focused checks pass on macOS and pinned hosted Linux, using different qualifying seeds.
  Production solver, numerical tolerances and full CI gates are unchanged; the temporary
  branch-only Linux workflow is excluded from main.

## 2026-09-14 — historical WTA campaign input

- Integrated the independently reconstructed WTA01 2019–2024 binding and its repaired
  audit helper. Retained every historical attempt and the explicit scientific limits;
  campaign fitting and external benchmark acceptance remain pending.

## 2026-09-14 — manual workflow integration and fixture provenance

- Integrated independently accepted synthetic manual workflow repair `5089b24`: immutable
  source receipts, qualified fixtures, ledger-bound versions, confined writes, and
  provisional/final/corrected settlement. Elo only; the real-data D2 snapshot is pending.
- Replaced the source-derived solver regression fixture with an independent synthetic
  construction, preserving the legacy-failure and independent numerical comparison.
- Recorded the owner-approved exception retaining exactly the former fixture in Git
  history, with source attribution and CC BY-NC-SA 4.0 terms.
- Reconciled release status and the collector's dated offline repair/resumption.

## 2026-09-14 — release narrative candidate

- Added a plain-English winner-picking readout for the final ATP and WTA sports rungs,
  including the 101-match partial 2026 WTA cohort and an explicit tie rule.
- Added aggregate-only, reproducible accuracy CSV/JSON files derived from the accepted
  saved forecasts and labels on the same priced cohorts as the model ladder; no model was
  fitted, selected, calibrated, or issued.
- Simplified the visible Jeff Sackmann / Tennis Abstract attribution while retaining
  permission provenance and redistribution limits in the technical source table.
- Reframed the front page around the supported retrospective result and the value of the
  audit trail; removed comprehensive leak-audit, prospective-record, public-model
  benchmark, and completed-snapshot claims.
- Updated `docs/METHODS.md` for the accepted B2 barrier state, exact ATP/WTA configuration
  horizons, market-aligned population limitation, admitted integrity scope, uncertainty,
  and negative results.
- Rebuilt `docs/PROCESS.md` around the human–LLM operating model, independent
  reconstruction, failures that changed the process, and the rejected live slice.
- Replaced stale source prose in `docs/DATA.md` with separate acquisition,
  qualification, and integration states; recorded the TennisMyLife date disagreement and
  the absence of an accepted 2026-09-14 data snapshot.
- Added a standalone profile blurb without invented biography or placeholders.
- Expanded `DATA_LICENSES.md` for Tennis Abstract, TennisMyLife, tracked artifacts, and
  the raw/row-level redistribution boundary.
- Added one reproducible ATP per-year chart generated solely from `docs/ladder.json` by
  `tools/render_ladder_chart.py`.
- Replaced the stale package-description claim of a comprehensive leak audit and public-
  model benchmark; no dependency or build setting changed.

No model, configuration, input data, generated result table, dependency, test, or CI file
was changed. The chart renderer is documentation tooling and does not fit or score a
model.
