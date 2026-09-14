import os
from pathlib import Path

import pytest

from tennislab.chain import common
from tennislab.config import Workspace, WorkspaceError, reset_workspace_cache


def test_relative_paths_resolve_under_root(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    assert ws.path("work/x.csv") == tmp_path / "work" / "x.csv"
    assert ws.relative(tmp_path / "work" / "x.csv") == "work/x.csv"


def test_escape_is_refused(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    with pytest.raises(WorkspaceError):
        ws.path("../elsewhere")
    with pytest.raises(WorkspaceError):
        ws.path("/etc/passwd")


def test_links_are_not_followed_for_containment(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.txt").write_text("x")
    inside = tmp_path / "ws"
    inside.mkdir()
    os.symlink(outside, inside / "data")
    ws = Workspace(inside)
    assert ws.path("data/f.txt").read_text() == "x"


def test_workspace_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(tmp_path))
    reset_workspace_cache()
    assert common.resolve_under_root("a/b", label="t") == tmp_path / "a" / "b"
    reset_workspace_cache()


def test_empty_digests_are_rejected() -> None:
    with pytest.raises(common.ChainError):
        common.require_nonempty_digest(common.canonical_hash({}), label="run_tree")
    with pytest.raises(common.ChainError):
        common.require_nonempty_digest("PENDING", label="x")
    good = common.canonical_hash({"a": 1})
    assert common.require_nonempty_digest(good, label="x") == good
