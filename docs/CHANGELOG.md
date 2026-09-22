# Changelog

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
