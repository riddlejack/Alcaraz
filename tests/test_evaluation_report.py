"""The reporter's contrast menu, the published primary, and the fail-closed bindings.

Ported from the report cases of the archive's ``test_tier01.py``; the bootstrap fixture
is the archive's own. The B5 case is new: a manifest whose run-tree digest is the hash
of ``{}`` is refused before anything is scored.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from tennislab.chain.common import ChainError, canonical_hash, sha256
from tennislab.config import reset_workspace_cache
from tennislab.evaluation import report, scores

YEARS = (2023, 2024)
PLAN = {
    "panel_end_year": 2024,
    "feature_end_year": 2024,
    "target_years": list(YEARS),
    "calibration_years_back": 3,
    "history_floor_year": 2011,
    "training_window_years": 5,
}
T1 = 12.7062047361747


@pytest.fixture(autouse=True)
def _restore_module_state() -> Iterator[None]:
    yield
    report.configure_identity()
    report.configure_years(report.DEFAULT_YEAR_PLAN, report.DEFAULT_T_CRITICAL_95)
    report.configure_bundles()
    report.configure_cohort()


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    yield tmp_path
    reset_workspace_cache()


def bootstrap_fixture(years, contrasts):
    """A `details` mapping and a `labels` mapping shaped like `contrast_outputs`' own."""
    details = {}
    labels = {}
    for year in years:
        keys = [(str(year), f"E{index // 4}/{index}") for index in range(48)]
        for index, key in enumerate(keys):
            labels[key] = {"tourney_id": f"{year}-E{index // 4}"}
        for name, scale in contrasts.items():
            deltas = np.asarray(
                [scale * (1.0 + 0.01 * index) for index in range(len(keys))], dtype=np.float64
            )
            details[("selected", "hgb", "primary", name, year)] = {
                "keys": keys,
                "loss_delta": deltas,
                "brier_delta": deltas,
            }
    return details, labels


def _tier_setup() -> None:
    report.configure_years(PLAN, T1)
    report.configure_bundles(["base", "full", "base_tier", "full_tier"], ["hgb"])


# ------------------------------------------------------------------ the contrast menu


def test_report_forms_both_ablation_contrasts() -> None:
    report.configure_bundles(
        ["base", "full", "base_tier", "full_tier", "full_tier_noqual"], ["hgb"]
    )
    names = [name for name, _ in report.CONTRASTS]
    assert "full_tier_noqual_minus_full" in names
    assert "full_tier_minus_full_tier_noqual" in names
    assert report.primary_contrast_id() == "full_tier_minus_full"
    assert sorted(report.secondary_contrast_ids()) == [
        "base_tier_minus_base",
        "full_tier_minus_full_tier_noqual",
        "full_tier_noqual_minus_full",
    ]


def test_report_forms_the_arms01_entry_contrast_and_names_its_direction() -> None:
    # ARMS01 Arm 1 minus Arm 0: the entry bundle against the tier bundle it extends.
    report.configure_years(PLAN, T1)
    report.configure_bundles(["base", "full_tier", "full_tier_entry"], ["hgb"])
    names = [name for name, _ in report.CONTRASTS]
    assert names == ["full_tier_entry_minus_full_tier"]
    assert report.primary_contrast_id() == "full_tier_entry_minus_full_tier"
    assert report.secondary_contrast_ids() == ()
    coefficients = dict(report.CONTRASTS)["full_tier_entry_minus_full_tier"]
    assert coefficients == {"full_tier_entry": 1.0, "full_tier": -1.0}
    # With the JOINT04 stem fitted too, the entry bundle also contrasts against it, and
    # the configured primary wins over the implied one.
    report.configure_bundles(
        ["base", "full", "base_tier", "full_tier", "full_tier_noqual", "full_tier_entry"], ["hgb"]
    )
    names = [name for name, _ in report.CONTRASTS]
    assert "full_tier_entry_minus_full" in names and "full_tier_minus_full" in names
    report.configure_primary("full_tier_minus_full", None, None)
    assert report.primary_contrast_id() == "full_tier_minus_full"
    # A bundle name with a suffix the reporter does not know is still refused.
    with pytest.raises(ChainError):
        report.configure_bundles(["base", "full_tier_extra"], ["hgb"])
    # The tour contract cannot record an entry bundle.
    report.configure_identity("WTA02", "WTA")
    with pytest.raises(ChainError):
        report.configure_bundles(["base", "full", "full_tier_entry"], ["hgb"])


