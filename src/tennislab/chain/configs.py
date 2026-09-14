"""Bind the frozen predictor and reporting configurations: stages ``predictor_config``
and ``reporting_config``. Does not fit or score.

Base revision: the archive's ``references/TIER01_models/build_config.py`` (the optional
``bundles``/``learners`` siblings of the year plan; the primary contrast, secondary
contrasts and bootstrap seed as ``reporting`` arguments). Merged from
``references/WTA02_models/build_config.py`` under the tour switch: the optional
``cohort``, ``primary_contrast``, ``bootstrap_seed``, ``bootstrap_unit``, ``tour`` and
``experiment_id`` siblings, carried into the predictor config as ``reporting_settings``
so the reporting stage installs them without re-reading the plan, and the
dynamic-feature dispersion receipts.

The runner and the reporter are the package modules ``tennislab.models.pipeline`` and
``tennislab.evaluation.report``; their code receipts are written where the archive wrote
a repository-relative path and file hash. No label is read: memberships come from the
feature/sidecar metadata only, and the reporting configuration's declared counts are
the runner's own primary and primary-priced counts over the configured target years,
which the reporter re-derives and re-checks before it scores anything.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from tennislab.chain.common import (
    ChainError,
    code_receipt,
    read_config,
    relative_to_root,
    require_nonempty_digest,
    resolve_under_root,
    sha256,
)
from tennislab.evaluation import report as reporter
from tennislab.models import pipeline as runner

# Optional siblings of the year_plan object; absent, the runner's own defaults stand.
# `bundles` is TIER01's spelling of `blocks`.
PLAN_SETTING_KEYS = (
    "blocks",
    "bundles",
    "learners",
    "cohort",
    "primary_contrast",
    "bootstrap_seed",
    "bootstrap_unit",
    "tour",
    "experiment_id",
)
REPORTING_SETTING_KEYS = ("primary_contrast", "bootstrap_seed", "bootstrap_unit")


class ConfigError(ChainError):
    """A binding the configuration cannot be frozen under."""


def binding(path: Path) -> dict[str, str]:
    return {
        "path": relative_to_root(path),
        "sha256": require_nonempty_digest(sha256(path), label=f"binding {path.name}"),
    }


def label_binding(labels_path: Path, features_path: Path) -> dict[str, str]:
    """The label file's binding, taken from the features stage's own manifest.

    The predictor config binds ``labels.csv`` by hash but must not open it (RB3: before
    the report, the label file is read only as history through ``LabelHistory``). The
    features stage that wrote the file recorded its hash beside the feature file's, so
    the binding is copied from that manifest after checking the manifest binds the
    feature file this config binds.
    """
    if labels_path.parent != features_path.parent or labels_path.name != "labels.csv":
        raise ConfigError(
            "labels must be the features stage's own labels.csv beside the feature file; "
            f"got {labels_path}"
        )
    manifest_path = features_path.parent / "manifest.json"
    if not manifest_path.is_file():
        raise ConfigError(f"features manifest not found beside the feature file: {manifest_path}")
    outputs = read_config(manifest_path).get("outputs", {})
    recorded_features = outputs.get("features.csv", {}).get("sha256")
    if recorded_features != sha256(features_path):
        raise ConfigError("features manifest does not bind the configured feature file")
    return {
        "path": relative_to_root(labels_path),
        "sha256": require_nonempty_digest(
            outputs.get("labels.csv", {}).get("sha256"), label="binding labels.csv"
        ),
    }


def read_year_plan(path: Path) -> dict[str, Any]:
    document = read_config(path)
    return document.get("year_plan", document)


def read_plan_settings(path: Path) -> dict[str, Any]:
    """The optional bundle/cohort/primary/identity settings beside the year plan."""
    document = read_config(path)
    settings = {key: document[key] for key in PLAN_SETTING_KEYS if key in document}
    if "blocks" in settings and "bundles" in settings:
        raise ConfigError("year plan declares both blocks and bundles")
    if "bundles" in settings:
        settings["blocks"] = settings.pop("bundles")
    return settings


def t_critical_95(degrees_of_freedom: int) -> float | None:
    """Two-sided 95% Student-t critical value, or None when there is no spread."""
    if degrees_of_freedom < 1:
        return None
    from scipy import stats

    return float(stats.t.ppf(0.975, degrees_of_freedom))


def build_predictor(
    year_plan_path: Path,
    inputs: dict[str, Path],
    design_path: Path,
    *,
    decision: str,
    execution_scope: str,
    proposal_status: str,
    provenance: list[Path],
    claim_limits: list[str],
) -> dict[str, Any]:
    plan = runner.configure_years(read_year_plan(year_plan_path))
    settings = read_plan_settings(year_plan_path)
    runner.configure_identity(settings.get("experiment_id"), settings.get("tour"))
    # Bundles first: the cohort check reads the installed blocks, and a two-block
    # no-dynamic plan must not be judged against the default four.
    runner.configure_bundles(settings.get("blocks"), settings.get("learners"))
    runner.configure_cohort(settings.get("cohort"))
    info = runner.runtime_description()

    dictionary = json.loads(inputs["dictionary"].read_text(encoding="utf-8"))
    contract = runner.FeatureContract.from_dictionary(dictionary)

    bundle = runner.assemble_feature_bundle(
        inputs["features"], inputs["dictionary"], inputs["sidecar"]
    )
    primary_by_year = {
        str(year): len(runner.target_keys(bundle.metadata, year)) for year in runner.RAW_YEARS
    }
    provisional_by_year = {
        str(year): len(runner.provisional_target_keys(bundle.metadata, year))
        for year in runner.RAW_YEARS
    }
    warmup = sum(
        key[0] == str(plan.history_floor_year) and runner.is_aligned_primary(row)
        for key, row in bundle.metadata.items()
    )
    expected_membership = {
        "raw_primary_by_year": primary_by_year,
        "provisional_by_year": provisional_by_year,
        "raw_primary_rows": sum(primary_by_year.values()),
        "selected_primary_rows": sum(primary_by_year[str(year)] for year in runner.OUTER_YEARS),
        "aligned_primary_warmup_rows": warmup,
        "raw_fit_attempts": sum(
            len(runner.candidate_ids(learner)) * len(runner.BLOCKS) * len(runner.RAW_YEARS)
            for learner in runner.LEARNERS
        ),
    }

    def receipt(keys: Any) -> dict[str, Any]:
        return {"rows": len(keys), "membership_sha256": runner.NUM.key_hash(keys)}

    membership_bindings = {
        "annual": {
            str(year): {
                "training": receipt(runner.training_keys(bundle.metadata, year)),
                "primary_target": receipt(runner.target_keys(bundle.metadata, year)),
                "provisional_target": receipt(
                    runner.provisional_target_keys(bundle.metadata, year)
                ),
                "all_predictions": receipt(runner.all_prediction_keys(bundle.metadata, year)),
            }
            for year in runner.RAW_YEARS
        },
        "selection": {
            str(year): {
                str(past): receipt(keys)
                for past, keys in runner.selection_keys(bundle.metadata, year).items()
            }
            for year in runner.OUTER_YEARS
        },
    }

    document = {
        "experiment_id": info["experiment_id"],
        "decision": decision,
        "execution_scope": execution_scope,
        "proposal_status": proposal_status,
        "created_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "design": binding(design_path),
        "code": info["code"],
        "dependencies": info["dependencies"],
        "settings": info["settings"],
        "inputs": {
            name: (label_binding(path, inputs["features"]) if name == "labels" else binding(path))
            for name, path in inputs.items()
        },
        "label_file_columns": list(runner.LABEL_COLUMNS),
        "ordered_model_columns": runner.ordered_model_columns(contract),
        "expected_membership": expected_membership,
        "membership_bindings": membership_bindings,
        "measurement_provenance": [binding(item) for item in provenance],
        "thread_environment": {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        },
        "reporting_execution": (
            "Run report.py once, after the forecast tree is hashed; it is the only program that "
            "reads target-year labels."
        ),
        "claim_limits": list(claim_limits),
    }
    if runner.tour_contract():
        # A raw year whose dynamic feature is constant is a declared degradation, and the
        # report must be able to show which years those were.  Availability provenance,
        # computed from the sidecar; never a feature and never compared against an
        # expectation.
        document["dynamic_feature_dispersion_by_raw_year"] = runner.dynamic_dispersion_by_raw_year(
            bundle.metadata
        )
        document["dynamic_feature_dispersion_by_training_window"] = (
            runner.training_window_dispersion(bundle.metadata)
        )
        # Carried so the reporting stage can install the same reporting settings without
        # re-reading the year-plan file the predictor was frozen from.
        document["reporting_settings"] = {
            key: settings[key] for key in REPORTING_SETTING_KEYS if key in settings
        }
    return document


def build_reporting(
    predictor_path: Path,
    selection_path: Path,
    *,
    primary_contrast: str | None,
    secondary_contrasts: list[str] | None,
    bootstrap_seed: int | None,
    selected_primary_priced_rows: int | None,
    claim_limits: list[str],
) -> dict[str, Any]:
    predictor = read_config(predictor_path)
    # The reporting config inherits the predictor config's own id and tour rather than
    # being refused by a literal.
    experiment_id = predictor.get("experiment_id")
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise ConfigError("predictor config carries no experiment_id")
    predictor_settings = predictor.get("settings")
    if not isinstance(predictor_settings, dict):
        raise ConfigError("predictor config settings must be an object")
    plan = predictor_settings["year_plan"]
    targets = [int(year) for year in plan["target_years"]]
    reporter.configure_identity(experiment_id, predictor_settings.get("tour"))
    reporter.configure_years(plan, t_critical_95(len(targets) - 1))
    # The reporter must expect exactly the bundles the pipeline produced, and the
    # published contrasts, seed and unit are frozen here rather than left to a literal
    # inside the reporter.  Command-line values override the settings the predictor
    # config carried from the year plan; absent both, the bundle list implies them.
    reporter.configure_bundles(predictor_settings.get("blocks"), predictor_settings.get("learners"))
    reporter.configure_cohort(predictor_settings.get("cohort"))
    reporting_settings = predictor.get("reporting_settings", {})
    if not isinstance(reporting_settings, dict):
        raise ConfigError("predictor reporting_settings must be an object")
    if secondary_contrasts is not None and [item.lower() for item in secondary_contrasts] == [
        "none"
    ]:
        secondary_contrasts = []
    reporter.configure_primary(
        primary_contrast or reporting_settings.get("primary_contrast"),
        secondary_contrasts,
        bootstrap_seed if bootstrap_seed is not None else reporting_settings.get("bootstrap_seed"),
        reporting_settings.get("bootstrap_unit"),
    )

    selection = read_config(selection_path)
    if selection.get("status") != "complete":
        raise ConfigError("selection_complete is not complete")
    if selection.get("outer_target_outcomes_scored") is not False:
        raise ConfigError("selection manifest already reports scored outer outcomes")
    if require_nonempty_digest(
        selection.get("config_sha256"), label="selection_complete config_sha256"
    ) != sha256(predictor_path):
        raise ConfigError("selection_complete was not produced from this predictor config")
    require_nonempty_digest(
        selection.get("raw_complete_sha256"), label="selection_complete raw_complete_sha256"
    )
    membership = selection.get("membership", {})
    declared = {
        "selected_primary_rows": int(membership["selected_primary_rows"]),
        "selected_primary_priced_rows": (
            int(selected_primary_priced_rows) if selected_primary_priced_rows is not None else None
        ),
    }
    if declared["selected_primary_priced_rows"] is None:
        # Priced rows are a market-coverage count, not a model membership; take them
        # from the saved market forecasts rather than a literal.
        priced = 0
        for record in selection["market_records"]:
            priced += int(record["target_rows"])
        declared["selected_primary_priced_rows"] = priced

    design = predictor.get("design")
    if not isinstance(design, dict):
        raise ConfigError("predictor config carries no design binding")
    require_nonempty_digest(design.get("sha256"), label="design")
    receipt = code_receipt(reporter.__name__)
    return {
        "experiment_id": experiment_id,
        "execution_scope": "frozen_real_outputs",
        "status": "frozen",
        "frozen_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "inputs": {
            "selection_complete": binding(selection_path),
            "predictor_config": binding(predictor_path),
            "design": design,
        },
        "code": {
            "reporter_path": receipt["module"],
            "reporter_sha256": receipt["sha256"],
            "package_version": receipt["package_version"],
        },
        "settings": reporter.settings_document(),
        "expected_membership": declared,
        "claim_limits": list(claim_limits),
    }


def write_config(document: dict[str, Any], output: Path) -> tuple[Path, str]:
    output = resolve_under_root(output, label="output")
    if output.exists():
        raise ConfigError(f"refusing to replace an existing config: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output, sha256(output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)

    predictor = subparsers.add_parser("predictor")
    predictor.add_argument("--year-plan", type=Path, required=True)
    predictor.add_argument("--features", type=Path, required=True)
    predictor.add_argument("--dictionary", type=Path, required=True)
    predictor.add_argument("--sidecar", type=Path, required=True)
    predictor.add_argument("--labels", type=Path, required=True)
    predictor.add_argument("--design", type=Path, required=True)
    predictor.add_argument("--decision", default="D40")
    predictor.add_argument("--execution-scope", default="frozen_real_inputs")
    predictor.add_argument("--proposal-status", default="candidate_pending_independent_review")
    predictor.add_argument("--provenance", nargs="*", default=[])
    predictor.add_argument("--claim-limit", action="append", default=[])
    predictor.add_argument("--output", type=Path, required=True)

    reporting = subparsers.add_parser("reporting")
    reporting.add_argument(
        "--primary-contrast",
        default=None,
        help="the contrast primary.json, report.md and bootstrap.csv publish as primary "
        "(default: the predictor config's reporting_settings, else what the bundle list implies)",
    )
    reporting.add_argument(
        "--secondary-contrast",
        action="append",
        default=None,
        help="a further contrast to publish with its own bootstrap interval; repeatable, "
        "or the single value 'none' to publish none",
    )
    reporting.add_argument(
        "--bootstrap-seed",
        type=int,
        default=None,
        help="seed for the fixed-prediction bootstrap (default: the predictor config's "
        "reporting_settings, else 20260911, or 20260912 for a tier primary)",
    )
    reporting.add_argument("--predictor-config", type=Path, required=True)
    reporting.add_argument("--selection-complete", type=Path, required=True)
    reporting.add_argument("--selected-primary-priced-rows", type=int)
    reporting.add_argument("--claim-limit", action="append", default=[])
    reporting.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.mode == "predictor":
            document = build_predictor(
                resolve_under_root(args.year_plan, label="year_plan"),
                {
                    name: resolve_under_root(getattr(args, name), label=name)
                    for name in ("features", "dictionary", "sidecar", "labels")
                },
                resolve_under_root(args.design, label="design"),
                decision=args.decision,
                execution_scope=args.execution_scope,
                proposal_status=args.proposal_status,
                provenance=[
                    resolve_under_root(item, label="provenance") for item in args.provenance
                ],
                claim_limits=args.claim_limit,
            )
        else:
            document = build_reporting(
                resolve_under_root(args.predictor_config, label="predictor_config"),
                resolve_under_root(args.selection_complete, label="selection_complete"),
                primary_contrast=args.primary_contrast,
                secondary_contrasts=args.secondary_contrast,
                bootstrap_seed=args.bootstrap_seed,
                selected_primary_priced_rows=args.selected_primary_priced_rows,
                claim_limits=args.claim_limit,
            )
        output, digest = write_config(document, args.output)
    except ChainError as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "mode": args.mode,
                "config": relative_to_root(output),
                "sha256": digest,
                "real_fits": 0,
                "real_scores": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
