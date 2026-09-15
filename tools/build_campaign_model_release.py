"""Build and verify the retrospective Lane E research-model companion bundle.

The source allowlist is exactly 140 fitted estimators, their 140 fit manifests, and 14
target-fold decisions from the independently accepted D93/D94 campaign. No source rows,
feature matrices, labels, forecasts, workbooks, or custody documents are copied.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import json
import math
import platform
import shutil
import subprocess
import sys
import tarfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from tennislab.campaign.members import MEMBER_IDS, NUMERICAL_MEMBER_IDS
from tennislab.models import numerical
from tennislab.models.release import (
    LoadedCampaignMember,
    combine_campaign_candidates,
    open_campaign_bundle,
    predict_campaign_feature_row,
    sha256_file,
    verify_bundle,
)

RELEASE_ID = "tennislab-campaign-e-research-models-2026-09-15"
ACCEPTED_SUCCESSOR_COMMIT = "644a57d1dc8bc662dc949fd5c9637b2b7c8bbffd"
RESULT_REVIEW_SHA256 = "4e872a983d79721d3262924b0367c655c2d290c44608ddcf10fae84f7b9d8119"
RUNTIME_VERSIONS = {
    "joblib": "1.6.0",
    "numpy": "2.5.3",
    "scikit-learn": "1.9.1",
    "scipy": "1.18.1",
}
PRIVATE_PATH_MARKERS = (b"/Users/", b"/home/", b"C:\\Users\\")
EXPECTED_TYPES = {
    "hgb": "sklearn.ensemble._hist_gradient_boosting.gradient_boosting.HistGradientBoostingClassifier",
    "ridge": "sklearn.linear_model._logistic.LogisticRegression",
    "rf": "sklearn.ensemble._forest.RandomForestClassifier",
}
SOURCE_SPECS = {
    "ATP": {
        "model_root": "work/campaign_e_v1/real/atp/attempt_007/inputs/producer/numerical",
        "decision_root": "work/campaign_e_v1/consumer_ec01/atp/attempt_001/run/forecast/decisions",
        "raw_years": tuple(range(2014, 2025)),
        "target_years": tuple(range(2017, 2025)),
        "inventory": {
            "models": (
                77,
                297_059_106,
                "26dc5ebb6cfdb0f761d19df95691c52f1cb89940ba8678ff6f0b357bd0d7196b",
            ),
            "fit_manifests": (
                77,
                696_336,
                "5857024a03476a80a9fad85fdf94883841f5010316ee541b1d678569fa28b3f9",
            ),
            "decisions": (
                8,
                52_397,
                "cb3391f683ca52f89e300f9bf947053271c1651654de7db5f412c870bfd7a198",
            ),
        },
    },
    "WTA": {
        "model_root": "work/campaign_e_v1/real/wta/attempt_004/inputs/producer/numerical",
        "decision_root": "work/campaign_e_v1/consumer_ec01/wta/attempt_001/run/forecast/decisions",
        "raw_years": tuple(range(2016, 2025)),
        "target_years": tuple(range(2019, 2025)),
        "inventory": {
            "models": (
                63,
                247_372_310,
                "718e7ab714d02c5d630e2227e74757d5b607d484b55f00b9a5e7febcf4a4067d",
            ),
            "fit_manifests": (
                63,
                536_237,
                "fcbdb9507e7b7f94a858ac33aa754635cde4df65a39d9677ae36e221ba4ecffa",
            ),
            "decisions": (
                6,
                39_267,
                "84816e6d44b41f4814d108f4b47300eed6015d2ad3dc8bb6cf029e5f1e516a04",
            ),
        },
    },
}


class BuildError(RuntimeError):
    """A source, privacy, inference, or deterministic-package invariant failed."""


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


def _copy(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise BuildError(f"source payload is not a regular file: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if target.stat().st_size != source.stat().st_size or sha256_file(target) != sha256_file(source):
        raise BuildError(f"copied payload differs: {source.name}")


def _git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _require_clean_tracked_tree(root: Path) -> None:
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status:
        raise BuildError(
            "product tracked tree must be clean so the source commit identifies the loader"
        )


def _inventory_digest(paths: Sequence[Path], root: Path) -> tuple[int, int, str]:
    lines = []
    total = 0
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        total += size
        lines.append(f"{relative}\t{size}\t{sha256_file(path)}\n")
    digest = hashlib.sha256("".join(lines).encode()).hexdigest()
    return len(paths), total, digest


def _source_paths(source: Path, tour: str) -> dict[str, list[Path]]:
    spec = SOURCE_SPECS[tour]
    model_root = source / str(spec["model_root"])
    decision_root = source / str(spec["decision_root"])
    paths = {
        "models": sorted(model_root.glob("*/*/model.joblib")),
        "fit_manifests": sorted(model_root.glob("*/*/fit_manifest.json")),
        "decisions": sorted(decision_root.glob("*.json")),
    }
    expected_pairs = {
        (year, member_id) for year in spec["raw_years"] for member_id in NUMERICAL_MEMBER_IDS
    }
    actual_models = {(int(path.parts[-3]), path.parts[-2]) for path in paths["models"]}
    actual_manifests = {(int(path.parts[-3]), path.parts[-2]) for path in paths["fit_manifests"]}
    if actual_models != expected_pairs or actual_manifests != expected_pairs:
        raise BuildError(f"{tour} numerical source inventory is not the fixed year/member grid")
    actual_decisions = {int(path.stem) for path in paths["decisions"]}
    if actual_decisions != set(spec["target_years"]):
        raise BuildError(f"{tour} decision source inventory is not the fixed target-year grid")
    roots = {
        "models": model_root,
        "fit_manifests": model_root,
        "decisions": decision_root,
    }
    for category, category_paths in paths.items():
        if any(path.is_symlink() or not path.is_file() for path in category_paths):
            raise BuildError(f"{tour} {category} contains a symlink or non-file")
        observed = _inventory_digest(category_paths, roots[category])
        expected = spec["inventory"][category]
        if observed != expected:
            raise BuildError(f"{tour} {category} source inventory differs: {observed!r}")
    return paths


def _runtime_document(product: Path) -> dict[str, object]:
    observed = {
        distribution: importlib.metadata.version(distribution) for distribution in RUNTIME_VERSIONS
    }
    if observed != RUNTIME_VERSIONS or platform.python_version() != "3.14.6":
        raise BuildError(f"runtime differs from the frozen campaign runtime: {observed!r}")
    return {
        "python_requirement": ">=3.14,<3.15",
        "verified_python": platform.python_version(),
        "packages": observed,
        "product_source_commit": _git_head(product),
        "pyproject_sha256": sha256_file(product / "pyproject.toml"),
        "uv_lock_sha256": sha256_file(product / "uv.lock"),
    }


def _family(member_id: str) -> str:
    if member_id.startswith("hgb_"):
        return "hgb"
    if member_id.startswith("ridge_"):
        return "ridge"
    if member_id.startswith("rf_"):
        return "rf"
    raise BuildError(f"unexpected numerical member: {member_id}")


def _walk_object(value: object):
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
    matrix_like = [
        item for item in arrays if len(item["shape"]) >= 2 and int(item["elements"]) >= 1000
    ]
    return {
        "root_type": f"{type(model).__module__}.{type(model).__qualname__}",
        "root_fields": sorted(vars(model)),
        "estimator_type": f"{type(model.estimator).__module__}.{type(model.estimator).__qualname__}",
        "estimator_feature_count": len(model.estimator_feature_names),
        "array_count": len(arrays),
        "array_elements_total": sum(int(item["elements"]) for item in arrays),
        "largest_array": max(arrays, key=lambda item: int(item["elements"]), default=None),
        "private_or_absolute_path_strings": path_strings,
        "raw_training_matrix_detected": bool(matrix_like),
        "raw_row_label_odds_or_winner_payload_detected": bool(suspicious_payload_fields),
    }


def _asymmetric_rows(
    model: numerical.FittedProcedure, tour: str
) -> tuple[dict[str, float], dict[str, float]]:
    signed = list(
        model.config.get("signed_numeric_columns", model.config.get("numeric_columns", []))
    )
    context = list(model.config.get("context_columns", []))
    if set((*signed, *context)) != set(model.estimator_feature_names):
        raise BuildError("model feature order is not explained by its signed/context contract")
    original = {name: ((index % 7) - 3) * 0.37 for index, name in enumerate(signed)}
    defaults = {
        "context_clay": 1.0,
        "context_grass": 0.0,
        "context_carpet": 0.0,
        "context_best_of_5": 1.0 if tour == "ATP" else 0.0,
        "context_indoor": 0.0,
        "context_indoor_unknown": 0.0,
        "ranking_global_age_days": 14.0,
        "ranking_global_stale": 0.0,
        "trait_mean_z_age": 0.2,
        "trait_mean_centered_height": 0.1,
        "trait_age_missing_sum": 0.0,
        "trait_height_missing_sum": 0.0,
        "trait_hand_missing_sum": 0.0,
    }
    original.update({name: defaults.get(name, 0.25) for name in context})
    reflected = {**original, **{name: -original[name] for name in signed}}
    return original, reflected


def _object_audit(
    model: numerical.FittedProcedure,
    fit_manifest: Mapping[str, Any],
    *,
    tour: str,
    raw_year: int,
    member_id: str,
) -> dict[str, Any]:
    audit = _audit_model(model)
    if (
        audit["private_or_absolute_path_strings"]
        or audit["raw_training_matrix_detected"]
        or audit["raw_row_label_odds_or_winner_payload_detected"]
        or model.identity_vocabulary is not None
    ):
        raise BuildError(f"serialized-content audit failed: {tour}/{raw_year}/{member_id}")
    sample_weight = getattr(model.estimator, "_sample_weight", None)
    uniform_sample_weight: dict[str, Any] | None = None
    if _family(member_id) == "rf":
        expected_rows = 2 * int(fit_manifest["fit_identity"]["training_rows"])
        if (
            not isinstance(sample_weight, np.ndarray)
            or sample_weight.shape != (expected_rows,)
            or not np.all(sample_weight == 0.5)
        ):
            raise BuildError(f"RF retained sample-weight contract differs: {tour}/{raw_year}")
        uniform_sample_weight = {
            "shape": list(sample_weight.shape),
            "unique_value": 0.5,
            "interpretation": "uniform augmentation weights only; no row values, keys, or labels",
        }
    elif sample_weight is not None:
        raise BuildError(f"unexpected retained sample-weight vector: {tour}/{raw_year}/{member_id}")
    return {
        "tour": tour,
        "raw_year": raw_year,
        "member_id": member_id,
        "root_type": audit["root_type"],
        "root_fields": audit["root_fields"],
        "estimator_type": audit["estimator_type"],
        "estimator_feature_count": audit["estimator_feature_count"],
        "array_count": audit["array_count"],
        "array_elements_total": audit["array_elements_total"],
        "largest_array": audit["largest_array"],
        "uniform_rf_sample_weight": uniform_sample_weight,
        "private_or_absolute_path_strings": [],
        "raw_training_matrix_detected": False,
        "raw_row_label_odds_or_winner_payload_detected": False,
    }


def _model_record(
    source_model: Path,
    source_fit: Path,
    output: Path,
    *,
    tour: str,
    raw_year: int,
    member_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fit_manifest = _json(source_fit)
    if (
        fit_manifest.get("status") != "complete"
        or fit_manifest.get("model_path") != "model.joblib"
        or fit_manifest.get("model_sha256") != sha256_file(source_model)
        or not isinstance(fit_manifest.get("estimator_feature_names"), list)
        or len(fit_manifest["estimator_feature_names"])
        != len(set(fit_manifest["estimator_feature_names"]))
    ):
        raise BuildError(f"source fit manifest differs: {tour}/{raw_year}/{member_id}")
    release_dir = output / "models" / tour.lower() / str(raw_year) / member_id
    model_path = release_dir / "model.joblib"
    fit_path = release_dir / "source_fit_manifest.json"
    _copy(source_model, model_path)
    _copy(source_fit, fit_path)

    sys.modules.setdefault("joint04_multi01_numerical", numerical)
    model = joblib.load(source_model)
    if not isinstance(model, numerical.FittedProcedure):
        raise BuildError(f"unexpected fitted object: {type(model)!r}")
    family = _family(member_id)
    estimator_type = f"{type(model.estimator).__module__}.{type(model.estimator).__qualname__}"
    if (
        estimator_type != EXPECTED_TYPES[family]
        or model.config.get("config_id") != fit_manifest.get("config_id")
        or list(model.estimator_feature_names) != fit_manifest["estimator_feature_names"]
    ):
        raise BuildError(f"model identity or type differs: {tour}/{raw_year}/{member_id}")
    audit = _object_audit(
        model,
        fit_manifest,
        tour=tour,
        raw_year=raw_year,
        member_id=member_id,
    )
    metadata = {
        "tour": tour,
        "raw_year": raw_year,
        "member_id": member_id,
        "family": model.config["family"],
        "config_id": fit_manifest["config_id"],
        "model_path": model_path.relative_to(output).as_posix(),
        "model_sha256": sha256_file(model_path),
        "fit_manifest_path": fit_path.relative_to(output).as_posix(),
        "fit_manifest_sha256": sha256_file(fit_path),
        "estimator_type": estimator_type,
        "estimator_feature_names": list(model.estimator_feature_names),
    }
    member = LoadedCampaignMember(model=model, metadata=metadata)
    first_row, reflected_row = _asymmetric_rows(model, tour)
    first = predict_campaign_feature_row(member, first_row, match_id="asymmetric-a")
    reflected = predict_campaign_feature_row(member, reflected_row, match_id="asymmetric-b")
    first_probability = first["raw_probability_a"]
    reflected_probability = reflected["raw_probability_a"]
    residual = abs(first_probability + reflected_probability - 1.0)
    if (
        not 0.0 < first_probability < 1.0
        or not 0.0 < reflected_probability < 1.0
        or first_probability == reflected_probability
        or residual > 1e-14
    ):
        raise BuildError(f"asymmetric inference failed: {tour}/{raw_year}/{member_id}")
    inference = {
        "tour": tour,
        "raw_year": raw_year,
        "member_id": member_id,
        "first_probability_a": first_probability,
        "reflected_probability_a": reflected_probability,
        "complement_residual": residual,
        "artificial_rows_only": True,
    }
    return metadata, audit, inference


def _decision_record(
    source_path: Path, output: Path, *, tour: str, target_year: int
) -> dict[str, Any]:
    decision = _json(source_path)
    try:
        trials = decision["S2"]["candidate_trials"]
        selection = decision["S2"]["selection"]
        member_order = decision["S3"]["member_order"]
        coefficients = decision["S3"]["coefficients"]
    except (KeyError, TypeError) as error:
        raise BuildError(f"decision lacks learned parameters: {tour}/{target_year}") from error
    slopes = {
        member_id: float(trials[member_id]["slope"]) for member_id in ("rf_leaf50", "rf_leaf100")
    }
    if (
        decision.get("outer_year") != target_year
        or decision.get("target_outcomes_read_or_scored") is not False
        or member_order != list(MEMBER_IDS)
        or len(coefficients) != len(MEMBER_IDS)
        or any(
            not math.isfinite(value) or value < 0.0 for value in (*slopes.values(), *coefficients)
        )
    ):
        raise BuildError(f"decision contract differs: {tour}/{target_year}")
    selected_member = str(selection["selected_candidate_id"])
    selected_slope = float(selection["selected_slope"])
    if selected_member not in slopes or selected_slope != slopes[selected_member]:
        raise BuildError(f"selected S2 parameter differs: {tour}/{target_year}")
    target = output / "decisions" / tour.lower() / f"{target_year}.json"
    _copy(source_path, target)
    return {
        "tour": tour,
        "target_year": target_year,
        "path": target.relative_to(output).as_posix(),
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "s2_candidate_slopes": slopes,
        "s2_selected_member": selected_member,
        "s2_selected_slope": selected_slope,
        "s3_member_order": member_order,
        "s3_coefficients": coefficients,
    }


def _required_state() -> dict[str, Any]:
    return {
        "status": "prepared-feature and historical-fold state required",
        "historical_identity": "Raw years and target folds identify the accepted outcome-exposed historical campaign; they are not current September 2026 model state.",
        "required_for_numerical_member_inference": [
            "a constructed row in the selected fit manifest's exact estimator_feature_names order",
            "chronological overall/surface Elo, serve-return, workload/rest, ranking, and trait state",
            "tour-specific dynamic serve-return state and ATP tier state where the member schema requires them",
        ],
        "required_for_S2": "the raw probability from the decision's selected RF member plus its saved target-fold slope",
        "required_for_S3": "all eight raw member probabilities in the saved member order, including separately constructed result Elo",
        "not_bundled": [
            "player-name/source-ID crosswalk and current feature state",
            "source rows or workbooks",
            "training or target feature rows and matrices",
            "training memberships and outcome labels",
            "raw-member or combined forecast files",
            "odds or market rows",
        ],
        "existing_producers": [
            "tennislab.features.base",
            "tennislab.panel.rankings and tennislab.chronology.ranking_lookup",
            "tennislab.features.sidecar",
            "tennislab.dynamics.sr02_runner and tennislab.dynamics.replay",
            "tennislab.ratings.tier_stream and tennislab.ratings.tier_elo for ATP",
        ],
    }


def _bundle_readme() -> str:
    return """# Tennis Lab Lane E research-model artifacts — 2026-09-15

