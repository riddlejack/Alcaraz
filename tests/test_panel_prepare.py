"""The archive's ``MULTI01_prepare/test_prepare_panel.py``, importing from the package.

Every case is the archive's, unchanged; the only difference is that the failure type is
now ``ChainError``, which subclasses ``ValueError``, so the assertions are unaltered.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from tennislab.panel.prepare import correct_counts, qualify


def fixture() -> tuple[dict[str, str], dict[str, Any]]:
    raw = {}
    for side in ("w", "l"):
        raw.update(
            {
                f"{side}_{k}": str(v)
                for k, v in dict(
                    ace=3,
                    df=4,
                    svpt=60,
                    **{"1stIn": 40, "1stWon": 28, "2ndWon": 15},
                    SvGms=10,
                    bpSaved=2,
                    bpFaced=3,
                ).items()
            }
        )
    raw["w_1stIn"] = "45"
    row = {
        "source_key": "fixture/1",
        "raw_row_json": json.dumps(raw),
        "a_source_side": "l",
        "b_source_side": "w",
    }
    case = {
        "official_url": "fixture",
        "assert_before_replacements": [{"field": "w_1stIn", "assert": 45, "replace": 40}],
    }
    return row, case


def test_guarded_correction_preserves_raw_and_neutral_side() -> None:
    row, case = fixture()
    original = copy.deepcopy(row)
    out = correct_counts(row, case)
    assert row == original
    assert out["b_1stIn"] == "40"
    assert out["raw_row_json"] == original["raw_row_json"]


def test_changed_source_cannot_receive_old_correction() -> None:
    row, case = fixture()
    case["assert_before_replacements"][0]["assert"] = 44
    with pytest.raises(ValueError):
        correct_counts(row, case)


def test_joint_second_serve_bound_catches_individually_valid_counts() -> None:
    row, case = fixture()
    case["assert_before_replacements"][0]["replace"] = 43
    with pytest.raises(ValueError):
        correct_counts(row, case)


def test_identity_tier_cannot_depend_on_winner_or_score_agreement() -> None:
    row = {
        "classification": "candidate_q4_unique_pair_round_date_event_unmapped",
        "archive_tourney_id": "2005-1",
    }
    event = {
        "archive_tourney_id": "2005-1",
        "final_recommendation": "provisional_recurrence_supported",
    }
    before = qualify(row, event)
    row.update(winner_agreement="disagree", score_agreement="disagree")
    assert qualify(row, event) == before
    assert before[0] == "provisional"
    assert qualify(row, {"archive_tourney_id": "2006-1"})[0] == "excluded"
