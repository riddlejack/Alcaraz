"""One native annual campaign fit from controller-bound inputs.

No model deserialization, target outcomes, calibration fitting, or scoring.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import math
import re
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from tennis_predict.models import (
    TEMPORAL_BLEND_SPECS_BY_TOUR,
    augment_derived_features,
    build_model,
    feature_columns,
)

warnings.filterwarnings("ignore", message="Skipping features without any observed values")
start = time.monotonic()
root = Path("/inputs")
config = json.loads((root / "fit_config.json").read_text())
tour = str(config["tour"]).lower()
if tour not in {"atp", "wta"}:
    raise ValueError("tour must be atp or wta")
for name in ["training_features.csv", "target_features.csv"]:
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != config["inputs"][name]:
        raise ValueError("bound input hash mismatch: " + name)

train = pd.read_csv(root / "training_features.csv")
if len(train) != config["fit_rows"]:
    raise ValueError("membership count mismatch")
if train["match_date"].max()[:10] > config["fit_cutoff"]:
    raise ValueError("training after cutoff")
train = augment_derived_features(train, tour=tour)
columns = feature_columns(train, tour=tour)
x = train[columns]
y = train["label"].astype(int)
if not y.isin([0, 1]).all() or y.nunique() != 2:
    raise ValueError("training labels must contain both binary classes")
temporal_spec = TEMPORAL_BLEND_SPECS_BY_TOUR[tour]
recent = pd.to_datetime(train["match_date"]) >= pd.Timestamp(temporal_spec.recent_start)
if int(recent.sum()) != config["recent_rows"]:
    raise ValueError("recent membership mismatch")
model = build_model(x, tour=tour, random_state=42, recent_indices=train.index[recent])
model.fit(x, y)

target = pd.read_csv(root / "target_features.csv")
if len(target) != config["target_rows"]:
    raise ValueError("target membership count mismatch")
if not target["label"].isna().all():
    raise ValueError("target labels entered fit process")
if set(train["match_id"]) & set(target["match_id"]):
    raise ValueError("train/target overlap")
target = augment_derived_features(target, tour=tour)
if feature_columns(target, tour=tour) != columns:
    raise ValueError("train/target feature schema mismatch")
native = model.predict_proba(target[columns])[:, 1].astype(float)

output = Path("/tmp/benchmark_output")
output.mkdir()
with (output / "native_forecasts.csv").open("w") as handle:
    writer = csv.writer(handle)
    writer.writerow(["match_id", "canonical_a_source_id", "p_a_native", "native_status"])
    for key, player, probability in zip(
        target["match_id"], target["player_a_id"], native, strict=True
    ):
        valid = bool(np.isfinite(probability) and 0 <= probability <= 1)
        writer.writerow(
            [
                key,
                int(player),
                format(probability, ".17g") if valid else "",
                "native" if valid else "nonfinite_or_out_of_range",
            ]
        )


def clean_parameters(estimator) -> dict:
    return {
        key: (
            "NaN_missing_value_sentinel"
            if isinstance(value, float) and math.isnan(value)
            else value
        )
        for key, value in estimator.get_params().items()
    }


def safe_member_stem(prefix: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}", prefix):
        return prefix
    simplified = re.sub(r"[^A-Za-z0-9_.-]+", "_", prefix).strip("._-")[:48] or "member"
    suffix = hashlib.sha256(prefix.encode()).hexdigest()[:12]
    return f"{simplified}_{suffix}"


menu: list[dict] = []
used_artifact_names: set[str] = set()


def retain_fitted_model(
    prefix: str, fitted, rows: int, role: str, metadata: dict | None = None
) -> list[str]:
    """Save every native XGBoost estimator behind a pipeline or weighted ensemble."""
    stem = safe_member_stem(prefix)
    if hasattr(fitted, "named_steps"):
        estimators = [(None, fitted.named_steps["model"])]
    elif hasattr(fitted, "estimators_") and hasattr(fitted, "weights_"):
        estimators = list(
            zip([float(value) for value in fitted.weights_], fitted.estimators_, strict=True)
        )
    else:
        raise TypeError(f"unsupported fitted native member: {type(fitted).__name__}")
    names = []
    for index, (ensemble_weight, estimator) in enumerate(estimators):
        member = stem if len(estimators) == 1 else f"{stem}_component_{index + 1:02d}"
        filename = member + ".json"
        if filename in used_artifact_names:
            raise ValueError("native artifact filename collision: " + filename)
        used_artifact_names.add(filename)
        estimator.save_model(output / filename)
        entry = {
            "member": member,
            "artifact": filename,
            "role": role,
            "rows": int(rows),
            "trees": estimator.get_booster().num_boosted_rounds(),
            "parameters": clean_parameters(estimator),
        }
        if ensemble_weight is not None:
            entry["ensemble_weight"] = ensemble_weight
        if metadata:
            entry.update(metadata)
        menu.append(entry)
        names.append(filename)
    return names


full_model = model.full_model_
activation = {
    "tour": tour,
    "temporal": {
        "recent_start": temporal_spec.recent_start,
        "recent_weight": temporal_spec.recent_weight,
        "min_recent_rows": temporal_spec.min_recent_rows,
        "recent_rows": int(recent.sum()),
        "active": model.recent_model_ is not None,
    },
    "segments": [],
}
if hasattr(full_model, "global_model_") and hasattr(full_model, "segment_models_"):
    retain_fitted_model("global", full_model.global_model_, len(train), "full_global")
    for spec, specialist in full_model.segment_models_:
        segment_rows = int((x[spec.column] == spec.value).sum())
        segment_stem = safe_member_stem("segment_" + str(spec.value))
        retain_fitted_model(
            segment_stem,
            specialist,
            segment_rows,
            "segment_specialist",
            {
                "segment_column": spec.column,
                "segment_value": spec.value,
                "global_weight": spec.global_weight,
            },
        )
        activation["segments"].append(
            {
                "column": spec.column,
                "value": spec.value,
                "global_weight": spec.global_weight,
                "rows": segment_rows,
                "active": True,
            }
        )
else:
    retain_fitted_model("global", full_model, len(train), "full_global")

if model.recent_model_ is not None:
    retain_fitted_model("recent_global", model.recent_model_, int(recent.sum()), "recent_global")

artifacts_without_receipt = sorted(output.iterdir())
receipt = {
    "tour": tour,
    "fit_cutoff": config["fit_cutoff"],
    "fit_rows": len(train),
    "target_rows": len(target),
    "native_rows": int(np.sum(np.isfinite(native) & (native >= 0) & (native <= 1))),
    "feature_columns": columns,
    "fit_menu": menu,
    "activation": activation,
    "wall_seconds": time.monotonic() - start,
    "artifact_inventory": [path.name for path in artifacts_without_receipt],
    "artifact_sha256": {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in artifacts_without_receipt
    },
}
(output / "fit_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
artifacts = sorted(output.iterdir())
raw_artifact_bytes = sum(path.stat().st_size for path in artifacts)
if raw_artifact_bytes > int(config["fit_artifact_bytes"]):
    raise RuntimeError("fit artifact raw-byte ceiling exceeded")
print(
    json.dumps(
        {
            "status": "forecast_complete_no_scores",
            "tour": tour,
            "fit_rows": len(train),
            "target_rows": len(target),
            "native_rows": receipt["native_rows"],
            "fit_members": len(menu),
            "raw_artifact_bytes": raw_artifact_bytes,
            "artifact_inventory": [path.name for path in artifacts],
            "artifacts_base64": {
                path.name: base64.b64encode(path.read_bytes()).decode("ascii") for path in artifacts
            },
        }
    )
)
