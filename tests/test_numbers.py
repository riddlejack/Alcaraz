"""``tennislab.numbers``: the placeholder language of the public pages. Synthetic values only."""

from __future__ import annotations

import pytest

from tennislab import numbers

DATA = {
    "cohort": {"n": 18972, "years": [2017, 2018, 2019], "priced": {"n": 18882}},
    "contrast": {"difference": -0.00703, "interval": [-0.01004, -0.00402], "years_negative": 2},
    "rows": [{"segment": "rank: 101/200", "share": 0.3456}, {"segment": "other", "share": 0.5}],
    "annual": {"2017": -0.0078, "2025": 0.0015},
    "files": {"docs/a.md": 0.25},
}


def resolve(alias: str, path: str):
    assert alias == "x"
    return numbers.lookup(DATA, path)


@pytest.mark.parametrize(
    ("placeholder", "expected"),
    [
        ("x:cohort/n|int", "18,972"),
        ("x:contrast/difference|s4", "−0.0070"),
        ("x:contrast/difference|abs4", "0.0070"),
        ("x:contrast/interval|ci4", "[−0.0100, −0.0040]"),
        ("x:rows/[segment=rank: 101/200]/share|pct1", "34.6%"),
        ("x:rows/1/share|pct0", "50%"),
        ("x:cohort/years|span", "2017–2019"),
        ("x:cohort/years|len|word", "three"),
        ("x:contrast/years_negative|Word", "Two"),
        ("x:cohort/n - x:cohort/priced/n|int", "90"),
        ("x:annual|values|last|s4", "+0.0015"),
        ("x:annual|values|negatives|word", "one"),
        ("x:cohort/n / 1000|round|word", "nineteen"),
        ("75|word", "seventy-five"),
        ("0.000000000001|e0", "1e-12"),
        ("x:files/'docs/a.md'|pct0", "25%"),
        ("1 / x:contrast/difference|neg|f1", "142.2"),
    ],
)
def test_placeholder_formats(placeholder: str, expected: str) -> None:
    assert numbers.render_placeholder(placeholder, resolve) == expected


def test_template_comment_is_dropped_and_unresolvable_path_raises() -> None:
    text = "A {{x:cohort/n|int}} B{{# slot {{x:missing|int}} #}}."
    assert numbers.render_text(text, resolve) == "A 18,972 B."
    with pytest.raises(numbers.NumbersError):
        numbers.render_text("{{x:missing/key|int}}", resolve)
    with pytest.raises(numbers.NumbersError):
        numbers.render_text("{{x:cohort/n}}", resolve)  # no format: refuses a bare value
