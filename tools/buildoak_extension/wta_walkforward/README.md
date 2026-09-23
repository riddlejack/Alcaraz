# WTA walk-forward replay of the frozen buildoak adaptation

Per-target-year driver for the unchanged `runtime/empirical_controller.py`, so that the
accepted WTA 2024 historical adaptation (source pinned at `237d1e7`) can be replayed for
target years 2019–2023 with one fit at each 30 December boundary and that year's own
Elo reference. Nothing here changes the frozen recipe: D−2 releases, the frozen date
hierarchy, transport IDs for reused native keys, training-only IOC vocabulary, the
native WTA menu (0.65/0.35 global ensemble, Hard then level-I specialists, recent-era
blend with its 15,000-row threshold evaluated per fit) and the neutral orientation
contract all come from the controller, the adapter and the pinned image.

- `prepare_year.py` derives a year-Y plan from the frozen WTA 2024 plan. Every row
  keeps its frozen dates, release basis, provenance and source locator; only
  `fit_target` (labels released by the boundary and not a target) and
  `evaluation_target` change. Targets are the WTA01 primary targets of year Y with a
  saved selected forecast (`selected/<Y>/hgb/full.csv`; `labels.csv` is read only for
  `match_id`, `calendar_year`, `primary_target`) and must equal the accepted selection's
  primary membership hash. The plan, memberships and IOC vocabulary keep the frozen
  serialization, so preparing 2024 reproduces the accepted files byte for byte. It also
  writes a metadata-only chronology replay projection and the projected menu.
- `freeze_year.py` binds every input, the adapter, the runtime tools and the immutable
  image (whose adapter bytes are probed with stdlib only) into one `tour: wta`
  authorization.
- Launch with the tour-agnostic `../atp_walkforward/run_year.py` (fresh process under
  `caffeinate -i`, exclusive logs, container sampling, read-only
  `runtime/verify_commitment.py`, `REPLAY_SUMMARY.json`).
- `compare_2024.py` checks a 2024 reproduction against the accepted WTA attempt by
  SHA-256: fit inputs and native forecasts (required), model files, fit receipt, release
  receipts, plan, memberships and vocabulary (informative).
- `map_orientation.py` maps committed native forecasts to the accepted WTA01 panel
  orientation (`match_id, p_a_wins`), the accepted `paired_rows.csv` `external_p_a`
  convention; with `--paired-rows` it copies the accepted 2024 values after checking
  they equal the mapping. It never reads outcomes or scores.
- `synthetic_rehearsal.py` runs the entry points on generated sources whose release
  schedule forces chronology replays; `--generate-only` writes the fixture used by
  `tests/test_buildoak_wta_walkforward.py`.

Attempt layout: `ROOT/preparation/`, `ROOT/AUTHORIZATION.json`, `ROOT/run/` (controller
artefacts and `FORECAST_COMMITMENT.json`), `ROOT/LAUNCH.json`, logs,
`ROOT/verification.json`, `ROOT/REPLAY_SUMMARY.json`, `ROOT/report/`. All empirical
inputs and attempts live in the assigned archive work directory; this checkout holds
code only. Scoring is a separate, later step and is not implemented here.
