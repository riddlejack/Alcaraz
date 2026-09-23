"""Reconstruct the native WTA ordered blend with deterministic stubs."""

import json

import numpy as np
import pandas as pd
from tennis_predict.models import (
    SEGMENT_BLEND_SPECS_BY_TOUR,
    TEMPORAL_BLEND_SPECS_BY_TOUR,
    SegmentBlendModel,
    TemporalBlendModel,
    WeightedXGBoostEnsemble,
)


class Identity:
    def transform(self, frame):
        return frame


class Constant:
    def __init__(self, probability):
        self.probability = probability

    def predict_proba(self, frame):
        p = np.full(len(frame), self.probability, dtype=float)
        return np.column_stack((1 - p, p))


frame = pd.DataFrame({"surface": ["Hard"], "tourney_level": ["I"]})

global_model = WeightedXGBoostEnsemble.__new__(WeightedXGBoostEnsemble)
global_model.preprocessor_ = Identity()
global_model.estimators_ = [Constant(0.4), Constant(0.6)]
global_model.weights_ = np.array([0.65, 0.35])
global_probability = float(global_model.predict_proba(frame)[0, 1])
assert np.isclose(global_probability, 0.65 * 0.4 + 0.35 * 0.6)

segment = SegmentBlendModel("wta", SEGMENT_BLEND_SPECS_BY_TOUR["wta"])
segment.global_model_ = global_model
segment.segment_models_ = [
    (SEGMENT_BLEND_SPECS_BY_TOUR["wta"][0], Constant(0.7)),
    (SEGMENT_BLEND_SPECS_BY_TOUR["wta"][1], Constant(0.2)),
]
full_probability = float(segment.predict_proba(frame)[0, 1])
after_hard = 0.1 * global_probability + 0.9 * 0.7
expected_full = 0.1 * after_hard + 0.9 * 0.2
assert np.isclose(full_probability, expected_full)

recent = WeightedXGBoostEnsemble.__new__(WeightedXGBoostEnsemble)
recent.preprocessor_ = Identity()
recent.estimators_ = [Constant(0.8), Constant(0.2)]
recent.weights_ = np.array([0.65, 0.35])
recent_probability = float(recent.predict_proba(frame)[0, 1])

temporal_spec = TEMPORAL_BLEND_SPECS_BY_TOUR["wta"]
temporal = TemporalBlendModel(
    "wta", pd.Index([]), temporal_spec.recent_weight, temporal_spec.min_recent_rows
)
temporal.full_model_ = segment
temporal.recent_model_ = recent
final_probability = float(temporal.predict_proba(frame)[0, 1])
expected_final = (
    1 - temporal_spec.recent_weight
) * expected_full + temporal_spec.recent_weight * recent_probability
assert np.isclose(final_probability, expected_final)

print(
    json.dumps(
        {
            "status": "PASS",
            "tour": "wta",
            "ordered_formula": "temporal(full(I(Hard(global weighted ensemble))), recent weighted ensemble)",
            "global_probability": global_probability,
            "after_hard_probability": after_hard,
            "after_I_probability": full_probability,
            "recent_probability": recent_probability,
            "final_probability": final_probability,
            "expected_final_probability": expected_final,
            "weights": {
                "global_ensemble": [0.65, 0.35],
                "Hard_global_weight": 0.1,
                "I_global_weight": 0.1,
                "recent_weight": temporal_spec.recent_weight,
            },
        },
        indent=2,
    )
)
