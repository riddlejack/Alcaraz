"""The tracked evidence representation and its local original."""

import hashlib
import json
import sys
import sysconfig
from pathlib import Path

from tennislab import evidence


def test_placeholders_are_derived_from_the_running_host(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    repo = tmp_path / "repo"
    pairs = dict(evidence.host_placeholders(repo_root=repo, archive_root=archive))
    purelib = sysconfig.get_paths()["purelib"]
    assert pairs[purelib] == evidence.SITE_PACKAGES
    assert pairs[str(repo)] == evidence.PRODUCT_ROOT
    assert pairs[str(archive)] == evidence.ARCHIVE_ROOT
    inside = Path(purelib).relative_to(sys.prefix)
    assert pairs[str(archive / Path(sys.prefix).name / inside)] == evidence.SITE_PACKAGES
    lengths = [
        len(prefix)
        for prefix, _ in evidence.host_placeholders(repo_root=repo, archive_root=archive)
    ]
    assert lengths == sorted(lengths, reverse=True)
    assert (
        evidence.ARCHIVE_ROOT
        not in dict(evidence.host_placeholders(repo_root=repo, archive_root=None)).values()
    )


def test_write_evidence_keeps_the_original_and_tracks_a_representation(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    repo = tmp_path / "repo"
    repo.mkdir()
    placeholders = evidence.host_placeholders(repo_root=repo, archive_root=archive)
    record = {
        "first": [f"-{archive}/work/x.csv", f"+{repo}/work/x.csv"],
        "run_root": f"{archive}/experiments/runs/R/attempt_001/run",
        "sha256": "0" * 64,
    }
    text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    written = evidence.write_evidence(repo, "docs/equivalence/R/stage.json", text, placeholders)
    original = repo / "local" / "evidence" / "docs" / "equivalence" / "R" / "stage.json"
    assert original.read_text(encoding="utf-8") == text
    assert written["sha256"] == hashlib.sha256(text.encode()).hexdigest()
    tracked = json.loads((repo / "docs" / "equivalence" / "R" / "stage.json").read_text())
    assert tracked["first"] == ["-<ARCHIVE_ROOT>/work/x.csv", "+<PRODUCT_ROOT>/work/x.csv"]
    assert tracked["run_root"] == "<ARCHIVE_ROOT>/experiments/runs/R/attempt_001/run"
    assert tracked["sha256"] == "0" * 64
    assert str(tmp_path) not in json.dumps(tracked)
    index = json.loads((repo / "local" / "evidence" / "index.json").read_text())
    assert index["records"]["docs/equivalence/R/stage.json"]["sha256"] == written["sha256"]
    assert str(archive) in index["placeholders"]["<ARCHIVE_ROOT>"]
    # A second write updates the same entry instead of duplicating it.
    evidence.write_evidence(repo, "docs/equivalence/R/stage.json", text + "\n", placeholders)
    index = json.loads((repo / "local" / "evidence" / "index.json").read_text())
    assert list(index["records"]) == ["docs/equivalence/R/stage.json"]
    assert index["records"]["docs/equivalence/R/stage.json"]["sha256"] != written["sha256"]
