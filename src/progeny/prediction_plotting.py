"""Dependency-free comparative SVG plots for threshold metric curves."""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence

PALETTE = (
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#E69F00",
    "#56B4E9",
    "#000000",
    "#7A68A6",
    "#8C564B",
    "#6B8E23",
)
WIDTH = 1100
LEFT = 90
RIGHT = 36
TOP = 58
PLOT_HEIGHT = 440


def _number(value: float) -> str:
    return f"{value:.6g}"


def _coordinates(
    threshold: float,
    value: float,
    *,
    maximum: float,
) -> tuple[float, float]:
    plot_width = WIDTH - LEFT - RIGHT
    x = LEFT + threshold * plot_width
    y = TOP + (1 - value / maximum) * PLOT_HEIGHT
    return x, y


def render_metric_svg(
    *,
    aspect: str,
    metric: str,
    series: Mapping[str, Sequence[Mapping[str, float]]],
    ylabel: str,
    fixed_unit_range: bool,
) -> str:
    """Render one aspect/metric chart with one line for every method."""
    values = [
        float(row[metric])
        for rows in series.values()
        for row in rows
        if row.get(metric) is not None
    ]
    maximum = 1.0 if fixed_unit_range else max(values, default=0.0) * 1.08
    if maximum <= 0:
        maximum = 1.0
    plot_width = WIDTH - LEFT - RIGHT
    plot_bottom = TOP + PLOT_HEIGHT
    ordered_series = sorted(series.items())
    legend_rows = max(1, (len(ordered_series) + 2) // 3)
    height = plot_bottom + 76 + legend_rows * 22
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
        f'height="{height}" viewBox="0 0 {WIDTH} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{WIDTH / 2}" y="30" text-anchor="middle" '
        'font-family="sans-serif" font-size="20" font-weight="bold">'
        f"{html.escape(aspect)} — {html.escape(metric)}</text>",
    ]
    tick_count = 5
    for index in range(tick_count + 1):
        fraction = index / tick_count
        y = TOP + fraction * PLOT_HEIGHT
        tick = maximum * (1 - fraction)
        elements.append(
            f'<line x1="{LEFT}" y1="{_number(y)}" '
            f'x2="{LEFT + plot_width}" y2="{_number(y)}" '
            'stroke="#dddddd" stroke-width="1"/>'
        )
        elements.append(
            f'<text x="{LEFT - 12}" y="{_number(y + 4)}" '
            'text-anchor="end" font-family="sans-serif" font-size="12">'
            f"{_number(tick)}</text>"
        )
    for index in range(5):
        threshold = index / 4
        x = LEFT + threshold * plot_width
        elements.append(
            f'<line x1="{_number(x)}" y1="{TOP}" '
            f'x2="{_number(x)}" y2="{plot_bottom}" '
            'stroke="#eeeeee" stroke-width="1"/>'
        )
        elements.append(
            f'<text x="{_number(x)}" y="{plot_bottom + 22}" '
            'text-anchor="middle" font-family="sans-serif" font-size="12">'
            f"{threshold:.2f}</text>"
        )
    elements.extend(
        [
            f'<line x1="{LEFT}" y1="{plot_bottom}" '
            f'x2="{LEFT + plot_width}" y2="{plot_bottom}" '
            'stroke="#222222" stroke-width="1.5"/>',
            f'<line x1="{LEFT}" y1="{TOP}" x2="{LEFT}" '
            f'y2="{plot_bottom}" stroke="#222222" stroke-width="1.5"/>',
            f'<text x="{LEFT + plot_width / 2}" '
            f'y="{plot_bottom + 44}" text-anchor="middle" '
            'font-family="sans-serif" font-size="14">Threshold τ</text>',
            f'<text transform="translate(24 {TOP + PLOT_HEIGHT / 2}) '
            'rotate(-90)" text-anchor="middle" font-family="sans-serif" '
            f'font-size="14">{html.escape(ylabel)}</text>',
        ]
    )
    for index, (method, rows) in enumerate(ordered_series):
        points = []
        for row in sorted(rows, key=lambda item: item["threshold"]):
            value = row.get(metric)
            if value is None:
                continue
            x, y = _coordinates(float(row["threshold"]), float(value), maximum=maximum)
            points.append(f"{_number(x)},{_number(y)}")
        if not points:
            continue
        color = PALETTE[index % len(PALETTE)]
        elements.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="2" '
            f'points="{" ".join(points)}"/>'
        )
        for point in points:
            x, y = point.split(",", maxsplit=1)
            elements.append(
                f'<circle cx="{x}" cy="{y}" r="3" '
                f'fill="{color}" stroke="white" stroke-width="1"/>'
            )
        legend_row = index // 3
        legend_column = index % 3
        legend_y = plot_bottom + 70 + legend_row * 22
        legend_x = LEFT + legend_column * (plot_width / 3)
        elements.append(
            f'<line x1="{legend_x}" y1="{legend_y}" '
            f'x2="{legend_x + 24}" y2="{legend_y}" '
            f'stroke="{color}" stroke-width="3"/>'
        )
        elements.append(
            f'<text x="{legend_x + 31}" y="{legend_y + 4}" '
            'font-family="sans-serif" font-size="12">'
            f"{html.escape(method)}</text>"
        )
    elements.append("</svg>")
    return "\n".join(elements) + "\n"