This companion preserves the exact 140 numerical estimators, 140 source fit manifests,
and 14 target-fold decisions evaluated in the independently accepted Lane E campaign.
The campaign was negative/inconclusive: no candidate passed the nomination screen, and
the accepted incumbent remains the product default in the separate `models-2026-09-14`
release. This bundle is retrospective, outcome-exposed research evidence, not a promotion.

The keyed loader verifies the complete bundle before any pickle is loaded, then rechecks
the selected model and fit manifest immediately before deserialization:

```python
from tennislab.models.release import (
    combine_campaign_candidates,
    open_campaign_bundle,
    predict_campaign_feature_row,
)

bundle = open_campaign_bundle("path/to/tennislab-campaign-e-research-models-2026-09-15")
member = bundle.load_member(tour="ATP", raw_year=2024, member_id="rf_leaf100")
raw = predict_campaign_feature_row(member, already_constructed_feature_values)
decision = bundle.load_decision(tour="ATP", target_year=2024)
combined = combine_campaign_candidates(decision, all_eight_raw_member_probabilities)
```

The model key is `(tour, raw_year, member_id)`. ATP raw years are 2014–2024 and WTA
raw years are 2016–2024; each has seven numerical members. The decision key is
`(tour, target_year)`, covering ATP 2017–2024 and WTA 2019–2024. `result_elo` is the
eighth S3 member but is constructed from chronological state and has no fitted pickle.