def test_report_forms_the_wta_entry_contrast_under_the_tour_contract() -> None:
    # ARMS01 WTA secondary: `full_entry` (no tier block) against `full`.
    report.configure_identity("ARMS01-WTA", "WTA")
    report.configure_years(PLAN, T1)
    report.configure_bundles(["base", "full", "full_entry"], ["hgb"])
    names = [name for name, _ in report.CONTRASTS]
    assert "full_entry_minus_full" in names and "full_minus_base" in names
    assert report.primary_contrast_id() == "full_entry_minus_full"
    assert dict(report.CONTRASTS)["full_entry_minus_full"] == {"full_entry": 1.0, "full": -1.0}
    # Tier variants stay refused under the tour contract.
    for tiered in ("full_tier", "full_tier_entry", "full_tier_noqual"):
        with pytest.raises(ChainError):
            report.configure_bundles(["base", "full", tiered], ["hgb"])


def test_report_makes_the_tier_contrast_primary_and_reverts_with_the_defaults() -> None:
    report.configure_bundles(["base", "full", "base_tier", "full_tier"], ["hgb"])
    names = [name for name, _ in report.CONTRASTS]
    assert "full_tier_minus_full" in names and "base_tier_minus_base" in names
    assert report.primary_contrast_id() == "full_tier_minus_full"
    report.configure_bundles()
    assert report.primary_contrast_id() == "full_minus_base"


def test_the_bundle_list_implies_the_tier_primary_and_its_seed() -> None:
    _tier_setup()
    assert report.primary_contrast_id() == "full_tier_minus_full"
    assert report.secondary_contrast_ids() == ("base_tier_minus_base",)
    assert report.BOOTSTRAP_SEED == 20260912
    settings = report.settings_document()
    assert settings["primary_contrast"] == "full_tier_minus_full"
    assert settings["secondary_contrasts"] == ["base_tier_minus_base"]
    assert settings["bootstrap_seed"] == 20260912
    assert "bootstrap_unit" not in settings and "tour" not in settings


def test_atp_mode_keeps_full_minus_base_and_seed_20260911() -> None:
    report.configure_years(PLAN, T1)
    report.configure_bundles(["base", "traits", "dynamic", "full"], ["ridge", "hgb"])
    assert report.primary_contrast_id() == "full_minus_base"
    assert report.secondary_contrast_ids() == ()
    assert report.BOOTSTRAP_SEED == 20260911


def test_a_primary_the_bundles_cannot_form_is_refused() -> None:
    _tier_setup()
    with pytest.raises(ChainError):
        report.configure_primary("traits_minus_base", None, None)
    with pytest.raises(ChainError):
        report.configure_primary("full_tier_minus_full", ["full_tier_minus_full"], None)
    with pytest.raises(ChainError):
        report.configure_primary("full_tier_minus_full", [], -1)
    with pytest.raises(ChainError):
        report.configure_primary("full_tier_minus_full", [], None, "match")


# ------------------------------------------------------------------ the published primary


