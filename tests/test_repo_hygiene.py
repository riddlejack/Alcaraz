"""Acceptance check 5: no host path, no sys.path mutation, no import-by-path, no
source-relative repository root in any tracked text file.

Every tracked file that decodes as UTF-8 is scanned, not only code: evidence records and
documentation carry host strings just as easily. The tracked equivalence records are
placeholder representations of local originals (docs/equivalence/LOCAL_EVIDENCE.md).
"""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FORBIDDEN = {
    "absolute host path": re.compile(r"/Users/|/home/|/private/tmp/|/tmp/|C:\\\\"),
    # The words "sys.path" may appear in prose (docstrings, docs/PORTING.md); a mutation is
    # a call or an assignment on it.
    "sys.path mutation": re.compile(r"sys\.path\s*(?:\.\s*(?:insert|append|extend)\s*\(|\+?=|\[)"),
    "import by path": re.compile(r"spec_from_file_location|load_module\(|load_sibling_package"),
    "source-relative repository root": re.compile(
        r"Path\(__file__\)\.resolve\(\)\.parents\[[12]\]"
    ),
}
ALLOWED = {
    # The hygiene test names the patterns it forbids; the harness anchors on the repo root.
    "tests/test_repo_hygiene.py": {*FORBIDDEN},
    "tools/equivalence.py": {"source-relative repository root"},
    # The build helper locates its checkout; its generated example locates its bundle.
    # Host-prefix literals are the forbidden strings its privacy scan detects, not paths
    # to a developer's files. Neither exception applies to the runtime model loader.
    "tools/build_model_release.py": {"source-relative repository root", "absolute host path"},
    "tools/build_campaign_model_release.py": {
        "source-relative repository root",
        "absolute host path",
    },
    # Porting notes quote, in prose, the archive's by-path load they replaced.
    "docs/equivalence/notes/tier_block.md": {"import by path"},
    "docs/equivalence/notes/tier_elo.md": {"import by path"},
}


def tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True
    )
    files = []
    for line in out.stdout.split("\0"):
        if not line or line.startswith(".git/"):
            continue
        path = REPO / line
        if not path.is_file():
            continue
        try:
            path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        files.append(path)
    assert files, "git ls-files returned nothing"
    return files


def test_no_forbidden_patterns_in_any_tracked_text_file() -> None:
    offences: list[str] = []
    for path in tracked_text_files():
        relative = path.relative_to(REPO).as_posix()
        text = path.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN.items():
            if label in ALLOWED.get(relative, set()):
                continue
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offences.append(f"{relative}:{line}: {label}: {match.group(0)!r}")
    assert not offences, "\n".join(offences)


def test_sys_path_pattern_is_precise() -> None:
    pattern = FORBIDDEN["sys.path mutation"]
    assert pattern.search("sys.path.insert(0, x)")
    assert pattern.search("sys.path.append(x)")
    assert pattern.search("sys.path = [x]")
    assert pattern.search("sys.path += [x]")
    assert pattern.search("sys.path[0:0] = [x]")
    assert not pattern.search("the archive put work/ on ``sys.path``; here it is imported")
    assert not pattern.search("no `sys.path` mutation, no `load_module` by path")


def test_local_evidence_store_is_ignored() -> None:
    out = subprocess.run(
        ["git", "check-ignore", "-q", "local/evidence/index.json"], cwd=REPO, check=False
    )
    assert out.returncode == 0, "local/ must be ignored so originals never get tracked"
    assert (REPO / "docs" / "equivalence" / "LOCAL_EVIDENCE.md").is_file()
