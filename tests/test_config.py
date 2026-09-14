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


def test_output_path_refuses_link_to_outside_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    inside = tmp_path / "ws"
    inside.mkdir()
    os.symlink(outside, inside / "data")
    ws = Workspace(inside)
    # Inputs may still be read through the link.
    assert ws.path("data/f.txt") == inside / "data" / "f.txt"
    with pytest.raises(WorkspaceError, match="symbolic link"):
        ws.output_path("data/out/x.csv", label="output_dir")
    with pytest.raises(WorkspaceError, match="symbolic link"):
        ws.output_path("data", label="output_dir")


def test_output_path_refuses_link_inside_workspace(tmp_path: Path) -> None:
    inside = tmp_path / "ws"
    (inside / "real").mkdir(parents=True)
    os.symlink(inside / "real", inside / "alias")
    ws = Workspace(inside)
    with pytest.raises(WorkspaceError, match="alias"):
        ws.output_path("alias/out.json")
    # A link to a file is refused as the destination itself.
    (inside / "real" / "f.txt").write_text("x")
    os.symlink(inside / "real" / "f.txt", inside / "real" / "g.txt")
    with pytest.raises(WorkspaceError, match="g.txt"):
        ws.output_path("real/g.txt")


def test_output_path_accepts_plain_directories(tmp_path: Path) -> None:
    inside = tmp_path / "ws"
    (inside / "work" / "run").mkdir(parents=True)
    ws = Workspace(inside)
    assert ws.output_path("work/run/stage") == inside / "work" / "run" / "stage"
    assert ws.output_path("work/new/deeper/x.csv") == inside / "work" / "new" / "deeper" / "x.csv"
    assert ws.output_path(inside) == inside


def test_output_path_refuses_workspace_that_escapes_physically(tmp_path: Path) -> None:
    # A component that is a real directory but whose parent chain crosses a link is
    # caught by the link check; the realpath check covers the deepest existing ancestor.
    outside = tmp_path / "outside"
    (outside / "sub").mkdir(parents=True)
    inside = tmp_path / "ws"
    inside.mkdir()
    os.symlink(outside, inside / "linked")
    ws = Workspace(inside)
    with pytest.raises(WorkspaceError):
        ws.output_path("linked/sub/new.csv")
    with pytest.raises(common.ChainError):
        reset_workspace_cache()
        os.environ["TENNISLAB_WORKSPACE"] = str(inside)
        try:
            common.resolve_output_under_root("linked/sub", label="output_dir")
        finally:
            del os.environ["TENNISLAB_WORKSPACE"]
            reset_workspace_cache()


def test_stage_refuses_to_write_into_linked_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: a stage's output directory that is a link out of the workspace fails
    before anything is written."""
    from tennislab.chronology import edition_index

    outside = tmp_path / "outside"
    outside.mkdir()
    inside = tmp_path / "ws"
    (inside / "work").mkdir(parents=True)
    os.symlink(outside, inside / "work" / "edition_index")
    monkeypatch.setenv("TENNISLAB_WORKSPACE", str(inside))
    reset_workspace_cache()
    try:
        with pytest.raises(common.ChainError, match="symbolic link"):
            edition_index.main(
                ["--source", "work/rankings.csv.gz", "--output-dir", "work/edition_index"]
            )
    finally:
        reset_workspace_cache()
    assert not any(outside.iterdir())
