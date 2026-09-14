"""Render the README's ATP per-year chart from the generated ladder JSON."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def _point(value: float, low: float, high: float, top: float, height: float) -> float:
    return top + (high - value) * height / (high - low)


def render(source: Path) -> str:
    payload = json.loads(source.read_text())
    tours = payload["tours"]
    tour = (
        tours["ATP"]
        if isinstance(tours, dict)
        else next(item for item in tours if item["pooled"]["tour"] == "ATP")
    )
    rows = tour["per_year"]
    years = [int(row["year"]) for row in rows]
    model = [float(row["log_loss_atp_full_tier"]) for row in rows]
    market = [float(row["log_loss_pinnacle_normalised"]) for row in rows]
    counts = [int(row["n"]) for row in rows]

    width, height = 960, 600
    left, right, top, bottom = 88, 56, 116, 150
    plot_width = width - left - right
    plot_height = height - top - bottom
    all_values = model + market
    low = math.floor((min(all_values) - 0.004) * 200) / 200
    high = math.ceil((max(all_values) + 0.004) * 200) / 200
    ticks = [low + index * (high - low) / 4 for index in range(5)]
    xs = [left + index * plot_width / (len(years) - 1) for index in range(len(years))]
    model_ys = [_point(value, low, high, top, plot_height) for value in model]
    market_ys = [_point(value, low, high, top, plot_height) for value in market]

    def path(points: list[tuple[float, float]]) -> str:
        return " ".join(
            ("M" if index == 0 else "L") + f" {x:.1f} {y:.1f}"
            for index, (x, y) in enumerate(points)
        )

    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="600" '
        'viewBox="0 0 960 600" role="img" aria-labelledby="title desc">',
        '<title id="title">ATP full-tier model and normalised Pinnacle log loss by year</title>',
        '<desc id="desc">On the identical priced cohort in every year from 2017 through '
        "2024, the full-tier model has higher log loss than normalised Pinnacle. Lower is better.</desc>",
        '<rect width="960" height="600" rx="18" fill="#f8fafc"/>',
        '<text x="48" y="48" font-family="ui-sans-serif, system-ui, sans-serif" '
        'font-size="25" font-weight="700" fill="#0f172a">Pinnacle had lower log loss in all '
        "eight ATP target years</text>",
        '<text x="48" y="78" font-family="ui-sans-serif, system-ui, sans-serif" '
        'font-size="14" fill="#475569">Full-tier model vs normalised Pinnacle · identical '
        "priced cohort in each year · lower is better</text>",
    ]

    for tick in ticks:
        y = _point(tick, low, high, top, plot_height)
        lines.extend(
            [
                f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" '
                'stroke="#cbd5e1" stroke-width="1"/>',
                f'<text x="{left - 14}" y="{y + 5:.1f}" text-anchor="end" '
                'font-family="ui-monospace, SFMono-Regular, monospace" font-size="12" '
                f'fill="#64748b">{tick:.3f}</text>',
            ]
        )

    for x, year, count in zip(xs, years, counts, strict=True):
        lines.extend(
            [
                f'<text x="{x:.1f}" y="{top + plot_height + 30}" text-anchor="middle" '
                'font-family="ui-sans-serif, system-ui, sans-serif" font-size="13" '
                f'font-weight="600" fill="#334155">{year}</text>',
                f'<text x="{x:.1f}" y="{top + plot_height + 49}" text-anchor="middle" '
                'font-family="ui-sans-serif, system-ui, sans-serif" font-size="10" '
                f'fill="#94a3b8">n={count:,}</text>',
            ]
        )

    lines.extend(
        [
            f'<path d="{path(list(zip(xs, model_ys, strict=True)))}" fill="none" '
            'stroke="#d97706" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>',
            f'<path d="{path(list(zip(xs, market_ys, strict=True)))}" fill="none" '
            'stroke="#2563eb" stroke-width="4" stroke-dasharray="10 7" '
            'stroke-linejoin="round" stroke-linecap="round"/>',
        ]
    )

    for x, y in zip(xs, model_ys, strict=True):
        lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#d97706"/>')
    for x, y in zip(xs, market_ys, strict=True):
        lines.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#f8fafc" '
            'stroke="#2563eb" stroke-width="3"/>'
        )

    lines.extend(
        [
            '<line x1="550" y1="542" x2="584" y2="542" stroke="#d97706" stroke-width="4"/>',
            '<circle cx="567" cy="542" r="5" fill="#d97706"/>',
            '<text x="594" y="547" font-family="ui-sans-serif, system-ui, sans-serif" '
            'font-size="13" fill="#334155">full_tier</text>',
            '<line x1="702" y1="542" x2="736" y2="542" stroke="#2563eb" stroke-width="4" '
            'stroke-dasharray="10 7"/>',
            '<circle cx="719" cy="542" r="5" fill="#f8fafc" stroke="#2563eb" stroke-width="3"/>',
            '<text x="746" y="547" font-family="ui-sans-serif, system-ui, sans-serif" '
            'font-size="13" fill="#334155">Pinnacle, normalised</text>',
            '<text x="48" y="582" font-family="ui-sans-serif, system-ui, sans-serif" '
            'font-size="11" fill="#64748b">Source: docs/ladder.json · match-weighted '
            "retrospective development data · matched n shown below each year</text>",
            "</svg>",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("docs/ladder.json"))
    parser.add_argument(
        "--output", type=Path, default=Path("docs/assets/atp_full_tier_vs_market.svg")
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(args.input))


if __name__ == "__main__":
    main()
