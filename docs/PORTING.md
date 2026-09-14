# Porting guide — archive stage program to package module

This is the contract every ported stage follows. The reconstruction thread checks the
port against it.

## Where things go

| Archive file (`references/TIER01_models/` unless noted) | Module | Stage(s) |
|---|---|---|
| `chain_common.py` | `tennislab.chain.common` (done) | all |
| `runner.YearPlan` | `tennislab.models.year_plan` (done) | all |
| `bridge_res2026.py`, `crosswalk_v2.py`, `market_event_names.json` | `tennislab.sources.bridge`, `tennislab.panel.crosswalk_v2`, `tennislab/sources/market_event_names.json` | bridge |
| `run_archive_panel.py` + `build_archive_panel.py` | `tennislab.panel.archive_panel` (done) | archive_panel |
| `join_candidates.py` (+ `work/MULTI01_market_acquisition/profile_annual.py`) | `tennislab.panel.join`, `tennislab.sources.profile_annual` | join |
| `carry_event_crosswalk.py` | `tennislab.panel.crosswalk_carry` | event_carry_forward |
| `prepare_panel.py` | `tennislab.panel.prepare` | prepare_panel |
| `apply_format_corrections.py` | `tennislab.panel.format_corrections` | format_corrections |
| `carry_rule_rows.py` | `tennislab.panel.rules` | rule_mapping |
| `WTA02_models/wta_market_join.py`, `wta_carry_event_crosswalk.py`, `wta_rule_rows.py`, `wta_rules.json`, `WTA01_event_map/wta_sources.py` | `tennislab.panel.wta_join`, `tennislab.panel.wta_crosswalk_carry`, `tennislab.panel.wta_rules`, `tennislab/panel/wta_rules.json`, `tennislab.sources.wta_sources` | WTA join / event_carry_forward / rule_mapping |
| `SR02_models/dynamic.py`, `path_runner.py`, `protocol.py`, `market.py`, `runner.py` | `tennislab.dynamics.dynamic`, `.path_runner`, `.protocol`, `.market`, `.sr02_runner` | (library) |
| `sr02_replay.py` | `tennislab.dynamics.replay` | sr02_replay, sr02_tier_replay, sr02_tier_noqual_replay |
| `SR03_calibration/calibration.py`, `sr03_calibrate.py` | `tennislab.dynamics.calibration`, `tennislab.dynamics.calibrate` | sr03_calibration |
| `qualify_rankings.py` | `tennislab.panel.rankings` | rankings |
| `work/MULTI01_ranking_lookup/ranking_lookup.py`, `build_edition_index.py` | `tennislab.chronology.ranking_lookup`, `tennislab.chronology.edition_index` | edition_index |
| `build_features.py` | `tennislab.features.base` | features |
| `build_sidecar.py` | `tennislab.features.sidecar` | sidecar |
| `CONFIRM2026_elo/elo_engine.py`, `mirror.py`, `crosswalk.py` | `tennislab.ratings.elo`, `tennislab.panel.mirror`, `tennislab.panel.elo_crosswalk` | (library; Elo baseline) |
| `tier_stream.py`, `tier_elo.py`, `tier_block.py` | `tennislab.ratings.tier_stream`, `tennislab.ratings.tier_elo`, `tennislab.features.tier_block` | tier_stream, tier_elo, tier_block |
| `MULTI01_models/numerical.py`, `runner.py` | `tennislab.models.numerical`, `tennislab.models.pipeline` | preflight, pipeline |
| `build_config.py` | `tennislab.chain.configs` | predictor_config, reporting_config |
| `report.py` | `tennislab.evaluation.report` | report |
| `run_chain.py` | `tennislab.chain.runner` | (the chain driver) |

When the `WTA02_models/` copy of a file is a superset of the `TIER01_models/` copy (a
`tour` switch plus unchanged ATP behaviour), port the WTA02 copy. When the TIER01 copy
carries TIER-specific additions the WTA02 copy lacks, port the TIER01 copy and merge the
WTA02 additions under the tour switch. Diff the two first; say in the module docstring
which revision was the base and what was merged.

## Rules

