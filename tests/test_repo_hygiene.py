"""Acceptance check 5: no absolute path, no sys.path mutation, no import-by-path, no
read outside the declared workspace in tracked code."""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FORBIDDEN = {
    "absolute home path": re.compile(r"/Users/|/home/|C:\\\\"),
    "sys.path mutation": re.compile(r"sys\.path\.(insert|append)"),
    "import by path": re.compile(r"spec_from_file_location|load_module\(|load_sibling_package"),
    "source-relative repository root": re.compile(
        r"Path\(__file__\)\.resolve\(\)\.parents\[[12]\]"
    ),
}
ALLOWED = {
    # The hygiene test itself names the patterns; the harness anchors on the repo root.
    "tests/test_repo_hygiene.py": {*FORBIDDEN},
    "tools/equivalence.py": {"source-relative repository root"},
}


def tracked_python() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "src", "tools", "tests"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [REPO / line for line in out.stdout.splitlines() if line.endswith(".py")]


def test_no_forbidden_patterns_in_tracked_code() -> None:
    offences: list[str] = []
    for path in tracked_python():
        relative = path.relative_to(REPO).as_posix()
        text = path.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN.items():
            if label in ALLOWED.get(relative, set()):
                continue
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offences.append(f"{relative}:{line}: {label}")
    assert not offences, "\n".join(offences)


def test_tracked_data_has_no_absolute_paths() -> None:
    out = subprocess.run(
        ["git", "ls-files", "data", "configs"], cwd=REPO, capture_output=True, text=True, check=True
    )
    offences = []
    for line in out.stdout.splitlines():
        path = REPO / line
        if path.suffix in {".json", ".csv", ".md", ".jsonl"} and "/Users/" in path.read_text(
            encoding="utf-8", errors="ignore"
        ):
            offences.append(line)
    assert not offences, offences
