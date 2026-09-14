# elo_baseline (library: `tennislab.ratings.elo`, `tennislab.panel.mirror`, `tennislab.panel.elo_crosswalk`)

Base revision: `references/CONFIRM2026_elo/elo_engine.py`, `references/CONFIRM2026_elo/mirror.py`,
`references/CONFIRM2026_elo/crosswalk.py` — the only revision of each; there is no
TIER01_models/WTA02_models copy of these three files to diff or merge. (The
TIER01/WTA02 `crosswalk_v2.py` wraps `crosswalk.py`; it is a separate port and was
not touched.) Not a chain stage, so `tools/equivalence.py` has no run for it; the
equivalent check is the archive's own Elo baseline run, below.

CONFIRM2026/elo_001 forecast replay (stage 1): **identical**, byte-for-byte.
7,528 forecast rows; produced `forecasts_2025_2026.csv`
sha256 `9097b979b31a982bf4676a075a1ba752e09596520b446b6862d5faa114d1db7e`, equal to
`experiments/runs/CONFIRM2026/elo_001/replay_summary.json` `forecasts_sha256` and to
the archive file's own bytes. Max absolute difference 0.0 on every float column
(`p_pooled_a`, `p_pooled_b`, `p_overall_a`, `p_surface_a`, `elo_overall_logit`,
`elo_surface_logit`); 0 differing cells in the 16 non-float columns.
Prospective state through 2026-09-10, `PooledElo.serialize()` sha256:
ATP `cd1f282d1ffc1b9dc076c474d7951e7ffa3e5ffdb99646ce5cede0d2a5223389`,
WTA `cd3922bcf2fad7e7f4e08740fe490963a4be8c5746e7045432c985e3eba0335f` — both equal
to the archive's.

CONFIRM2026/elo_001/f2 forecast replay: **identical**, byte-for-byte. 8,428 rows;
sha256 `4034b0762c8b47fe8293e7a3f3ed0709e3274279a32c0b1701c6846618db828d`; max
absolute difference 0.0 on every float column; state sha256 ATP
`4f072b502591fac246c1f85a4cca251a6fbf7d08bf2c953f49f4565b2ac4f9bf`, WTA
`9f033fad42b82983152fdb0661174d9f13c7723788e747da3524a08f394873f4`, both equal.

What was compared and how: the archive's replay driver
(`experiments/runs/CONFIRM2026/elo_001/replay.py`, and its F2 wrapper
`f2/replay_v2.py`) carries hard-coded absolute archive paths and writes into the
archive run directory, and neither was in this port's assignment, so it was not
run. Its forecast pass was reproduced verbatim by a scratch script,
`data/runs/elo_check/replay_check.py` (an ignored directory, not part of the
package and not a test), which imports `tennislab.ratings.elo` and reads the
archive's `results_stream.csv` read-only: per tour, `parse_results` over the whole
tour stream as sources and over the 2025/2026 tranches
(`c_tennisdata_2025`, `d_tennisdata_2026`, `e_wikipedia_2026`) as targets, then
`replay(targets, lag_days=2, sources=sources)`, the archive's column order and
`repr()` float rendering; plus `state_as_of(sources, 2026-09-10)`. Nothing was
written inside the archive. Its report is at
`data/runs/elo_check/replay_check_report.json`.

