"""Build and verify a local release bundle of accepted fitted model artifacts.

This copies only the selected HGB checkpoint for each accepted tour/rung/year, its
separate past-only calibration slope, schema/configuration material, and the accepted
pooled-Elo state.  It never copies source rows, feature rows, labels, odds, or training
membership files.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from tennislab.models import numerical, pipeline
from tennislab.models.release import (
    load_checkpoint,
    load_elo_state,
    predict_elo,
    predict_feature_row,
    sha256_file,
    verify_bundle,
)

RELEASE_ID = "tennislab-accepted-models-2026-09-14"
PRODUCT_CONFIGS = {
    "elo": "configs/elo.json",
    "atp_p0": "configs/atp_p0.json",
    "atp_p1": "configs/atp_p1.json",
    "atp_full_tier": "configs/atp_full_tier.json",
    "wta_base": "configs/wta_base.json",
    "wta_full": "configs/wta_full.json",
}
RUN_SPECS = (
    {
        "run_id": "TIER01/attempt_002",
        "root": "experiments/runs/TIER01/attempt_002",
        "tour": "ATP",
        "years": tuple(range(2017, 2025)),
        "blocks": ("base", "full", "full_tier"),
        "rungs": {"base": "atp_p0", "full": "atp_p1", "full_tier": "atp_full_tier"},
        "config": "predictor_config/config.2017_2024.json",
        "sidecar": "run/tier_block/trait_latent_sidecar.csv",
    },
    {
        "run_id": "WTA01/attempt_001/primary",
        "root": "experiments/runs/WTA01/attempt_001/primary",
        "tour": "WTA",
        "years": tuple(range(2019, 2025)),
        "blocks": ("base", "full"),
        "rungs": {"base": "wta_base", "full": "wta_full"},
        "config": "predictor_config/config.json",
        "sidecar": "run/sidecar/trait_latent_sidecar.csv",
    },
    {
        "run_id": "WTA02/attempt_002",
        "root": "experiments/runs/WTA02/attempt_002",
        "tour": "WTA",
        "years": (2025, 2026),
        "blocks": ("base", "full"),
        "rungs": {"base": "wta_base", "full": "wta_full"},
        "config": "predictor_config/config.json",
        "sidecar": "run/sidecar/trait_latent_sidecar.csv",
    },
)
ACCEPTANCE_EVIDENCE = (
    (
        "archive",
        "references/TIER01-review-002.md",
        "independent TIER01 attempt 002 result review",
    ),
    (
        "archive",
        "references/WTA02-review.md",
        "independent WTA02 result review",
    ),
    (
        "archive",
        "docs/reviews/rebuild_2026-09-13/LANE_WTA01_BINDING_RECONSTRUCTION.md",
        "independent WTA01 fitted-state reconstruction",
    ),
    (
        "archive",
        "references/CONFIRM2026-review.md",
        "independent bounded CONFIRM2026 result reconstruction",
    ),
    (
        "product",
        "docs/EQUIVALENCE.md",
        "product historical equivalence record",
    ),
)
ELO_STATE_SOURCE = "experiments/runs/CONFIRM2026/elo_001/elo_state_2026-09-10.json"
PRIVATE_PATH_MARKERS = (b"/Users/", b"/home/", b"C:\\Users\\")


class BuildError(RuntimeError):
    """A source binding or bundle invariant failed."""


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def _git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _binding(root: Path, relative: str) -> dict[str, object]:
    path = root / relative
    if not path.is_file():
        raise BuildError(f"missing source artifact: {relative}")
    return {"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _read_prediction(path: Path) -> tuple[list[tuple[str, str]], np.ndarray]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != ("season", "match_id", "p_a_wins"):
            raise BuildError(f"unexpected prediction schema: {path.name}")
        rows = list(reader)
    keys = [(row["season"], row["match_id"]) for row in rows]
    probabilities = np.asarray([float(row["p_a_wins"]) for row in rows], dtype=np.float64)
    return keys, probabilities


def _prediction_bytes(keys: Sequence[tuple[str, str]], probabilities: Sequence[float]) -> bytes:
    lines = ["season,match_id,p_a_wins\n"]
    lines.extend(
        f"{season},{match_id},{repr(float(probability))}\n"
        for (season, match_id), probability in zip(keys, probabilities, strict=True)
    )
    return "".join(lines).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _walk_object(value: object) -> Iterator[tuple[str, object]]:
    seen: set[int] = set()
    stack: list[tuple[str, object]] = [("/", value)]
    while stack:
        path, current = stack.pop()
        if isinstance(current, str | bytes | int | float | bool | type(None) | np.generic):
            yield path, current
            continue
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        yield path, current
        if isinstance(current, Mapping):
            for key, item in current.items():
                stack.append((f"{path}/{key}", item))
        elif isinstance(current, list | tuple):
            for index, item in enumerate(current):
                stack.append((f"{path}/{index}", item))
        elif isinstance(current, set | frozenset):
            for index, item in enumerate(sorted(current, key=repr)):
                stack.append((f"{path}/{index}", item))
        elif isinstance(current, np.ndarray):
            continue
        elif hasattr(current, "__dict__"):
            for key, item in vars(current).items():
                stack.append((f"{path}/{key}", item))


def _audit_model(model: numerical.FittedProcedure) -> dict[str, object]:
    path_strings: list[dict[str, str]] = []
    suspicious_payload_fields: list[str] = []
    arrays: list[dict[str, object]] = []
    class_counts: Counter[str] = Counter()
    suspicious_names = {
        "training_data",
        "training_matrix",
        "training_rows",
        "x_train",
        "y_train",
        "raw_rows",
        "source_rows",
        "source_path",
        "labels",
        "odds",
        "winner",
    }
    for path, value in _walk_object(model):
        leaf = path.rsplit("/", 1)[-1].lower()
        if leaf in suspicious_names:
            suspicious_payload_fields.append(path)
        if isinstance(value, str):
            lowered = value.lower()
            if value.startswith(("/", "~/")) or ":\\" in value or "/users/" in lowered:
                path_strings.append({"object_path": path, "value": value})
        elif isinstance(value, np.ndarray):
            arrays.append(
                {
                    "object_path": path,
                    "shape": list(value.shape),
                    "dtype": str(value.dtype),
                    "elements": int(value.size),
                }
            )
        elif not isinstance(value, bytes | int | float | bool | type(None) | np.generic):
            class_counts[f"{type(value).__module__}.{type(value).__qualname__}"] += 1
    largest = max(arrays, key=lambda item: int(item["elements"]), default=None)
    matrix_like = [
        item for item in arrays if len(item["shape"]) >= 2 and int(item["elements"]) >= 1000
    ]
    return {
        "root_type": f"{type(model).__module__}.{type(model).__qualname__}",
        "root_fields": sorted(vars(model)),
        "estimator_type": f"{type(model.estimator).__module__}.{type(model.estimator).__qualname__}",
        "estimator_feature_count": len(model.estimator_feature_names),
        "identity_vocabulary": model.identity_vocabulary is not None,
        "rms_scale": None if model.rms_scale is None else list(model.rms_scale.shape),
        "array_count": len(arrays),
        "array_elements_total": sum(int(item["elements"]) for item in arrays),
        "largest_array": largest,
        "matrix_like_arrays_at_least_1000_elements": matrix_like,
        "private_or_absolute_path_strings": path_strings,
        "suspicious_retained_payload_fields": sorted(suspicious_payload_fields),
        "class_counts": dict(sorted(class_counts.items())),
        "raw_training_matrix_detected": bool(matrix_like),
        "raw_row_label_odds_or_winner_payload_detected": bool(suspicious_payload_fields),
    }


def _configure_and_assemble(run_root: Path, spec: Mapping[str, object]) -> pipeline.AssembledBundle:
    config = _json(run_root / str(spec["config"]))
    settings = config["settings"]
    # Each frozen run normally executes in a fresh process. Reset the module globals before
    # crossing from the tier-capable ATP contract to the tour-declared WTA contract.
    pipeline.configure_identity(None, None)
    pipeline.configure_bundles()
    pipeline.configure_cohort()
    pipeline.configure_identity(config.get("experiment_id"), settings.get("tour"))
    pipeline.configure_years(settings["year_plan"])
    pipeline.configure_bundles(settings["blocks"], settings["learners"])
    pipeline.configure_cohort(settings.get("cohort"))
    return pipeline.assemble_feature_bundle(
        run_root / "run/features/features.csv",
        run_root / "run/features/column_dictionary.json",
        run_root / str(spec["sidecar"]),
        {
            "base": config["inputs"]["features"]["sha256"],
            "dictionary": config["inputs"]["dictionary"]["sha256"],
            "sidecar": config["inputs"]["sidecar"]["sha256"],
        },
    )


def _selected_checkpoints(
    archive: Path, output: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    models: list[dict[str, Any]] = []
    parity: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    sys.modules.setdefault("joint04_multi01_numerical", numerical)

    for spec in RUN_SPECS:
        run_root = archive / str(spec["root"])
        raw_complete = _json(run_root / "run/pipeline/raw_complete.json")
        selection_complete = _json(run_root / "run/pipeline/selection_complete.json")
        assembled = _configure_and_assemble(run_root, spec)
        raw_index = {
            (
                int(record["year"]),
                str(record["learner"]),
                str(record["block"]),
                str(record["candidate_id"]),
            ): record
            for record in raw_complete["raw_attempts"]
        }
        selected_index = {
            (int(record["outer_year"]), str(record["learner"]), str(record["block"])): record
            for record in selection_complete["selection_records"]
        }
        for year in spec["years"]:
            for block in spec["blocks"]:
                selection = selected_index.get((year, "hgb", block))
                if selection is None:
                    raise BuildError(
                        f"missing selected HGB record: {spec['run_id']}/{year}/{block}"
                    )
                candidate = str(selection["selected_candidate_id"])
                raw = raw_index.get((year, "hgb", block, candidate))
                if raw is None:
                    raise BuildError(
                        f"missing selected raw attempt: {spec['run_id']}/{year}/{block}"
                    )
                cache_id = str(raw["fit_identity_sha256"])
                source_directory = run_root / "run/pipeline/fit_cache" / cache_id
                source_model = source_directory / "model.joblib"
                source_fit_manifest = source_directory / "fit_manifest.json"
                fit_manifest = _json(source_fit_manifest)
                if fit_manifest["fit_identity_sha256"] != cache_id:
                    raise BuildError("fit cache identity differs from directory")
                if sha256_file(source_model) != fit_manifest["model_sha256"]:
                    raise BuildError("source model differs from fit manifest")
                if fit_manifest["config_id"] != raw["config_id"]:
                    raise BuildError("source model config differs from raw attempt")

                rung = spec["rungs"][block]
                release_directory = output / "models" / str(spec["tour"]).lower() / rung / str(year)
                model_relative = (release_directory / "model.joblib").relative_to(output).as_posix()
                fit_relative = (
                    (release_directory / "source_fit_manifest.json").relative_to(output).as_posix()
                )
                _copy(source_model, output / model_relative)
                _copy(source_fit_manifest, output / fit_relative)

                loaded = joblib.load(source_model)
                if not isinstance(loaded, numerical.FittedProcedure):
                    raise BuildError(f"unexpected fitted model type: {type(loaded)!r}")
                audit = _audit_model(loaded)
                if (
                    audit["private_or_absolute_path_strings"]
                    or audit["raw_training_matrix_detected"]
                    or audit["raw_row_label_odds_or_winner_payload_detected"]
                ):
                    raise BuildError(
                        f"selected object content audit failed: {spec['run_id']}/{year}/{block}"
                    )

                raw_prediction_path = run_root / "run/pipeline" / raw["prediction_path"]
                selected_prediction_path = (
                    run_root / "run/pipeline" / selection["selected_prediction_path"]
                )
                keys, expected_raw = _read_prediction(raw_prediction_path)
                selected_keys, expected_selected = _read_prediction(selected_prediction_path)
                if keys != selected_keys:
                    raise BuildError("raw and selected prediction keys differ")
                target_features = assembled.features.subset(keys)
                actual_raw = loaded.predict(target_features).probabilities
                actual_selected = pipeline.apply_slope(
                    actual_raw, float(selection["selected_slope"])
                )
                actual_raw_hash = _digest_bytes(_prediction_bytes(keys, actual_raw))
                actual_selected_hash = _digest_bytes(_prediction_bytes(keys, actual_selected))
                raw_exact = actual_raw_hash == raw["prediction_sha256"]
                selected_exact = actual_selected_hash == selection["selected_prediction_sha256"]
                if not raw_exact or not selected_exact:
                    raise BuildError(f"prediction parity failed: {spec['run_id']}/{year}/{block}")

                source_model_relative = source_model.relative_to(archive).as_posix()
                source_fit_relative = source_fit_manifest.relative_to(archive).as_posix()
                model_entry: dict[str, Any] = {
                    "model_id": f"{str(spec['tour']).lower()}-{rung}-{year}",
                    "tour": spec["tour"],
                    "rung": rung,
                    "feature_block": block,
                    "learner": "hgb",
                    "target_year": year,
                    "source_run": spec["run_id"],
                    "source_model_path": source_model_relative,
                    "source_fit_manifest_path": source_fit_relative,
                    "source_fit_manifest_sha256": sha256_file(source_fit_manifest),
                    "model_path": model_relative,
                    "model_sha256": fit_manifest["model_sha256"],
                    "config_id": fit_manifest["config_id"],
                    "fit_cutoff": fit_manifest["fit_identity"]["fit_cutoff"],
                    "training_rows": fit_manifest["fit_identity"]["training_rows"],
                    "training_feature_sha256": fit_manifest["fit_identity"][
                        "training_feature_sha256"
                    ],
                    "training_label_sha256": fit_manifest["fit_identity"]["training_label_sha256"],
                    "training_keys_sha256": fit_manifest["fit_identity"]["training_keys_sha256"],
                    "selection_cutoff_inclusive": selection["selection_cutoff_inclusive"],
                    "selection_years": selection["selection_years"],
                    "selected_candidate_id": candidate,
                    "calibration_slope": float(selection["selected_slope"]),
                    "calibration_semantics": "past-only candidate selection and nuisance logit-slope calibration",
                    "estimator_feature_names": list(loaded.estimator_feature_names),
                    "raw_prediction_oracle": {
                        "source_path": raw_prediction_path.relative_to(archive).as_posix(),
                        "rows": len(keys),
                        "sha256": raw["prediction_sha256"],
                    },
                    "selected_prediction_oracle": {
                        "source_path": selected_prediction_path.relative_to(archive).as_posix(),
                        "rows": len(keys),
                        "sha256": selection["selected_prediction_sha256"],
                    },
                    "status": "accepted retrospective/development fitted artifact; not a current-state or prospective-performance claim",
                }
                models.append(model_entry)
                parity.append(
                    {
                        "model_id": model_entry["model_id"],
                        "rows": len(keys),
                        "raw_expected_sha256": raw["prediction_sha256"],
                        "raw_actual_sha256": actual_raw_hash,
                        "raw_bytes_identical": raw_exact,
                        "raw_max_abs_probability_difference": float(
                            np.max(np.abs(actual_raw - expected_raw))
                        ),
                        "selected_expected_sha256": selection["selected_prediction_sha256"],
                        "selected_actual_sha256": actual_selected_hash,
                        "selected_bytes_identical": selected_exact,
                        "selected_max_abs_probability_difference": float(
                            np.max(np.abs(actual_selected - expected_selected))
                        ),
                        "labels_or_scores_read": False,
                    }
                )
                audits.append({"model_id": model_entry["model_id"], **audit})

    if len(models) != 40:
        raise BuildError(f"expected 40 selected checkpoints, found {len(models)}")
    audit_summary = {
        "scope": "all 40 selected fitted objects included in this bundle",
        "method": "load each hash-bound joblib through the accepted numerical class; recursively inspect object fields, strings, containers and ndarray shapes",
        "checkpoint_count": len(audits),
        "private_or_absolute_path_strings": sum(
            len(item["private_or_absolute_path_strings"]) for item in audits
        ),
        "models_with_raw_training_matrix": sum(
            bool(item["raw_training_matrix_detected"]) for item in audits
        ),
        "models_with_raw_row_label_odds_or_winner_payload": sum(
            bool(item["raw_row_label_odds_or_winner_payload_detected"]) for item in audits
        ),
        "interpretation": "The joblib objects retain learned estimator parameters/tree state and exact feature schema. They do not retain raw training matrices, source rows, outcome vectors, odds rows, or private paths. Learned thresholds and tree nodes are model state, not retained source rows.",
        "checkpoints": audits,
    }
    return models, parity, audit_summary


def _write_support_files(product: Path, archive: Path, output: Path) -> None:
    for name, relative in PRODUCT_CONFIGS.items():
        _copy(product / relative, output / "configs" / f"{name}.json")
    _copy(
        archive / "experiments/runs/TIER01/attempt_002/run/features/column_dictionary.json",
        output / "schemas/feature_dictionary.json",
    )
    _copy(
        archive / "experiments/runs/TIER01/attempt_002/run/tier_block/tier_dictionary.json",
        output / "schemas/atp_tier_dictionary.json",
    )
    for spec in RUN_SPECS:
        source = archive / str(spec["root"]) / str(spec["config"])
        target_name = str(spec["run_id"]).replace("/", "_") + ".json"
        _copy(source, output / "bindings" / target_name)
    _copy(archive / ELO_STATE_SOURCE, output / "elo/state_2026-09-10.json")


def _missing_state_document() -> dict[str, object]:
    return {
        "status": "non-Elo name-to-probability route incomplete",
        "reason": "The accepted HGB checkpoints consume constructed feature rows; their complete current player-feature state was not serialized as a standalone accepted snapshot.",
        "minimum_missing_state": [
            {
                "state": "player identity and source crosswalk",
                "reused_producer": [
                    "tennislab.panel.crosswalk_v2",
                    "tennislab.panel.wta_join",
                    "tennislab.panel.elo_crosswalk",
                ],
            },
            {
                "state": "overall/surface result Elo, serve-return counts, workload and rest",
                "reused_producer": ["tennislab.features.base"],
            },
            {
                "state": "annual ranking lookup and staleness",
                "reused_producer": [
                    "tennislab.panel.rankings",
                    "tennislab.chronology.ranking_lookup",
                ],
            },
            {
                "state": "age/height/hand sidecar",
                "reused_producer": ["tennislab.features.sidecar"],
            },
            {
                "state": "WTA and ATP SR02 dynamic serve-return probability",
                "reused_producer": [
                    "tennislab.dynamics.sr02_runner",
                    "tennislab.dynamics.replay",
                ],
            },
            {
                "state": "ATP tier Elo, lower-tier experience and tier SR02 dynamic probability",
                "reused_producer": [
                    "tennislab.ratings.tier_stream",
                    "tennislab.ratings.tier_elo",
                    "tennislab.dynamics.sr02_runner",
                ],
            },
        ],
        "available_interface": "Use tennislab.models.release.predict_feature_row with an already-constructed row matching the checkpoint schema.",
        "elo_exception": "The bundled Elo JSON is a complete named-player state and can be loaded with tennislab.models.release.load_elo_state.",
    }


def _bundle_readme() -> str:
    return """# Tennis Lab accepted model artifacts — 2026-09-14

