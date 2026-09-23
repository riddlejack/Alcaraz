# ATP walk-forward replay of the frozen buildoak adaptation

Per-target-year driver for the unchanged `runtime/empirical_controller.py`, so that the
accepted ATP 2024 historical adaptation (source pinned at `237d1e7`) can be replayed for
target years 2017–2023 with one fit at each 30 December boundary and that year's own
Elo reference. Nothing here changes the frozen recipe: D−2 releases, the frozen date
hierarchy, training-only IOC vocabulary, the native ATP menu (global, level specialists,
recent-era blend with its 15,000-row threshold evaluated per fit) and the neutral
orientation contract all come from the controller, the adapter and the pinned image.

- `prepare_year.py` derives a year-Y plan from the frozen 2024 date hierarchy plan. Every
  row keeps its frozen dates, release basis and provenance; only `fit_target` (labels
  released by the boundary and not a target) and `evaluation_target` (that year's
  accepted all-target cohort, taken from the same forecast carrier D97 used) change, and
  the controller's `source_file`/`source_line` locators are added. It also writes the fit
  and target memberships, the fit-only IOC vocabulary, and a metadata-only chronology
  replay projection. It refuses cohort keys without an accepted reported date, cohort
  sizes that differ from the accepted selection's primary rows, and IOC ties at the
  bucket boundary.
- `freeze_year.py` binds every input, the adapter, the runtime tools and the immutable
  image (whose adapter bytes are probed with stdlib only) into one authorization.
- `run_year.py` launches the controller in a fresh process under `caffeinate -i` with
  exclusive logs, samples container CPU/memory, then runs the read-only
  `runtime/verify_commitment.py` and writes `REPLAY_SUMMARY.json` (timings, replay
  counts, activated members, whether the recent blend activated).
- `compare_2024.py` checks a 2024 reproduction against the accepted D97 attempt by
  SHA-256: fit inputs, native forecasts, fitted model JSON and release receipts.
- `synthetic_rehearsal.py` runs the three entry points on generated sources whose
  release schedule forces chronology replays and a level-A specialist.

Attempt layout: `ROOT/preparation/` (prepare), `ROOT/AUTHORIZATION.json` (freeze),
`ROOT/run/` (the controller's artefacts: `fit_inputs/` with hashes,
`forecast/native_forecasts.csv`, `FORECAST_COMMITMENT.json`, `release_receipts.jsonl`,
container inspect receipts), `ROOT/LAUNCH.json`, logs, `ROOT/verification.json`,
`ROOT/REPLAY_SUMMARY.json`. All empirical inputs and attempts live in the assigned
archive work directory; this checkout holds code only. Scoring is a separate,
later step and is not implemented here.