Public interface kept (each module's docstring lists the callers):

* `tennislab.ratings.elo` — `MODEL_ID`, `INITIAL_RATING`, `ELO_K`, `ELO_SCALE`,
  `POOLED_OVERALL_WEIGHT`, `POOLED_SURFACE_WEIGHT`, `POOLING_DOMAIN`,
  `DEFAULT_LAG_DAYS`, `SURFACES`, `RESULT_COLUMNS`, `PlayerKey`, `normalize_name`,
  `player_key`, `key_label`, `Result`, `parse_results`, `read_results_csv`,
  `Prediction`, `PooledElo` (`overall_rating`, `surface_rating`, `probability`,
  `feature_logit`, `history_absent`, `pooled_probability`, `prospective`,
  `apply_batch`, `advance_to`, `serialize`, `state_hash`, and the attributes
  `overall`, `surface`, `overall_matches`, `surface_matches`,
  `latest_source_date`, `applied_rows`), `state_as_of`, `replay`,
  `probability_function`, `_cli`.
  Callers: `tier_elo.py` (`elo_engine` config binding), `crosswalk_v2.py`,
  `regression.py`, `bracket.py`, `daily_ledger.py`, `CONFIRM2026/elo_001/*.py`.
* `tennislab.panel.mirror` — `ARCHIVE_DEFAULT`, `ARCHIVE_ROOT`, `RESERVED_YEARS`,
  `TEAM_EVENTS`, `NEXTGEN_EVENTS`, `TOUR_FINALS_EVENTS`, `SURFACES`,
  `TOUR_LEVELS`, `TOUR_FINALS_BY_TOUR`, `TEAM_EVENT_SUBSTRINGS`,
  `ACCEPTED_STATUS`, `FORBIDDEN_MEMBER_PATTERN`, `ReservedWindowError`,
  `guard_member`, `list_members`, `read_member_rows`, `classify_status`,
  `event_rule`, `anchor_date`, `extract_results`, `CANONICAL_COLUMNS`,
  `write_results_csv`, `active_player_ids`, `_cli`; new: `resolve_archive`.
  Callers: `crosswalk_v2.py` (`_mirror`), `regression.py`, `build_stream.py`,
  `tennislab.panel.elo_crosswalk`.
* `tennislab.panel.elo_crosswalk` — `ACTIVITY_YEARS`, `TENNIS_DATA_STYLE`,
  `CROSSWALK_COLUMNS`, `UNMATCHED_COLUMNS`, `CONFIDENCE`, `Player`, `Crosswalk`
  (`active`, `by_id`, `full`, `surname_initial`, `surname`, `lookup`),
  `load_players`, `build`, `resolve_many`, `write_outputs`, `round_trip`, `_cli`;
  re-exported as the archive copy did: `normalize_name`, `ARCHIVE_DEFAULT`,
  `ARCHIVE_ROOT`, `RESERVED_YEARS`, `extract_results`, `read_member_rows`.
  Callers: `crosswalk_v2.py` (`_elo_crosswalk`), `build_stream.py`.

What changed, and nothing else: the `sys.path` insertions and the sibling imports
(`from elo_engine import ...`, `from mirror import ...`) are replaced by package
imports; `mirror.ARCHIVE_DEFAULT` stays a workspace-relative string and becomes a
path only through the new `mirror.resolve_archive`, which calls
`tennislab.chain.common.resolve_under_root`; every `_cli` resolves the paths it
reads and writes the same way. No absolute path anywhere. Arithmetic, iteration
order, sort keys, name normalisation, `repr()`/`json.dumps(..., sort_keys=True,
separators=(",", ":"))` serialization and CSV column order are untouched — the
byte-identical replay above is the evidence.

Label reads: `elo.PooledElo.apply_batch` reads `Result.a_won` (marked
`# outcome-history read`) — the Elo state update, history only, never scored;
`elo.replay` carries `a_won` into `Prediction` (marked) so a later scoring stage
can join it, and computes no score. `mirror.extract_results` reads winner/loser of
non-reserved seasons (marked); the 2025/2026 match files are refused outright by
`FORBIDDEN_MEMBER_PATTERN`/`guard_member`, which the tests pin.

Learned constants: none measured here. The frozen parameters (1500.0, 32.0, 400.0,
0.5/0.5, lag 2, `probability_space_mean`) are copied from
`work/MULTI01_features/config.json` and `experiments/ELO-DATE-002-C1.json` and are
pinned as literals in `tests/test_elo.py::test_parameters_match_the_validated_sources`,
because those two archive files are not in this repository. ELO-DATE-002-C1 itself
is pinned closed-form in
`tests/test_elo.py::test_pooled_probability_is_the_closed_form_probability_mean`
(overall 1600/1500, Clay 1500/1700, `p_pooled = 0.4401590365774636`).

Tests: `tests/test_elo.py` (12), `tests/test_mirror.py` (11),
`tests/test_elo_crosswalk.py` (8) — 31 in all, green. The archive's `CrosswalkTests` and the mirror
extraction assertions ran against the preserved ~50 MB Sackmann tarball, which is
not in this repository; they are reproduced over a synthetic tarball built in
`tests/test_mirror.py::build_fixture_archive` with the mirror's exact member layout,
sized so every match method, the ambiguity quarantine and every exclusion counter
are exercised. The archive's `RegressionTests`, `BracketTests` and `LedgerTests`
belong to `regression.py`, `bracket.py` and `daily_ledger.py`, which were read for
the interface contract but not ported, and are not in these files.

Open:
* Deliberate deviation from PORTING.md rule 6 (`ChainError`): the archive's own
  exception types are kept — `ValueError` in `elo`, `ValueError` plus
  `ReservedWindowError(RuntimeError)` in `mirror`. These are library modules whose
  unported callers (`bracket.py`, `daily_ledger.py`, `regression.py`,
  `crosswalk_v2.py`) catch or expect those bases, and `ChainError` is itself a
  `ValueError`, so narrowing later stays source-compatible. Narrowing
  `ReservedWindowError` would change what `except RuntimeError` catches and should
  be a single deliberate repository-wide change, not a side effect of this port.
* `mirror`'s low-level readers (`list_members`, `read_member_rows`,
  `extract_results`, `active_player_ids`) still accept any `str | Path` rather than
  forcing `resolve_under_root`, so a caller can hand them a fixture. If the
  integration pass wants containment enforced at that level too, it is a one-line
  change in each and the tests already set `TENNISLAB_WORKSPACE`.
* `elo_crosswalk` gained an `__all__` (not in the archive) to declare which names
  are re-exports that `crosswalk_v2` reads off this module. Drop it if the
  convention elsewhere is no `__all__`.
* No equivalence-harness run exists for these modules because they are not chain
  stages. If `tools/equivalence.py` should grow a library mode, the replay above is
  the comparison it would automate; that file is outside this port's write
  boundary.