This local release candidate contains the byte-identical selected HGB estimators and their
separately learned calibration slopes for ATP base/P0, ATP full/P1, ATP full-tier, WTA base,
and WTA full. It also contains the complete primary pooled-Elo ATP/WTA state.

Coverage: ATP HGB checkpoints are target years 2017–2024. WTA HGB checkpoints are WTA01
2019–2024 plus WTA02 2025–2026. These dates identify historical annual fit/selection states;
they do not make a checkpoint a current September 2026 feature state. Elo `state_through` is
2026-09-10 while its latest applied source date is 2026-08-31; those are separate facts.

Install the exact locked tennis-lab runtime, then verify and load:

```python
from tennislab.models.release import load_checkpoint, predict_feature_row, verify_bundle

root = "path/to/tennislab-accepted-models-2026-09-14"
verify_bundle(root)
checkpoint = load_checkpoint(root, tour="ATP", rung="atp_full_tier", year=2024)
result = predict_feature_row(checkpoint, already_constructed_feature_values)
```

`joblib` is pickle-based. Never bypass `verify_bundle` or load model files detached from this
manifest. The loader verifies the whole bundle and selected model digest before unpickling.

The HGB artifacts are complete for inference from an already-constructed feature row. They
are not a complete name-to-probability application: see `REQUIRED_STATE.json` for the exact
unserialized feature state and the existing producers that must be reused. Elo is the only
rung with a complete named-player state in this bundle. `examples/synthetic_feature_row.json`
and `examples/run.py` exercise the loader without claiming a real player forecast.

