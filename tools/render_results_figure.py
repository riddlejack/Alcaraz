"""Render the README results figure from the generated result artifacts.

Every plotted number is read from a committed artifact; nothing is typed in by hand.

- Panel A, the ATP feature ladder: match-weighted log loss per rung from
  ``docs/ladder.json`` and winner-picking accuracy from ``docs/winner_accuracy.json``
  (ATP overall rows). Both must describe the same matched cohort.
- Panel B, paired log-loss differences against public systems, each on its own cohort:
  BuildOak over ATP 2017–2024 from ``docs/benchmarks/buildoak_2017_2024.json`` (ARMS01
  contrast 2, ``full_tier_entry``), Ultimate Tennis Statistics on ATP 2024 from
  ``docs/benchmarks/EXTERNAL_2024_2025_RESULTS.json`` and Ingram on ATP 2024 from
  ``docs/benchmarks/ingram_2024.json`` (both ``full_tier``), each with its primary
  eight-week block-bootstrap 95% interval. The cohorts differ, so every row carries its
  own cohort and Alcaraz-rung label; each row's two sides must have the same size.

matplotlib is deliberately not part of the locked ``uv`` environment. Run this script
with the system ``python3`` (tested with matplotlib 3.11), not ``uv run``::

    python3 tools/render_results_figure.py   # from the repository root

It writes ``docs/assets/alcaraz-results.svg`` and ``docs/assets/alcaraz-results.png``, and
the per-season BuildOak figure ``docs/assets/alcaraz-by-season.svg`` / ``.png`` (ARMS01
contrast 2 annual paired differences from ``docs/benchmarks/buildoak_2017_2024.json``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(".")  # run from the repository root, like the other docs tools

# Design tokens (light mode).
SURFACE = "#fcfcfb"
TEXT1 = "#0b0b0b"
TEXT2 = "#52514e"
TEXT3 = "#8a8985"
GRID = "#e6e5e1"
BLUE = "#2a78d6"  # Alcaraz
ORANGE = "#eb6834"  # market
NEUTRAL = "#9a9994"  # other systems

# Ladder rung key -> (label, colour), bottom to top of the plotted order.
LADDER_RUNGS = (
    ("elo", "Elo only (K=32, overall + surface)", NEUTRAL),
    ("atp_p0", "+ boosted model on results, ranks, workload", NEUTRAL),
    ("atp_p1", "+ traits, dynamic serve/return states", NEUTRAL),
    ("atp_full_tier", "+ qualifying, Challenger, Futures history", NEUTRAL),
    ("atp_full_tier_entry", "+ entry status, tournament level", BLUE),
    ("pinnacle_normalised", "Pinnacle closing price (normalised)", ORANGE),
)
PRIMARY_BLOCK_WEEKS = 8


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"render_results_figure: {message}")


def ladder_rows(root: Path) -> tuple[list[tuple[str, float, float, str]], int, list[int]]:
    """Match-weighted log loss and accuracy per rung on the shared ATP cohort."""
    pooled = _load(root / "docs/ladder.json")["tours"]["ATP"]["pooled"]
    accuracy = _load(root / "docs/winner_accuracy.json")["tours"]["ATP"]["overall"]
    n = int(pooled["n"])
    rows = []
    for key, label, colour in LADDER_RUNGS:
        _require(int(accuracy[key]["n"]) == n, f"{key} accuracy n differs from ladder n {n}")
        log_loss = float(pooled[f"log_loss_{key}_match_weighted"])
        rows.append((label, log_loss, 100.0 * float(accuracy[key]["accuracy"]), colour))
    return rows, n, [int(year) for year in pooled["years"]]


def _interval(results: dict[str, Any], weeks: int) -> tuple[float, float]:
    low, high = results[str(weeks)]["percentile_95"]
    return float(low), float(high)


def comparison_rows(root: Path) -> list[tuple[str, float, float, float]]:
    """Alcaraz-minus-system paired log loss and its primary interval, one cohort per row."""
    benchmarks = root / "docs/benchmarks"

    arms01 = _load(benchmarks / "buildoak_2017_2024.json")
    buildoak = arms01["contrasts"]["contrast2_arm1_minus_buildoak"]
    _require(
        int(buildoak["primary_interval_log_loss"]["mean_block_weeks"]) == PRIMARY_BLOCK_WEEKS,
        "buildoak primary block is not eight weeks",
    )
    years = buildoak["years"]
    buildoak_row = (
        f"BuildOak XGBoost\n{int(buildoak['n']):,} ATP, {years[0]}–{str(years[-1])[2:]}"
        f" · {arms01['systems']['arm1']['label']}",
        float(buildoak["difference"]["match_weighted"]["log_loss"]),
        *(float(bound) for bound in buildoak["intervals_95"]["log_loss"][str(PRIMARY_BLOCK_WEEKS)]),
    )

    external = _load(benchmarks / "EXTERNAL_2024_2025_RESULTS.json")["comparisons"]
    uts = next(c for c in external if c["id"] == "uts_fixed_formula_adaptation_atp_2024")
    paired = uts["paired_log_loss"]
    weeks = int(paired["primary_mean_block_weeks"])
    _require(weeks == PRIMARY_BLOCK_WEEKS, f"UTS primary block is {weeks} weeks")
    uts_row = (
        f"Ultimate Tennis Statistics\n{int(uts['cohort']['matches']):,} ATP, "
        f"{uts['cohort']['season']} · full_tier",
        float(paired["alcaraz_minus_external"]),
        *(float(bound) for bound in paired["primary_95_interval"]),
    )

    ingram = _load(benchmarks / "ingram_2024.json")["primary"]
    weeks = int(ingram["uncertainty"]["primary_block_weeks"])
    _require(weeks == PRIMARY_BLOCK_WEEKS, f"Ingram primary block is {weeks} weeks")
    _require(
        int(ingram["incumbent"]["n"]) == int(ingram["ingram"]["n"]), "Ingram sides differ in size"
    )
    _require(
        int(uts["cohort"]["matches"]) == int(ingram["incumbent"]["n"]),
        "UTS and Ingram 2024 cohorts differ in size",
    )
    ingram_row = (
        f"Ingram point model\n{int(ingram['incumbent']['n']):,} ATP, "
        f"{uts['cohort']['season']} · full_tier",
        float(ingram["incumbent_minus_ingram_log_loss"]),
        *_interval(ingram["uncertainty"]["results"], weeks),
    )
    return [buildoak_row, uts_row, ingram_row]


def render(root: Path, output_dir: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import rcParams

    rows, ladder_n, years = ladder_rows(root)
    comps = comparison_rows(root)

    rcParams.update(
        {
            "font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
            "font.size": 11,
            "axes.edgecolor": GRID,
            "axes.labelcolor": TEXT2,
            "xtick.color": TEXT2,
            "ytick.color": TEXT1,
            "text.color": TEXT1,
            "svg.fonttype": "none",
            "svg.hashsalt": "alcaraz-results",
        }
    )

    # Stacked panels: at README column width a side-by-side layout shrinks the type
    # below legibility, so the figure is one column wide and two panels tall.
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(8.6, 9.0), gridspec_kw={"height_ratios": [1.45, 1.0], "hspace": 0.62}
    )
    fig.patch.set_facecolor(SURFACE)

    # Panel A: the ladder on one cohort.
    ax1.set_facecolor(SURFACE)
    ys = list(range(len(rows)))[::-1]
    for y, (_label, log_loss, acc, colour) in zip(ys, rows, strict=True):
        ax1.plot([0.58, log_loss], [y, y], color=GRID, lw=1, zorder=1)
        ax1.scatter([log_loss], [y], s=90, color=colour, edgecolor=SURFACE, linewidth=2, zorder=3)
        ax1.text(
            log_loss + 0.0012,
            y,
            f"{log_loss:.4f}   ·   {acc:.1f}% picks",
            va="center",
            ha="left",
            fontsize=10,
            color=TEXT2,
        )
    ax1.set_yticks(ys)
    ax1.set_yticklabels([row[0] for row in rows], fontsize=10.5)
    ax1.set_xlim(0.580, 0.640)
    ax1.set_ylim(-0.6, len(rows) - 0.55)
    ax1.set_xticks([0.58, 0.59, 0.60, 0.61, 0.62, 0.63])
    ax1.set_xlabel("log loss (lower is better)")
    ax1.grid(axis="x", color=GRID, lw=1)
    for side in ("top", "right", "left"):
        ax1.spines[side].set_visible(False)
    ax1.tick_params(axis="y", length=0)
    ax1.set_title(
        f"Same {ladder_n:,} ATP matches, {years[0]}–{years[-1]}",
        loc="left",
        fontsize=12.5,
        fontweight="bold",
        color=TEXT1,
        pad=22,
    )
    ax1.text(
        0,
        1.015,
        "Each rung adds one block of public statistics; every step is paired on identical matches",
        transform=ax1.transAxes,
        fontsize=9.5,
        color=TEXT3,
        va="bottom",
    )

    # Panel B: paired differences against public systems.
    ax2.set_facecolor(SURFACE)
    ys2 = list(range(len(comps)))[::-1]
    ax2.axvline(0, color=TEXT3, lw=1, zorder=1)
    for y, (_label, delta, low, high) in zip(ys2, comps, strict=True):
        ax2.plot([low, high], [y, y], color=BLUE, lw=2, solid_capstyle="round", zorder=2)
        ax2.scatter([delta], [y], s=90, color=BLUE, edgecolor=SURFACE, linewidth=2, zorder=3)
        ax2.text(
            delta,
            y - 0.2,
            f"{delta:+.4f}  [{low:+.4f}, {high:+.4f}]",
            fontsize=9.5,
            color=TEXT2,
            va="top",
            ha="center",
        )
    ax2.set_yticks(ys2)
    ax2.set_yticklabels([comp[0] for comp in comps], fontsize=10.5)
    ax2.set_xlim(-0.072, 0.022)
    ax2.set_ylim(-0.75, 2.45)
    ax2.set_xticks([-0.06, -0.04, -0.02, 0.0, 0.02])
    ax2.set_xlabel("Alcaraz minus system, paired log loss (negative favours Alcaraz)")
    ax2.grid(axis="x", color=GRID, lw=1)
    for side in ("top", "right", "left"):
        ax2.spines[side].set_visible(False)
    ax2.tick_params(axis="y", length=0)
    ax2.set_title(
        "Paired against public models, each on its own matches",
        loc="left",
        fontsize=12.5,
        fontweight="bold",
        color=TEXT1,
        pad=22,
    )
    crossing = [label.split("\n")[0] for label, _, low, high in comps if low < 0 < high]
    subtitle = "95% calendar-week block bootstrap"
    if crossing:
        noun = "interval crosses" if len(crossing) == 1 else "intervals cross"
        subtitle += f"; the {' and '.join(crossing)} {noun} zero"
    else:
        subtitle += "; every interval excludes zero"
    ax2.text(0, 1.015, subtitle, transform=ax2.transAxes, fontsize=9.5, color=TEXT3, va="bottom")

    fig.text(
        0.01,
        0.035,
        "Sources: docs/ladder.json, docs/winner_accuracy.json, docs/benchmarks/*.json. "
        "Retrospective, outcome-exposed development\ncomparisons; intervals condition on "
        "saved forecasts.",
        fontsize=8.5,
        color=TEXT3,
        va="top",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    svg = output_dir / "alcaraz-results.svg"
    png = output_dir / "alcaraz-results.png"
    fig.savefig(svg, format="svg", bbox_inches="tight", facecolor=SURFACE, metadata={"Date": None})
    fig.savefig(png, format="png", dpi=160, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return [svg, png]


def season_rows(root: Path) -> tuple[list[tuple[int, float]], int, int, float]:
    """Alcaraz-minus-BuildOak paired log loss per season, ARMS01 contrast 2."""
    arms01 = _load(root / "docs/benchmarks/buildoak_2017_2024.json")
    contrast = arms01["contrasts"]["contrast2_arm1_minus_buildoak"]
    annual = contrast["difference"]["annual_log_loss"]
    years = [int(year) for year in contrast["years"]]
    _require(sorted(annual) == [str(year) for year in years], "annual years differ from cohort")
    rows = [(year, float(annual[str(year)])) for year in years]
    negative = sum(1 for _year, delta in rows if delta < 0)
    _require(negative == int(contrast["difference"]["years_negative"]), "years_negative mismatch")
    pooled = float(contrast["difference"]["match_weighted"]["log_loss"])
    return rows, int(contrast["n"]), negative, pooled


def render_by_season(root: Path, output_dir: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import rcParams

    rows, n, negative, pooled = season_rows(root)
    rcParams.update(
        {
            "font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
            "font.size": 11,
            "axes.edgecolor": GRID,
            "axes.labelcolor": TEXT2,
            "xtick.color": TEXT1,
            "ytick.color": TEXT2,
            "text.color": TEXT1,
            "svg.fonttype": "none",
            "svg.hashsalt": "alcaraz-by-season",
        }
    )
    fig, ax = plt.subplots(figsize=(8.6, 3.6))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    xs = list(range(len(rows)))
    ax.axhline(0, color=TEXT3, lw=1, zorder=1)
    ax.axhline(pooled, color=BLUE, lw=1, ls=(0, (4, 3)), zorder=1)
    ax.text(
        -0.35,
        0.0028,
        f"dashed line: all seasons pooled, {pooled:+.4f}",
        fontsize=9,
        color=BLUE,
        ha="left",
        va="center",
    )
    for x, (_year, delta) in zip(xs, rows, strict=True):
        colour = BLUE if delta < 0 else NEUTRAL
        ax.bar(x, delta, width=0.62, color=colour, zorder=2)
        ax.text(
            x,
            delta - 0.0006 if delta < 0 else delta + 0.0006,
            f"{delta:+.4f}",
            fontsize=9,
            color=TEXT2,
            ha="center",
            va="top" if delta < 0 else "bottom",
        )
    ax.set_xticks(xs)
    ax.set_xticklabels([str(year) for year, _delta in rows])
    ax.set_ylim(-0.0165, 0.0045)
    ax.set_yticks([-0.015, -0.010, -0.005, 0.0])
    ax.set_ylabel("Alcaraz minus BuildOak, paired log loss")
    ax.grid(axis="y", color=GRID, lw=1)
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="x", length=0)
    ax.set_title(
        f"Ahead of BuildOak in {negative} of {len(rows)} seasons",
        loc="left",
        fontsize=12.5,
        fontweight="bold",
        color=TEXT1,
        pad=20,
    )
    ax.text(
        0,
        1.02,
        f"Same {n:,} ATP matches, {rows[0][0]}–{rows[-1][0]}; negative favours Alcaraz",
        transform=ax.transAxes,
        fontsize=9.5,
        color=TEXT3,
        va="bottom",
    )
    fig.text(
        0.01,
        -0.02,
        "Source: docs/benchmarks/buildoak_2017_2024.json (ARMS01 contrast 2). "
        "Retrospective development comparison.",
        fontsize=8.5,
        color=TEXT3,
        va="top",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    svg = output_dir / "alcaraz-by-season.svg"
    png = output_dir / "alcaraz-by-season.png"
    fig.savefig(svg, format="svg", bbox_inches="tight", facecolor=SURFACE, metadata={"Date": None})
    fig.savefig(png, format="png", dpi=160, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return [svg, png]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "docs/assets", help="figure directory"
    )
    args = parser.parse_args()
    for path in render(args.root, args.output_dir) + render_by_season(args.root, args.output_dir):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
