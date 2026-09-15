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
  --output "/path/to/tennislab-accepted-models-2026-09-14-r2" \
  --tar "/path/to/tennislab-accepted-models-2026-09-14-r2.tar.gz"
```

Verify an unpacked bundle without accessing the archive:

```sh
uv run python tools/build_model_release.py \
  --verify "/path/to/tennislab-accepted-models-2026-09-14-r2"
```

`src/tennislab/models/release.py` verifies the complete manifest and the selected model digest
before `joblib` unpickling. This detects a mismatch against the manifest but does not authenticate
an attacker-supplied manifest: verify the official tarball checksum through a trusted channel
before loading it. The loader accepts a constructed HGB feature row and reuses the existing
fitted-model `predict` method. It also restores the Elo state into the existing `PooledElo` class.

The bundled Elo state has numeric source player IDs but no name-key entries. Use source IDs for
Elo inference; unresolved name-only calls fail instead of silently cold-starting. HGB artifacts
are not a complete player-name forecasting application. `REQUIRED_STATE.json` names the missing
identity/feature state and the existing producer for each piece. Packaging that state is a
separate dependency; weights alone must not be described as a current model or as ready for
name-to-probability inference.

## Published model release

The [2026-09-14-r2 bundle](https://github.com/riddlejack/tennis-lab/releases/tag/models-2026-09-14)
is publicly available. [Integrated CI34915514677](https://github.com/riddlejack/tennis-lab/actions/runs/34915514677)
passed for release code `6bd88a62ee3d3c782b4b9c62bb56e67dc0340bdf`. An unauthenticated
download reproduced the exact release bytes and checksum.
Its SHA-256 is `bbe0337006e298897f6dda0ed87f0717d8a451e465235d95078916def74bcfc4`
(3,573,067 bytes). This is the full accepted checkpoint collection described above; no
model was retrained, reduced, or replaced for distribution. It contains 40 fitted models,
40 fit manifests and the pooled-Elo state, all byte-identical to the original candidate.

Release review checked the complete 102-file tar inventory, all model/state hashes, all
40 HGB inference interfaces on asymmetric artificial rows, and the corrected Elo identity
handling. The five focused tests pass. The original 40-checkpoint historical parity covers
92,946 checkpoint-prediction rows, with zero difference; this count includes repeated matches
across checkpoints and is not a unique-match count or a new performance evaluation.

The learned parameters and aggregate state in this exact bundle are distributed under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/), separately from the MIT
loader code. Source attribution and source-specific terms remain in the bundle notice and
[`DATA_LICENSES.md`](../DATA_LICENSES.md). This disposition resolves the artifact-specific
review marked pending when the immutable candidate was built. It grants no additional
rights to the underlying databases and includes no raw match tables or provider payloads.

This review covers the specified release contents. It does not certify arbitrary future
checkpoints, formal privacy guarantees, a complete player-name application or new scientific
performance. The [ranking/Elo comparison](benchmarks/G_L_RESULTS.md) is complete. The
separate four-arm improvement campaign is also complete and independently accepted as
negative/inconclusive; it did not nominate or promote a replacement. A companion package
for its evaluated research weights is proposed separately and has not been released.
See [`CAMPAIGN_E_RESULTS.md`](CAMPAIGN_E_RESULTS.md) for the accepted result boundary.

The evaluated Lane E weights now have a separate deterministic companion candidate and
keyed prepared-feature loader. It preserves all 140 numerical members and 14 fold
decisions without changing this accepted release or its default. See
[`CAMPAIGN_E_MODEL_RELEASE.md`](CAMPAIGN_E_MODEL_RELEASE.md). Publication remains pending
until the integration branch passes CI and the public asset is downloaded and reverified.