`joblib` uses pickle and can execute code. Authenticate the official tarball SHA-256
through a trusted release channel before unpacking, keep `MANIFEST.json` attached, and
call `open_campaign_bundle`. Manifest hashes detect corruption relative to that manifest;
an attacker-supplied replacement manifest does not authenticate itself.

The estimators accept prepared feature rows only. They are not a current player-name
forecasting application. `REQUIRED_STATE.json` identifies the historical feature/state
boundary. The package excludes source rows/workbooks, feature matrices, labels, training
memberships, forecasts, odds, private paths, and custody files. `OBJECT_AUDIT.json` and
`INFERENCE_CHECK.json` record the all-model inspection and artificial asymmetric checks.
"""


def _license_notice() -> str:
    return """# License, attribution, and provenance boundary

The tennis-lab source code and release loader are MIT-licensed. The fitted estimators,
learned slopes/coefficients, and fit manifests in this companion are treated conservatively
under CC BY-NC-SA 4.0, separately from the code. That treatment does not relicense or grant
rights to any underlying database.

Source credits and roles:

- Jeff Sackmann ATP/WTA datasets (https://github.com/JeffSackmann), CC BY-NC-SA 4.0:
  primary historical result, ranking, and player inputs.
- tennis-data.co.uk (https://www.tennis-data.co.uk/): local result additions and
  descriptive market/reference fields; no workbook, odds row, or source row is included.
- Wikipedia (https://www.wikipedia.org/), CC BY-SA 4.0: labelled secondary recent
  draw/result additions; no raw page capture or row is included.

Tennis Abstract player collection is not integrated into these campaign models. Match
Charting Project material was research corroboration, not a model input. WTA inherited
outcome-assisted rule provenance remains a disclosed scientific limitation, not a new
redistribution claim.

No source file, source row, feature row/matrix, outcome label, training membership,
forecast row, odds row, or private custody path is included. Source-data terms continue
to govern the omitted underlying material. This notice is not legal advice.
"""


def _file_inventory(output: Path) -> list[dict[str, Any]]:
    roles = {
        "README.md": "use and scientific-boundary guide",
        "LICENSE-NOTICE.md": "artifact license and source attribution",
        "REQUIRED_STATE.json": "prepared-feature and historical-state boundary",
        "RUNTIME.json": "exact verified runtime and product bindings",
        "SOURCE_INVENTORY.json": "trusted fixed-source allowlist receipt",
        "OBJECT_AUDIT.json": "all-model retained-content audit",
        "INFERENCE_CHECK.json": "all-model asymmetric artificial inference receipt",
    }
    files = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "MANIFEST.json":
            continue
        relative = path.relative_to(output).as_posix()
        role = roles.get(relative)
        if role is None:
            role = "byte-identical fitted estimator and source fit manifest"
            if relative.startswith("decisions/"):
                role = "byte-identical target-fold S2/S3 decision"
        files.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "role": role,
            }
        )
    return files


def _privacy_scan(output: Path) -> None:
    findings = []
    for path in output.rglob("*"):
        if path.is_file() and any(marker in path.read_bytes() for marker in PRIVATE_PATH_MARKERS):
            findings.append(path.relative_to(output).as_posix())
    if findings:
        raise BuildError(f"private path markers found in package: {findings}")
    forbidden_suffixes = {".csv", ".xlsx", ".xls", ".parquet", ".feather"}
    forbidden = [
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() and path.suffix.lower() in forbidden_suffixes
    ]
    if forbidden:
        raise BuildError(f"row or workbook payload entered the package: {forbidden}")


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


def verify_release(root: Path) -> dict[str, Any]:
    manifest = verify_bundle(root)
    if manifest.get("release_id") != RELEASE_ID:
        raise BuildError("unexpected campaign release ID")
    models = manifest.get("campaign_models")
    decisions = manifest.get("campaign_decisions")
    if not isinstance(models, list) or len(models) != 140:
        raise BuildError("campaign release must contain 140 model records")
    if not isinstance(decisions, list) or len(decisions) != 14:
        raise BuildError("campaign release must contain 14 decision records")
    bundle = open_campaign_bundle(root)
    types: Counter[str] = Counter()
    max_residual = 0.0
    for metadata in models:
        member = bundle.load_member(
            tour=metadata["tour"],
            raw_year=metadata["raw_year"],
            member_id=metadata["member_id"],
        )
        types[type(member.model.estimator).__name__] += 1
        first_row, reflected_row = _asymmetric_rows(member.model, metadata["tour"])
        first = predict_campaign_feature_row(member, first_row)["raw_probability_a"]
        reflected = predict_campaign_feature_row(member, reflected_row)["raw_probability_a"]
        residual = abs(first + reflected - 1.0)
        if first == reflected or residual > 1e-14:
            raise BuildError("verified campaign model failed asymmetric inference")
        max_residual = max(max_residual, residual)
    for metadata in decisions:
        decision = bundle.load_decision(tour=metadata["tour"], target_year=metadata["target_year"])
        artificial = {member_id: 0.17 + 0.07 * index for index, member_id in enumerate(MEMBER_IDS)}
        combined = combine_campaign_candidates(decision, artificial)
        if any(not 0.0 < value < 1.0 for value in combined.values()):
            raise BuildError("verified campaign decision emitted an invalid probability")
    return {
        "status": "PASS",
        "files": len(manifest["files"]),
        "models": len(models),
        "decisions": len(decisions),
        "estimator_types": dict(sorted(types.items())),
        "maximum_asymmetric_complement_residual": max_residual,
    }


def build(product: Path, source: Path, output: Path, tar_path: Path | None) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise BuildError(f"output directory must not exist or be empty: {output}")
    _require_clean_tracked_tree(product)
    head = _git_head(product)
    output.mkdir(parents=True, exist_ok=True)
    source_receipt: dict[str, Any] = {
        "schema_version": 1,
        "accepted_successor_commit": ACCEPTED_SUCCESSOR_COMMIT,
        "result_review_sha256": RESULT_REVIEW_SHA256,
        "payload_definition": "sorted relative_path<TAB>bytes<TAB>sha256<LF>",
        "tours": {},
    }
    all_paths = {}
    for tour in SOURCE_SPECS:
        all_paths[tour] = _source_paths(source, tour)
        source_receipt["tours"][tour] = {
            category: {
                "files": values[0],
                "bytes": values[1],
                "sha256": values[2],
            }
            for category, values in SOURCE_SPECS[tour]["inventory"].items()
        }
    source_receipt["exact_copied_payload"] = {"files": 294, "bytes": 545_755_653}

    model_records = []
    audits = []
    inference_checks = []
    decision_records = []
    for tour, paths in all_paths.items():
        fit_index = {(int(path.parts[-3]), path.parts[-2]): path for path in paths["fit_manifests"]}
        for model_path in paths["models"]:
            raw_year = int(model_path.parts[-3])
            member_id = model_path.parts[-2]
            record, audit, inference = _model_record(
                model_path,
                fit_index[(raw_year, member_id)],
                output,
                tour=tour,
                raw_year=raw_year,
                member_id=member_id,
            )
            model_records.append(record)
            audits.append(audit)
            inference_checks.append(inference)
        for decision_path in paths["decisions"]:
            decision_records.append(
                _decision_record(
                    decision_path, output, tour=tour, target_year=int(decision_path.stem)
                )
            )

    type_counts = Counter(item["estimator_type"] for item in model_records)
    _write_json(output / "SOURCE_INVENTORY.json", source_receipt)
    _write_json(
        output / "OBJECT_AUDIT.json",
        {
            "status": "PASS",
            "scope": "all 140 trusted fitted objects, recursively inspected after fixed-source hash verification",
            "model_count": len(audits),
            "estimator_types": dict(sorted(type_counts.items())),
            "private_or_absolute_path_strings": 0,
            "raw_training_matrices": 0,
            "raw_rows_labels_odds_or_winner_payloads": 0,
            "note": "RF objects retain only a uniform 0.5 augmentation-weight vector aligned to the symmetrized fit; it contains no row values, keys, or labels and is preserved for byte parity.",
            "models": audits,
        },
    )
    _write_json(
        output / "INFERENCE_CHECK.json",
        {
            "status": "PASS",
            "scope": "all 140 models on artificial asymmetric and reflected prepared rows; no source row, label, score, or historical forecast used",
            "model_count": len(inference_checks),
            "all_asymmetric": all(
                item["first_probability_a"] != item["reflected_probability_a"]
                for item in inference_checks
            ),
            "maximum_complement_residual": max(
                item["complement_residual"] for item in inference_checks
            ),
            "checks": inference_checks,
        },
    )
    _write_json(output / "REQUIRED_STATE.json", _required_state())
    _write_json(output / "RUNTIME.json", _runtime_document(product))
    _write_text(output / "README.md", _bundle_readme())
    _write_text(output / "LICENSE-NOTICE.md", _license_notice())
    _privacy_scan(output)

    manifest = {
        "schema_version": 1,
        "release_id": RELEASE_ID,
        "snapshot_date": "2026-09-15",
        "status": "research; retrospective outcome-exposed; experimental; no nomination; not a default; not prospective evidence",
        "product_source_commit": head,
        "accepted_campaign_successor_commit": ACCEPTED_SUCCESSOR_COMMIT,
        "independent_result_review_sha256": RESULT_REVIEW_SHA256,
        "models": [],
        "campaign_models": sorted(
            model_records, key=lambda item: (item["tour"], item["raw_year"], item["member_id"])
        ),
        "campaign_decisions": sorted(
            decision_records, key=lambda item: (item["tour"], item["target_year"])
        ),
        "source_payload": {
            "files": 294,
            "bytes": 545_755_653,
            "models": 140,
            "fit_manifests": 140,
            "decisions": 14,
            "receipt_path": "SOURCE_INVENTORY.json",
        },
        "inference_boundary": {
            "numerical_member": "complete only for an already-constructed row matching the fit manifest's ordered feature schema",
            "S2": "complete from the target-fold decision and its selected raw RF probability",
            "S3": "complete from the target-fold decision and all eight ordered raw-member probabilities",
            "current_player_name_application": "not included; see REQUIRED_STATE.json",
        },
        "default_policy": "The separate accepted incumbent release remains the default; this bundle performs no promotion.",
        "license_boundary": {
            "loader_code": "MIT",
            "learned_artifacts": "CC BY-NC-SA 4.0 conservative package treatment",
            "source_databases": "retain their own terms and are not redistributed",
        },
        "excluded": [
            "source rows and workbooks",
            "feature rows and matrices",
            "outcome labels",
            "training memberships",
            "raw and combined forecast rows",
            "odds and market rows",
            "private paths, authorizations, and custody documents",
        ],
    }
    manifest["files"] = _file_inventory(output)
    _write_json(output / "MANIFEST.json", manifest)
    verification = verify_release(output)
    result = {
        "release_id": RELEASE_ID,
        "directory": str(output),
        "manifest_sha256": sha256_file(output / "MANIFEST.json"),
        "verification": verification,
    }
    if tar_path is not None:
        _deterministic_tar(output, tar_path)
        repeat = tar_path.with_name(f".{tar_path.name}.determinism-check")
        _deterministic_tar(output, repeat)
        if tar_path.stat().st_size != repeat.stat().st_size or sha256_file(tar_path) != sha256_file(
            repeat
        ):
            raise BuildError("deterministic tar rebuild differs")
        repeat.unlink()
        result["tar"] = {
            "path": str(tar_path),
            "bytes": tar_path.stat().st_size,
            "sha256": sha256_file(tar_path),
            "deterministic_rebuild_equal": True,
        }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        help="root of the accepted D93/D94 consumer workspace (build only)",
    )
    parser.add_argument("--output", type=Path, help="new companion bundle directory")
    parser.add_argument("--tar", type=Path, help="optional deterministic .tar.gz output")
    parser.add_argument("--verify", type=Path, help="verify an unpacked companion bundle")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verify is not None:
        if args.source is not None or args.output is not None or args.tar is not None:
            raise SystemExit("--verify cannot be combined with build arguments")
        print(json.dumps(verify_release(args.verify.resolve()), indent=2, sort_keys=True))
        return 0
    if args.source is None or args.output is None:
        raise SystemExit("build requires --source and --output")
    product = Path(__file__).resolve().parents[1]
    result = build(product, args.source.resolve(), args.output.resolve(), args.tar)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
