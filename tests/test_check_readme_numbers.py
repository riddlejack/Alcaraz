"""``tools/check_readme_numbers.py``: templated pages must render byte for byte from the
JSONs, typed numbers are untraced, missing sources are pending. Synthetic pages only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path("tools", "check_readme_numbers.py").resolve()
DATA = {"cohort": {"n": 18972}, "k": 7}


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    write(tmp_path / "docs/x.json", json.dumps(DATA))
    write(tmp_path / "docs/templates/PAGE.md.in", "Matches: {{x:cohort/n|int}}; 95% interval.\n")
    registry = {
        "aliases": {"x": "docs/x.json", "later": "docs/not_yet.json"},
        "pages": [
            {
                "page": "PAGE.md",
                "template": "docs/templates/PAGE.md.in",
                "allowed": [{"text": "95%", "reason": "level"}],
            },
            {
                "page": "README.md",
                "bindings": [
                    {"context": "We scored", "text": "18,972", "value": "{{x:cohort/n|int}}"},
                    {
                        "context": "Seasons",
                        "offset": 1,
                        "text": "7 of 8",
                        "value": "{{x:k|d}} of 8",
                    },
                ],
                "allowed": [{"text": "95%", "reason": "level"}],
            },
        ],
    }
    write(tmp_path / "docs/numbers.json", json.dumps(registry))
    write(tmp_path / "README.md", README)
    return tmp_path


README = (
    "We scored 18,972 matches; 95% intervals.\n"
    "Seasons ahead:\n"
    "7 of 8\n"
    "Skipped: `code 42`, [link](docs/x_2024_7.md), 2026-09-24, 22 September, 2017–2025,\n"
    "2025–26, D137, IBM02 and <!-- 99 in a comment -->.\n"
)


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), "--root", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_render_then_check_passes_and_edit_is_stale(repo: Path) -> None:
    assert run(repo, "--page", "PAGE.md").returncode == 1  # not rendered yet
    assert run(repo, "--page", "PAGE.md", "--render").returncode == 0
    assert (repo / "PAGE.md").read_text() == "Matches: 18,972; 95% interval.\n"
    assert run(repo, "--page", "PAGE.md").returncode == 0
    (repo / "PAGE.md").write_text("Matches: 18,973; 95% interval.\n")
    done = run(repo, "--page", "PAGE.md")
    assert done.returncode == 1
    assert "STALE PAGE.md" in done.stdout


def test_literal_number_in_template_is_untraced(repo: Path) -> None:
    write(repo / "docs/templates/PAGE.md.in", "Matches: {{x:cohort/n|int}}, typed 0.6046.\n")
    done = run(repo, "--page", "PAGE.md", "--render")
    assert done.returncode == 1
    assert "UNTRACED docs/templates/PAGE.md.in:1: 0.6046" in done.stdout


def test_missing_source_is_pending(repo: Path) -> None:
    write(repo / "docs/templates/PAGE.md.in", "Later: {{later:n|int}}.\n")
    done = run(repo, "--page", "PAGE.md", "--render")
    assert done.returncode == 1
    assert "PENDING PAGE.md: missing source docs/not_yet.json" in done.stdout
    assert not (repo / "PAGE.md").exists()


def test_bound_readme_passes_and_skips_non_results(repo: Path) -> None:
    done = run(repo, "--page", "README.md")
    assert done.returncode == 0, done.stdout
    assert "OK README.md (bindings): 3 bound, 1 allowed constants, 0 untraced" in done.stdout


def test_changed_number_is_a_mismatch_and_new_number_is_untraced(repo: Path) -> None:
    text = README.replace("18,972 matches", "18,973 matches, 0.6046 log loss")
    (repo / "README.md").write_text(text)
    done = run(repo, "--page", "README.md")
    assert done.returncode == 1
    assert "MISMATCH README.md:1: shows '18,972'" not in done.stdout
    assert "MISSING README.md:1: '18,972' is not on the line of 'We scored'" in done.stdout
    assert "UNTRACED README.md:1: 18,973; no JSON value matches" in done.stdout
    assert "UNTRACED README.md:1: 0.6046" in done.stdout


def test_stale_context_and_wrong_value_fail(repo: Path) -> None:
    (repo / "README.md").write_text(README.replace("We scored", "Scored"))
    assert "STALE BINDING README.md: context 'We scored' not found" in run(repo).stdout
    (repo / "docs/x.json").write_text(json.dumps({"cohort": {"n": 18972}, "k": 6}))
    (repo / "README.md").write_text(README)
    assert "MISMATCH README.md:3: shows '7 of 8', the JSON gives '6 of 8'" in run(repo).stdout


def test_compound_number_is_scanned_and_marked_lines_are_skipped(repo: Path) -> None:
    registry = json.loads((repo / "docs/numbers.json").read_text())
    readme = registry["pages"][1]
    readme["skip_lines_containing"] = ["SLOT_ROW"]
    readme["bindings"].append(
        {"context": "ledger", "text": "18,972", "value": "{{x:cohort/n|int}}"}
    )
    (repo / "docs/numbers.json").write_text(json.dumps(registry))
    (repo / "README.md").write_text(README + "A 18,972-entry ledger.\n| Model | SLOT_ROW 0.61 |\n")
    done = run(repo, "--page", "README.md")
    assert done.returncode == 0, done.stdout
    assert "4 bound" in done.stdout  # 18,972 twice, 7 and 8
    assert "SKIPPED README.md lines [7]" in done.stdout