def test_the_artifact_records_the_configured_contrast_and_seed() -> None:
    """SCAR_TISSUE B6: what primary.json and bootstrap.csv publish is the config's, not a literal."""
    _tier_setup()
    config_settings = {"primary_contrast": "base_tier_minus_base", "bootstrap_seed": 4242}
    report.configure_primary(
        config_settings["primary_contrast"], [], config_settings["bootstrap_seed"]
    )
    details, labels = bootstrap_fixture(
        YEARS, {"full_tier_minus_full": -0.01, "base_tier_minus_base": -0.05}
    )
    rows, summary, secondary = report.bootstrap_primary(details, labels)
    frozen = report.settings_document()
    assert frozen["primary_contrast"] == config_settings["primary_contrast"]
    assert frozen["bootstrap_seed"] == config_settings["bootstrap_seed"]
    assert summary["contrast_id"] == frozen["primary_contrast"]
    assert summary["seed"] == frozen["bootstrap_seed"]
    assert {row["contrast_id"] for row in rows} == {frozen["primary_contrast"]}
    assert {row["seed"] for row in rows} == {frozen["bootstrap_seed"]}
    assert secondary == {}


def test_a_config_naming_a_different_pair_changes_the_published_primary() -> None:
    _tier_setup()
    details, labels = bootstrap_fixture(
        YEARS, {"full_tier_minus_full": -0.01, "base_tier_minus_base": -0.05}
    )
    report.configure_primary("full_tier_minus_full", [], None)
    first_rows, first, _ = report.bootstrap_primary(details, labels)
    report.configure_primary("base_tier_minus_base", [], None)
    second_rows, second, _ = report.bootstrap_primary(details, labels)
    assert first["contrast_id"] == "full_tier_minus_full"
    assert second["contrast_id"] == "base_tier_minus_base"
    assert not np.isclose(first["lower_95"], second["lower_95"], atol=1e-6)
    assert second["upper_95"] < first["upper_95"]
    assert {row["contrast_id"] for row in first_rows} == {"full_tier_minus_full"}
    assert {row["contrast_id"] for row in second_rows} == {"base_tier_minus_base"}


def test_the_seed_is_configuration_and_changes_the_draw() -> None:
    _tier_setup()
    details, labels = bootstrap_fixture(YEARS, {"full_tier_minus_full": -0.01})
    report.configure_primary("full_tier_minus_full", [], 20260912)
    _, first, _ = report.bootstrap_primary(details, labels)
    report.configure_primary("full_tier_minus_full", [], 20260911)
    _, second, _ = report.bootstrap_primary(details, labels)
    assert first["seed"] == 20260912 and second["seed"] == 20260911
    assert first["lower_95"] != second["lower_95"]
    report.configure_primary("full_tier_minus_full", [], 20260912)
    _, again, _ = report.bootstrap_primary(details, labels)
    assert first == again


def test_the_tour_contract_publishes_the_configured_unit_and_both_are_emitted() -> None:
    report.configure_identity("WTA02", "WTA")
    report.configure_years(PLAN, T1)
    report.configure_bundles(["base", "traits", "dynamic", "full"], ["ridge", "hgb"])
    report.configure_primary("full_minus_base", None, 20260912, "match")
    settings = report.settings_document()
    assert settings["bootstrap_unit"] == "match"
    assert settings["bootstrap_units_emitted"] == ["match", "tournament_edition"]
    assert settings["tour"] == "WTA" and settings["cohort"] == "aligned_primary"
    assert "secondary_contrasts" not in settings
    details, labels = bootstrap_fixture(YEARS, {"full_minus_base": -0.007})
    rows, published, secondary = report.bootstrap_primary(details, labels)
    assert published["unit"] == "match"
    assert list(secondary) == ["tournament_edition"]
    assert [row["unit"] for row in rows] == ["match"] * 2 + ["tournament_edition"] * 2
    assert rows[0]["resampling_blocks"] == 48 and rows[2]["resampling_blocks"] == 12
    # The edition-blocked draw is the same one the tier contract publishes: one
    # generator per unit, seeded identically.
    report.configure_identity(None, None)
    report.configure_bundles(["base", "traits", "dynamic", "full"], ["ridge", "hgb"])
    report.configure_primary("full_minus_base", [], 20260912)
    tier_rows, tier_summary, _ = report.bootstrap_primary(details, labels)
    assert (tier_summary["lower_95"], tier_summary["upper_95"]) == (
        secondary["tournament_edition"]["lower_95"],
        secondary["tournament_edition"]["upper_95"],
    )
    assert [r["bootstrap_lower_95"] for r in tier_rows] == [
        r["bootstrap_lower_95"] for r in rows[2:]
    ]
    with pytest.raises(ChainError):
        report.configure_identity("WTA02", "WTA")
        report.configure_bundles(["base", "full", "full_tier"], ["hgb"])


