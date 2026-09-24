# Changelog

## 2026-09-24 — tier_stream: a spent reserved year needs explicit acknowledgement

- `tennislab.ratings.tier_stream` admits a `last_year` in the reserved window (2025–2026)
  only when its stage config carries `reserved_release_acknowledged: true`; without it the
  two refusals and their messages are unchanged, and `last_year == panel_end_year` is still
  required. `tennislab.chain.runner` copies the chain's own `reserved_release_acknowledged`
  (the field the bridge already reads) into the tier_stream config when it is `true`, so one
  acknowledgement covers both stages; the stage note in the ledger says when a reserved
  year is opened. The stage summary then lists the reserved years opened and never opened,
  and its Futures limit sentence names the count-identity screen that can now touch a
  2025 Futures row with serve counts. No numerical path, default or output for spans ending
  in 2024 or earlier changed (byte-identical on the synthetic inputs; all 12 committed chain
  configs emit identical stage configs). Nine new tests (refusal unchanged, acceptance,
  runner propagation); 737 pass. Needed by the archive's REFIT2025 (the frozen recipe run
  for target season 2025; the 2025–2026 window is spent, archive D130–D135).

## 2026-09-24 — IBM matched comparison, lead decomposition, README section

- **IBM01** (archive decision D135, independently reconstructed): the 37 IBM Match Insights
  pre-match files that the Internet Archive holds for Wimbledon 2023–2024 and the US Open
  2022–2023 were recovered with receipts and joined to this repository's matches; 29 were
  published before the first ball (fixed from archived order-of-play and point-by-point
  feeds before any score was read). On those 29, log loss is 0.4550 (Alcaraz, saved frozen
  forecasts), 0.4394 (Pinnacle) and 0.6285 (IBM); Alcaraz − IBM −0.1735 [−0.2383, −0.1074].
  `docs/benchmarks/IBM01_RESULTS.md`, `ibm01.json` (aggregates and match identities only).
- **WHY01** (exploratory, post hoc): decomposition of the lead over BuildOak, Ultimate Tennis
  Statistics, Ingram and the five Elo/ranking baselines on the saved forecasts: the gap
  concentrates in matches with a qualifier, a player ranked 101–200 or a player with fewer
  than 10 prior main-tour matches; it is earned mainly by the lower-tier history block; it
  is discrimination rather than calibration except against Ingram; when systems disagree,
  Alcaraz is right slightly more often and pays less when wrong.
  `docs/benchmarks/WHY01_LEAD_DECOMPOSITION.md`, `why01.json`.
- README: new section "Where the lead over public models comes from" with the figure
  `docs/assets/alcaraz-lead-by-history.svg` (rendered by `tools/render_results_figure.py`
  from `why01.json`); IBM row in the head-to-head table; first-person plural removed
  throughout.

## 2026-09-23 — README reworked for the portfolio reader

- Rewrote `README.md` around the scoped claim the registered ARMS01 result supports:
  state of the art among public, statistics-only forecasters on every matched test we
  could run, 0.010 log loss behind Pinnacle. The head-to-head table now carries explicit
  columns (their log loss, Alcaraz on the same matches, paired difference with interval,
  seasons ahead) instead of the earlier "x vs y" cells, and explains why Alcaraz's own
  score shifts between match sets (18,972 all-target versus 18,882 priced; 2024 rows
  scored with `full_tier`). Section headings state the point of each section; the
  operating-model paragraph moved out of the README (it stays in `docs/PROCESS.md`).
  Green Code's videos are named as the project's origin and, with IBM, as systems not yet
  compared on matched matches. No number changed; every figure still traces to
  `docs/ladder.json`, `docs/winner_accuracy.json` or `docs/benchmarks/*.json`.
- `tools/render_results_figure.py` also renders `docs/assets/alcaraz-by-season.svg` /
  `.png`: the ARMS01 contrast 2 paired difference per season (Alcaraz ahead of BuildOak
  in 7 of 8), read from `docs/benchmarks/buildoak_2017_2024.json`.
- `docs/METHODS.md`: the market-reference section no longer says no external public-model
  benchmark exists; it points to `docs/benchmarks/`.

## 2026-09-23 — WTA secondary, TUNE01 null and the model freeze

- Integrated the outstanding branches. The WTA entry branch (`73e499f`–`81a95a9`) adds the
  WTA `full_entry` bundle: `full` plus the entry/level block, with a declared per-tour
  `entry_level_map` that defaults to the ATP codes, so ATP outputs are unchanged. Its
  cherry-picked copies of the LL and Q-only switches (`a4cc9b7`, `d083ae2`) resolve to the
  same options as `6603b20` and `d37cbd5`, rebased on the level map. The BuildOak
  walk-forward controller layers for ATP (`e22ed43`) and WTA (`13ba128`) sit under
  `tools/buildoak_extension/`; the vendored BuildOak projection is excluded from ruff so
  its audited bytes stay verbatim, as on the earlier benchmark branch. The TUNE01 branch
  (`2fed784`) adds the menu-driven HGB candidate family with temporal early stopping, seed
  bagging, worker parallelism and curve commitment, plus its chain configuration and menu.
- Documented the ARMS01 WTA secondary on 12,900 WTA matches from 2019 to 2024 in
  `docs/benchmarks/BUILDOAK_WTA_2019_2024_RESULTS.md` and `buildoak_wta_2019_2024.json`,
  with the registered sentences: gate 1 passed (new WTA rung `full_entry`), gate 2
  inconclusive (16% power at the 2024 gap), gate 3 passed, with the blend released as an
  attributed research artefact. Also documented the level-map declaration and its
  disclosures, BuildOak's 2024 structural break, the sensitivities, power and provenance.
  Independently reconstructed (archive decision D133).
- Documented TUNE01 in `docs/benchmarks/TUNE01_RESULTS.md` and `tune01.json`: one
  registered 110-candidate tuning pass over the boosted-tree head, TUNE01 − Arm 0
  −0.0000305 [−0.0003924, +0.0003305], gate failed. The model is frozen at
  `full_tier_entry`; no further feature or learner search. Independently reconstructed
  (archive decision D134).
- Regenerated `docs/RESULTS.md`, `docs/ladder.json` and `docs/ladder.csv` with a WTA01
  2019–2024 section (new rung config `configs/wta_full_entry.json`). Its run root is
  composed from WTA01 attempt 001 features, market and `base`/`full` forecasts plus the
  ARMS01 WTA attempt 002 `full_entry` forecasts, with a `LADDER_ROOT.json` receipt. Every
  ATP and WTA 2025–26 value is unchanged. The experiment-ledger count is now 125.
- Refreshed `data/registries/experiments.jsonl` from the archive ledger (12 new rows,
  through D134); the leaderboard copy was already current.
- `tennislab report` no longer accepts abbreviated options. `--run` used to resolve to
  `--runs`, and repeating it kept only the last value, so a second run root silently
  replaced the first. `--run` is now an explicit repeatable option that accumulates with
  `--runs`.
- `docs/benchmarks/BUILDOAK_2017_2024_RESULTS.md` records the fit-record check that
  `entry_ll_diff` is never split on in the fits behind the selected 2017, 2018, 2023 and
  2024 forecasts, and points to the WTA and TUNE01 results.
- The README reports the WTA secondary with its registered sentences, adds the WTA
  BuildOak and blend rows, the tuning null and the model freeze, and updates the test
  count.
- Recorded RB35 (WTA secondary, mirroring D133) and RB36 (TUNE01 null and model freeze,
  mirroring D134), accepted by the research lead.

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
