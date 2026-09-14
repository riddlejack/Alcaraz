"""The one place a data root is declared.

Every path a stage reads or writes is expressed relative to a *workspace* root and is
confined to it. Nothing in the package resolves a path against the location of its own
source file, mutates ``sys.path`` or carries an absolute path.

The workspace is named by the ``TENNISLAB_WORKSPACE`` environment variable and defaults
to the current working directory, which for ordinary use is the repository root. An
equivalence run against the research archive points the workspace at a scratch tree
whose read-only parts are links into the archive; see ``tools/equivalence.py``.

Containment is checked lexically, without following symbolic links, so a workspace may
link its inputs from elsewhere while every write still lands inside it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

WORKSPACE_ENVIRONMENT_VARIABLE = "TENNISLAB_WORKSPACE"


class WorkspaceError(ValueError):
    """A path escaped the declared workspace or no workspace could be found."""


@dataclass(frozen=True)
class Workspace:
    root: Path

    @classmethod
    def from_environment(cls) -> Workspace:
        declared = os.environ.get(WORKSPACE_ENVIRONMENT_VARIABLE)
        root = Path(declared) if declared else Path.cwd()
        root = Path(os.path.normpath(os.path.abspath(root)))
        if not root.is_dir():
            raise WorkspaceError(f"workspace is not a directory: {root}")
        return cls(root)

    def path(self, value: str | os.PathLike[str], *, label: str = "path") -> Path:
        """Resolve ``value`` under the workspace root and refuse anything outside it."""
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        normalized = Path(os.path.normpath(candidate))
        if normalized != self.root and self.root not in normalized.parents:
            raise WorkspaceError(f"{label} lies outside the workspace {self.root}: {normalized}")
        return normalized

    def relative(self, value: str | os.PathLike[str], *, label: str = "path") -> str:
        """The workspace-relative string form of ``value``, with forward slashes."""
        return self.path(value, label=label).relative_to(self.root).as_posix()

    def contains(self, value: str | os.PathLike[str]) -> bool:
        try:
            self.path(value)
        except WorkspaceError:
            return False
        return True


@lru_cache(maxsize=1)
def workspace() -> Workspace:
    """The process-wide workspace, read once from the environment."""
    return Workspace.from_environment()


def reset_workspace_cache() -> None:
    """For tests that change the environment between calls."""
    workspace.cache_clear()