No raw source rows, historical feature rows, outcome labels, odds rows, training membership
files, or source file paths are included. `PARITY.json` records byte-identical inference against
the already-accepted historical prediction files without reading labels or computing scores.

See `LICENSE-NOTICE.md` before redistribution. This directory and its deterministic tarball
are local release candidates only; no tag, GitHub release, or upload is implied.
"""


def _license_notice() -> str:
    return """# License and provenance notice

The tennis-lab source code and loader are MIT-licensed under the product repository's
`LICENSE`. That code license does not automatically determine the license of fitted artifacts.

The bundled fitted HGB estimators and pooled-Elo state are source-derived learned components.
For this release candidate they are treated conservatively under CC BY-NC-SA 4.0, with
attribution to Jeff Sackmann's tennis datasets and the Match Charting Project where applicable,
pending artifact-specific redistribution review. This package is therefore non-commercial and
share-alike. It provides no rights to underlying source databases or provider payloads.

No raw source file, source row, historical feature row, label row, odds row, or training-key
list is included. The models' learned coefficients/scales/tree thresholds and Elo ratings are
retained model state. The exact source hashes and acceptance evidence locators are in
`MANIFEST.json`; absence of raw rows is also checked in `OBJECT_AUDIT.json`.

If artifact-specific review finds that a fitted component is not redistributable under these
terms, remove that component before any public upload. This local package is not legal advice.
"""


def _example_script() -> str:
    return """from __future__ import annotations

