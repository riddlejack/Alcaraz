"""Gate T10 (Lane C2, admitted by archive R15/R17): manifest integrity of a completed run.

PASS CRITERION (kept from C2, evaluated on the synthetic run tree): every file hash a
stage manifest records re-derives from the bytes on disk and the stage directory holds
exactly the files it declares; each manifest's ``outputs_sha256`` is the canonical hash
of its output table and equals the ledger entry for that stage; the chain ledger
verifies link by link from genesis; the barrier's ``run_tree`` names exactly the
pre-barrier stages, every leaf carries a well-formed SHA-256 that re-hashes correctly
and agrees with that stage's own manifest, and ``run_tree_sha256`` is non-placeholder
and equals the canonical hash of the recorded tree. The report's artifact manifest and
the SR03 run manifest re-hash too. A placeholder digest is a defect only where the
content it summarises is non-empty (C2's refinement: an empty ``stderr.txt`` legitimately
hashes to the empty-string digest, and the barrier's empty output map to the empty-object
digest).

NEGATIVE CONTROLS (same check function, on a scratch copy of the run tree): a changed
byte in a frozen leaf, a broken ledger link, a placeholder run-tree digest and a leaf
with its hash omitted each fail.

Not a proof of source truth: matching hashes show the tree is the one the chain froze,
not that the chain's inputs were correct.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from tennislab.chain import runner
from tests.gate_support import (
    EMPTY_OBJECT_SHA256,
    EMPTY_STRING_SHA256,
    PLACEHOLDERS,
    canonical_hash,
    must_reject,
    read_json,
    sha256,
)

HEX64 = re.compile(r"[0-9a-f]{64}")


def _ledger(run_root: Path) -> list[dict[str, Any]]:
    path = run_root / runner.LEDGER
    assert path.is_file(), "ledger is missing"
    entries = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
    assert entries, "ledger is empty"
    return entries


def _leaf_ok(record: Any) -> bool:
    return (
        isinstance(record, dict)
        and isinstance(record.get("sha256"), str)
        and bool(HEX64.fullmatch(record["sha256"]))
    )


def _placeholder_defects(node: Any, path: str = "") -> list[str]:
    """Digest fields holding a placeholder whose summarised content is not empty."""
    defects: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if (
                isinstance(value, str)
                and ("sha256" in key or "digest" in key)
                and value in PLACEHOLDERS
            ):
                if key == "sha256" and node.get("bytes") == 0 and value == EMPTY_STRING_SHA256:
                    continue  # accurate hash of a genuinely empty file
                if (
                    key == "outputs_sha256"
                    and node.get("outputs") == {}
                    and value == EMPTY_OBJECT_SHA256
                ):
                    continue  # accurate hash of an empty output map (the barrier)
                defects.append(here)
            defects += _placeholder_defects(value, here)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            defects += _placeholder_defects(value, f"{path}[{index}]")
    return defects


def check_manifest_integrity(run_root: Path) -> dict[str, Any]:
    entries = _ledger(run_root)
    stages = [entry["stage"] for entry in entries]
    assert len(set(stages)) == len(stages), "a stage appears twice in the ledger"
    assert stages.count("barrier") == 1, "ledger needs exactly one barrier"

    # (1) Ledger links from genesis.
    previous = "genesis"
    for index, entry in enumerate(entries):
        assert entry.get("previous_entry_sha256") == previous, (
            f"ledger break at entry {index} ({entry.get('stage')})"
        )
        previous = canonical_hash(entry)

    # (2) Every stage manifest re-hashes from disk and matches its ledger entry.
    files_checked = 0
    manifests: dict[str, dict[str, Any]] = {}
    for entry in entries:
        name = entry["stage"]
        manifest = read_json(run_root / name / runner.STAGE_MANIFEST)
        manifests[name] = manifest
        declared = manifest["outputs"]
        assert isinstance(declared, dict), f"{name}: malformed output table"
        observed = runner.hash_tree(run_root / name)
        assert set(observed) == set(declared), (
            f"{name}: file-hash membership differs: {sorted(set(observed) ^ set(declared))[:5]}"
        )
        for relative, record in declared.items():
            assert _leaf_ok(record), f"{name}/{relative}: missing/malformed leaf hash"
            assert observed[relative]["sha256"] == record["sha256"], (
                f"{name}/{relative}: file-hash mismatch"
            )
            assert observed[relative]["bytes"] == record["bytes"], (
                f"{name}/{relative}: size differs"
            )
            files_checked += 1
        assert manifest["outputs_sha256"] == canonical_hash(declared), (
            f"{name}: outputs_sha256 differs"
        )
        assert entry["outputs_sha256"] == manifest["outputs_sha256"], (
            f"{name}: ledger entry differs"
        )
        assert manifest["integrity_violations"] == [], f"{name}: recorded integrity violations"
        assert entry.get("integrity") != "fail", f"{name}: ledger records an integrity failure"
        defects = _placeholder_defects(manifest)
        assert not defects, f"{name}: placeholder digest over non-empty content: {defects[:3]}"

    # (3) The barrier's frozen run tree.
    barrier = manifests["barrier"]
    run_tree = barrier.get("run_tree")
    digest = barrier.get("run_tree_sha256")
    assert isinstance(run_tree, dict) and run_tree, "missing or empty run-tree inventory"
    assert set(run_tree) == set(stages[: stages.index("barrier")]), (
        "run-tree stage inventory differs from the pre-barrier ledger"
    )
    tree_files = 0
    for stage, leaves in run_tree.items():
        assert isinstance(leaves, dict) and leaves, f"malformed run-tree stage: {stage}"
        assert leaves == manifests[stage]["outputs"], f"run tree differs from {stage}'s manifest"
        for relative, record in leaves.items():
            assert _leaf_ok(record), f"missing/malformed run-tree leaf hash: {stage}/{relative}"
            path = run_root / stage / relative
            assert path.is_file() and sha256(path) == record["sha256"], (
                f"run-tree leaf differs from disk: {stage}/{relative}"
            )
            tree_files += 1
    assert isinstance(digest, str) and digest not in PLACEHOLDERS, (
        f"barrier run-tree placeholder digest: {digest}"
    )
    assert digest == canonical_hash(run_tree), "barrier run_tree_sha256 != canonical_hash(run_tree)"

    # (4) Stage-written artifact manifests re-hash as well.
    artifacts = 0
    report_manifest = run_root / "report" / "artifact_manifest.json"
    if report_manifest.is_file():
        for item in read_json(report_manifest)["files"]:
            path = run_root / "report" / item["path"]
            assert path.is_file() and sha256(path) == item["sha256"], (
                f"report artifact differs: {item['path']}"
            )
            assert path.stat().st_size == item["bytes"], (
                f"report artifact size differs: {item['path']}"
            )
            artifacts += 1
    sr03_manifest = run_root / "sr03_calibration" / "run_manifest.json"
    if sr03_manifest.is_file():
        for name, expected in read_json(sr03_manifest)["artifacts"].items():
            path = run_root / "sr03_calibration" / name
            assert path.is_file() and sha256(path) == expected, f"SR03 artifact differs: {name}"
            artifacts += 1
    return {
        "ledger_links": len(entries),
        "stages": stages,
        "files_checked": files_checked,
        "run_tree_files": tree_files,
        "artifact_manifest_files": artifacts,
        "run_tree_sha256": digest,
    }


# ------------------------------------------------------------------ clean behaviour


def test_the_frozen_run_tree_re_hashes(sample_run: dict[str, Any]) -> None:
    result = check_manifest_integrity(sample_run["run_root"])
    assert result["stages"] == sample_run["stages"]
    assert result["ledger_links"] == len(sample_run["stages"]) >= 14
    assert result["files_checked"] > 100 and result["run_tree_files"] > 100
    assert result["artifact_manifest_files"] > 15
    # The gate's ledger and output verdicts agree with the chain's own verifiers.
    runner.verify_ledger(sample_run["run_root"])
    runner.verify_earlier(sample_run["run_root"], sample_run["stages"])


# ------------------------------------------------------------------ negative controls


def test_each_planted_manifest_defect_fails_the_check(
    sample_run: dict[str, Any], tmp_path: Path
) -> None:
    run_root = tmp_path / "run"
    shutil.copytree(sample_run["run_root"], run_root)
    check_manifest_integrity(run_root)
    detected: list[str] = []

    leaf = run_root / "features" / "features.csv"
    original = leaf.read_bytes()
    with leaf.open("ab") as handle:
        handle.write(b"\n")  # one changed byte; every recorded hash of it is now stale
    detected.append(must_reject(lambda: check_manifest_integrity(run_root), "file-hash mismatch"))
    leaf.write_bytes(original)

    ledger = run_root / runner.LEDGER
    ledger_original = ledger.read_text("utf-8")
    entries = [json.loads(line) for line in ledger_original.splitlines() if line.strip()]
    entries[3]["previous_entry_sha256"] = "0" * 64
    ledger.write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in entries), "utf-8")
    detected.append(
        must_reject(lambda: check_manifest_integrity(run_root), "ledger break at entry 3")
    )
    ledger.write_text(ledger_original, "utf-8")

    barrier = run_root / "barrier" / runner.STAGE_MANIFEST
    barrier_original = barrier.read_text("utf-8")
    manifest = json.loads(barrier_original)
    manifest["run_tree_sha256"] = EMPTY_OBJECT_SHA256
    barrier.write_text(json.dumps(manifest), "utf-8")
    detected.append(must_reject(lambda: check_manifest_integrity(run_root), "placeholder digest"))

    manifest = json.loads(barrier_original)
    del manifest["run_tree"]["features"]["features.csv"]["sha256"]
    manifest["run_tree_sha256"] = canonical_hash(manifest["run_tree"])
    barrier.write_text(json.dumps(manifest), "utf-8")
    detected.append(
        must_reject(lambda: check_manifest_integrity(run_root), "run tree differs from features")
    )
    # And once the stage manifest is made to agree, the leaf without a hash is still refused.
    features = run_root / "features" / runner.STAGE_MANIFEST
    features_original = features.read_text("utf-8")
    stage = json.loads(features_original)
    del stage["outputs"]["features.csv"]["sha256"]
    stage["outputs_sha256"] = canonical_hash(stage["outputs"])
    features.write_text(json.dumps(stage), "utf-8")
    detected.append(
        must_reject(lambda: check_manifest_integrity(run_root), "missing/malformed leaf hash")
    )
    features.write_text(features_original, "utf-8")
    barrier.write_text(barrier_original, "utf-8")

    check_manifest_integrity(run_root)  # every plant was reverted
    assert len(detected) == 5