1. **No `ROOT = Path(__file__)...`, no `sys.path` mutation, no `load_module` by path, no
   absolute path.** Paths in configs resolve through
   `tennislab.chain.common.resolve_under_root(value, label=...)`; workspace-relative
   strings for manifests come from `relative_to_root(path)`. Never call `Path.resolve()`
   on a workspace path (the equivalence workspace links into the archive; a resolved
   path escapes it).
2. **Modules import each other by name.** A config field that pinned a module by path and
   hash (`ranking_lookup_module`, `elo_engine`, `dynamic`/`path_runner` bindings) is
   still read and recorded into the stage's manifest as `declared_binding`, but the code
   that runs is the package module, and the manifest records `code_receipt(__name__)`
   for it. Do not verify the archive file's hash against the package file.
3. **Keep the argv interface exactly as the archive's `stage_manifest.json` `command`
   shows it.** `main(argv: list[str] | None = None) -> int`; the module runs with
   `python -m tennislab.<module>`. The equivalence harness passes the archive's own
   arguments.
4. **Keep every data output byte-identical.** CSV writers, float formatting
   (`format(x, ".17g")`), key ordering, `json.dumps(..., sort_keys=True, indent=2)`, and
   stdout text are part of the contract. Provenance fields that name code paths, code
   hashes or the launcher id may differ; nothing else may.
5. **Pure core, thin CLI.** The stage's work is a function taking parsed inputs and an
   output directory and returning the manifest document; `main` parses argv, reads the
   config and calls it. Split a 2,000-line `main` into named steps, but do not change
   arithmetic, iteration order or serialization while doing so.
6. **Errors are `ChainError`** (or a module-specific subclass of it) and fail closed.
7. **Typed dates.** Where the archive attached a `date_basis` string, keep it; where a
   date is inferred (event anchor + offset, round order), it is a bound and the
   `date_basis` says so. Do not invent a reported date.
8. **Receipts for learned constants.** A stage that measures a constant (offsets,
   slopes, selected candidates) writes the data horizon it was measured on beside the
   value, as the archive's TIER01 revision 2 already does for offsets.
9. **Labels.** Modules before `evaluation.report` must not compute a proper score on
   target-year outcomes. Reading outcomes as *history* (state updates, fits on training
   years, membership counts) is allowed and must go through one accessor,
   `tennislab.chain.labels` (owned by the models group), once it exists; until then keep
   the archive's own reads but mark each with a `# outcome-history read` comment so the
   integration pass can find them.
10. **Tests.** Move the archive's unit tests for the files you port into
    `tests/test_<module>.py`, importing from the package. Add the regression tests the
    brief names where they belong (Spain 1 2006 satellite dating in `tier_stream`,
    Canada-final event-end bound in `chronology`).
11. **Lint.** `uv run ruff format <files>` then `uv run ruff check <files>` clean.
12. **Write boundary.** Only the module files assigned to you, their tests, and your
    note under `docs/equivalence/notes/<stage>.md`. Do not edit `tennislab.chain.common`,
    `tennislab.config`, `tools/equivalence.py` or another group's modules; if you need a
    change there, write it in your note. Do not commit. Never write inside the archive.

## Verifying a stage

```sh
export TENNISLAB_ARCHIVE="/path/to/Tennis Research Lab"
uv run python tools/equivalence.py run --run TIER01/attempt_002 --stage <stage>
uv run python tools/equivalence.py run --run WTA02/attempt_002 --stage <stage>
```

The tool builds `data/runs/equivalence/<run>/` (links into the archive, a real directory
for your stage), runs your module with the archive's argv, compares every output by hash
and writes `docs/equivalence/<run>/<stage>.json`. Read the summary: every file must be
`identical` or differ only in named provenance leaves. Anything else is a defect in the
port, not a tolerance. Write the per-stage note:

```
# <stage>
Base revision: TIER01_models/<file> (WTA02 additions merged: ...)
ATP TIER01/attempt_002: identical <n>/<m>; differing: <file> (<leaves>) — cause
WTA WTA02/attempt_002: ...
Label reads: none | <file> read as history at <function>
Learned constants: none | <name>, horizon <...>
Open: <anything unexplained, or nothing>
```