import json
from pathlib import Path

from tennislab.models.release import (
    load_checkpoint,
    load_elo_state,
    predict_elo,
    predict_feature_row,
)

ROOT = Path(__file__).resolve().parents[1]
row = json.loads((ROOT / "examples/synthetic_feature_row.json").read_text())

for tour, rung, year in (
    ("ATP", "atp_p0", 2024),
    ("ATP", "atp_p1", 2024),
    ("ATP", "atp_full_tier", 2024),
    ("WTA", "wta_base", 2026),
    ("WTA", "wta_full", 2026),
):
    checkpoint = load_checkpoint(ROOT, tour=tour, rung=rung, year=year)
    print(checkpoint.metadata["model_id"], predict_feature_row(checkpoint, row["values"]))

engine = load_elo_state(ROOT, tour="ATP")
print(
    "elo-cold-start",
    predict_elo(
        engine,
        player_a_name="Synthetic Player A",
        player_b_name="Synthetic Player B",
        surface="Hard",
    ),
)
"""


def _file_inventory(output: Path) -> list[dict[str, object]]:
    role_prefixes = {
        "models/": "byte-identical selected fitted model or source fit manifest",
        "bindings/": "byte-identical accepted predictor configuration",
        "configs/": "byte-identical product rung configuration",
        "schemas/": "byte-identical feature schema/dictionary",
        "elo/": "complete primary pooled-Elo ATP/WTA state",
        "examples/": "synthetic loader example",
    }
    exact_roles = {
        "README.md": "bundle use and limitation guide",
        "LICENSE-NOTICE.md": "code/artifact license boundary and attribution",
        "REQUIRED_STATE.json": "missing non-Elo name-inference state and reused producers",
        "PARITY.json": "accepted historical prediction parity receipt",
        "OBJECT_AUDIT.json": "serialized-content privacy and retained-state audit",
    }
    result: list[dict[str, object]] = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "MANIFEST.json":
            continue
        relative = path.relative_to(output).as_posix()
        role = exact_roles.get(relative)
        if role is None:
            role = next(
                (
                    description
                    for prefix, description in role_prefixes.items()
                    if relative.startswith(prefix)
                ),
                "bundle payload",
            )
        result.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "role": role,
            }
        )
    return result


def _privacy_scan(output: Path) -> None:
    findings: list[str] = []
    for path in output.rglob("*"):
        if not path.is_file():
            continue
        payload = path.read_bytes()
        if any(marker in payload for marker in PRIVATE_PATH_MARKERS):
            findings.append(path.relative_to(output).as_posix())
    if findings:
        raise BuildError(f"private path markers found in bundle: {sorted(findings)}")


def _deterministic_tar(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in sorted(source.rglob("*")):
                    if not path.is_file():
                        continue
                    relative = Path(RELEASE_ID) / path.relative_to(source)
                    info = tarfile.TarInfo(relative.as_posix())
                    info.size = path.stat().st_size
                    info.mode = 0o644
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)


def build(product: Path, archive: Path, output: Path, tar_path: Path | None) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise BuildError(f"output directory must not exist or be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    _write_support_files(product, archive, output)
    models, parity, audit = _selected_checkpoints(archive, output)
    _write_json(
        output / "PARITY.json",
        {
            "status": "PASS",
            "scope": "existing accepted predictions only; no fit, label read, score, or experimental evaluation",
            "checkpoint_count": len(parity),
            "all_raw_bytes_identical": all(item["raw_bytes_identical"] for item in parity),
            "all_selected_bytes_identical": all(
                item["selected_bytes_identical"] for item in parity
            ),
            "checks": parity,
        },
    )
    _write_json(output / "OBJECT_AUDIT.json", audit)
    _write_json(output / "REQUIRED_STATE.json", _missing_state_document())
    _write_text(output / "README.md", _bundle_readme())
    _write_text(output / "LICENSE-NOTICE.md", _license_notice())
    _write_text(output / "examples/run.py", _example_script())
    union_features = sorted({name for model in models for name in model["estimator_feature_names"]})
    _write_json(
        output / "examples/synthetic_feature_row.json",
        {
            "description": "Artificial all-zero constructed model row; not a player or match forecast.",
            "values": {name: 0.0 for name in union_features},
        },
    )

    evidence = []
    for repository, relative, role in ACCEPTANCE_EVIDENCE:
        root = archive if repository == "archive" else product
        evidence.append({"repository": repository, "role": role, **_binding(root, relative)})
    source_bindings = []
    for spec in RUN_SPECS:
        run_root = archive / str(spec["root"])
        source_bindings.append(
            {
                "run_id": spec["run_id"],
                "tour": spec["tour"],
                "target_years": list(spec["years"]),
                "predictor_config": _binding(run_root, str(spec["config"])),
                "raw_complete": _binding(run_root, "run/pipeline/raw_complete.json"),
                "selection_complete": _binding(run_root, "run/pipeline/selection_complete.json"),
                "feature_dictionary": _binding(run_root, "run/features/column_dictionary.json"),
            }
        )
    elo_wrapper = _json(archive / ELO_STATE_SOURCE)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "release_id": RELEASE_ID,
        "snapshot_date": "2026-09-14",
        "status": "local release candidate; no tag or upload",
        "product_source_commit": _git_head(product),
        "archive_head_observed": _git_head(archive),
        "archive_artifact_custody": "local ignored immutable run outputs; identity bound by exact file hashes, not Git blobs",
        "models": sorted(
            models, key=lambda item: (item["tour"], item["rung"], item["target_year"])
        ),
        "elo": {
            "model_id": elo_wrapper["model_id"],
            "source": _binding(archive, ELO_STATE_SOURCE),
            "state_path": "elo/state_2026-09-10.json",
            "state_through": elo_wrapper["state_through"],
            "per_tour": {
                tour: {
                    "latest_source_date": entry["latest_source_date"],
                    "applied_rows": entry["applied_rows"],
                    "players_overall": entry["players_overall"],
                    "player_surface_entries": entry["player_surface_entries"],
                    "state_sha256": entry["state_sha256"],
                }
                for tour, entry in elo_wrapper["tours"].items()
            },
        },
        "source_bindings": source_bindings,
        "acceptance_evidence": evidence,
        "inference_boundary": {
            "constructed_feature_row": "complete for every bundled HGB checkpoint",
            "name_to_probability_non_elo": "incomplete; see REQUIRED_STATE.json",
            "name_to_probability_elo": "complete for the bundled state",
        },
        "license_boundary": {
            "code": "MIT",
            "learned_artifacts": "CC BY-NC-SA 4.0 conservative treatment pending artifact-specific review",
        },
        "excluded": [
            "unselected or rejected candidate fits",
            "raw source files and source rows",
            "historical feature rows",
            "outcome labels and scores",
            "odds rows",
            "training_keys.csv membership files",
            "E campaign artifacts",
        ],
    }

    # The synthetic expected output uses the finished model index but precedes the final file
    # inventory. It proves the public loader path without real match inputs.
    manifest["files"] = _file_inventory(output)
    _write_json(output / "MANIFEST.json", manifest)
    synthetic = []
    example_values = _json(output / "examples/synthetic_feature_row.json")["values"]
    for tour, rung, year in (
        ("ATP", "atp_p0", 2024),
        ("ATP", "atp_p1", 2024),
        ("ATP", "atp_full_tier", 2024),
        ("WTA", "wta_base", 2026),
        ("WTA", "wta_full", 2026),
    ):
        checkpoint = load_checkpoint(output, tour=tour, rung=rung, year=year)
        synthetic.append(
            {
                "model_id": checkpoint.metadata["model_id"],
                **predict_feature_row(checkpoint, example_values),
            }
        )
    elo_engine = load_elo_state(output, tour="ATP")
    synthetic.append(
        {
            "model_id": "elo-atp-cold-start",
            **predict_elo(
                elo_engine,
                player_a_name="Synthetic Player A",
                player_b_name="Synthetic Player B",
                surface="Hard",
            ),
        }
    )
    _write_json(
        output / "examples/expected.json",
        {"status": "synthetic only; not a real forecast", "predictions": synthetic},
    )
    manifest["files"] = _file_inventory(output)
    _write_json(output / "MANIFEST.json", manifest)
    _privacy_scan(output)
    verify_bundle(output)
    if tar_path is not None:
        if tar_path.exists():
            raise BuildError(f"tar output already exists: {tar_path}")
        _deterministic_tar(output, tar_path)
    return {
        "release_id": RELEASE_ID,
        "output": str(output),
        "checkpoint_count": len(models),
        "payload_file_count": len(manifest["files"]),
        "payload_bytes": sum(int(item["bytes"]) for item in manifest["files"]),
        "manifest_bytes": (output / "MANIFEST.json").stat().st_size,
        "manifest_sha256": sha256_file(output / "MANIFEST.json"),
        "tar": str(tar_path) if tar_path else None,
        "tar_bytes": tar_path.stat().st_size if tar_path else None,
        "tar_sha256": sha256_file(tar_path) if tar_path else None,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--tar", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    if args.verify:
        document = verify_bundle(args.verify)
        print(json.dumps({"status": "PASS", "release_id": document["release_id"]}, indent=2))
        return 0
    if args.archive is None or args.output is None:
        parser.error("--archive and --output are required unless --verify is used")
    product = Path(__file__).resolve().parents[1]
    result = build(product, args.archive.resolve(), args.output.resolve(), args.tar)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
