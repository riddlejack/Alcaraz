# Fitted model release packaging

`tools/build_model_release.py` builds a deterministic local bundle from the accepted,
immutable archive run outputs. It selects only the model products used by the accepted
historical forecasts:

- ATP HGB base/P0, full/P1 and full-tier checkpoints for target years 2017–2024;
- WTA HGB base and full checkpoints from WTA01 for 2019–2024 and WTA02 for 2025–2026;
- the primary CONFIRM2026 pooled-Elo state through 2026-09-10, whose latest applied source
  date is 2026-08-31.

The HGB calibration slope is not stored in `model.joblib`. The builder binds the selected
candidate and copies that separately learned slope from each run's `selection_complete.json`.
For every checkpoint it reloads the byte-identical fitted estimator through the existing
`tennislab.models.numerical.FittedProcedure`, predicts the already-accepted historical target
feature rows, applies the accepted slope, and requires both raw and calibrated prediction CSV
hashes to match. It reads no labels and computes no scores.

The object audit covers every included checkpoint. It rejects absolute/private path strings,
raw-looking row/label/odds/winner fields, and matrix-like retained arrays. The accepted objects
contain model configuration, ordered feature names and learned estimator state; HGB thresholds
and tree nodes are learned parameters, not retained source rows. Training-key membership files,
feature rows, labels and odds are excluded.

Build from the repository root:

```sh
uv run python tools/build_model_release.py \
  --archive "/path/to/Tennis Research Lab" \
  --output "/path/to/tennislab-accepted-models-2026-09-14" \
  --tar "/path/to/tennislab-accepted-models-2026-09-14.tar.gz"
```

Verify an unpacked bundle without accessing the archive:

```sh
uv run python tools/build_model_release.py \
  --verify "/path/to/tennislab-accepted-models-2026-09-14"
```

`src/tennislab/models/release.py` verifies the complete manifest and the selected model digest
before `joblib` unpickling. It loads one checkpoint plus its calibration slope, accepts a
constructed feature row, and reuses the existing fitted-model `predict` method. It also restores
the complete named-player Elo state into the existing `PooledElo` class.

The non-Elo artifacts are not a complete player-name forecasting application. The bundle's
`REQUIRED_STATE.json` names the missing live feature state and the existing producer for each
piece. Packaging that state is a separate dependency; weights alone must not be described as a
current model or as ready for name-to-probability inference.