# ------------------------------------------------------------------ pure scores


def test_scores_are_the_reporters_arithmetic() -> None:
    losses, brier, clipped = scores.individual_scores([0.0, 0.5, 1.0], [1, 1, 0], 1e-15)
    assert clipped == 2
    assert np.isclose(losses[1], np.log(2.0))
    assert brier.tolist() == [1.0, 0.25, 1.0]
    delta = scores.contrast_delta(
        {"a": np.asarray([1.0, 2.0]), "b": np.asarray([0.5, 0.5])}, {"a": 1.0, "b": -1.0}
    )
    assert delta.tolist() == [0.5, 1.5]
    bins = scores.reliability_bins([(0.05, 0), (1.0, 1)], report.RELIABILITY_EDGES)
    assert bins[0]["n"] == 1 and bins[9]["n"] == 1 and bins[5]["mean_prediction"] == ""
    with pytest.raises(ChainError):
        scores.individual_scores([], [], 1e-15)
    with pytest.raises(ChainError):
        scores.t_half_width([0.1], 2.0)


# ------------------------------------------------------------------ fail-closed bindings


def _reporting_config(tmp_path: Path, selection_digest: str | None = None) -> Path:
    selection = tmp_path / "selection_complete.json"
    selection.write_text("{}\n")
    _tier_setup()
    report.configure_identity("TIER01", None)
    document = {
        "experiment_id": "TIER01",
        "execution_scope": "frozen_real_outputs",
        "status": "frozen",
        "settings": report.settings_document(),
        "code": {
            "reporter_path": "tennislab.evaluation.report",
            "reporter_sha256": sha256(report.__file__),
        },
        "expected_membership": {"selected_primary_rows": 10, "selected_primary_priced_rows": 9},
        "inputs": {
            "selection_complete": {
                "path": "selection_complete.json",
                "sha256": selection_digest or sha256(selection),
            }
        },
    }
    path = tmp_path / "reporting.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return path


def test_b5_a_manifest_digest_of_the_empty_object_is_refused(workspace: Path) -> None:
    path = _reporting_config(workspace, canonical_hash({}))
    with pytest.raises(ChainError, match="empty content"):
        report.validate_config(path)


def test_a_reporter_binding_naming_this_module_must_match_it(workspace: Path) -> None:
    path = _reporting_config(workspace)
    document = json.loads(path.read_text())
    document["code"]["reporter_sha256"] = "1" * 64
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    with pytest.raises(ChainError, match="reporter code hash"):
        report.validate_config(path)


def test_the_config_not_a_literal_sets_the_contrast_and_seed(workspace: Path) -> None:
    path = _reporting_config(workspace)
    document = json.loads(path.read_text())
    document["settings"]["bootstrap_seed"] = 1
    document["settings"]["primary_contrast"] = "base_tier_minus_base"
    document["settings"]["secondary_contrasts"] = []
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    config, selection_path, declared = report.validate_config(path)
    assert report.BOOTSTRAP_SEED == 1
    assert report.primary_contrast_id() == "base_tier_minus_base"
    assert report.settings_document() == document["settings"]
    assert selection_path == workspace / "selection_complete.json"
    assert declared["reporter_path"] == "tennislab.evaluation.report"


def test_settings_that_drift_from_the_contract_are_refused(workspace: Path) -> None:
    path = _reporting_config(workspace)
    document = json.loads(path.read_text())
    document["settings"]["raw_years"] = [2000]
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    with pytest.raises(ChainError, match="settings differ"):
        report.validate_config(path)
