# Changelog

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
