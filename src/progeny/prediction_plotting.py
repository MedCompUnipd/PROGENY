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
DASHES = (
    "",
    "8 4",
    "2 3",
    "10 3 2 3",
    "5 3",
    "1 3",
    "8 3 2 3",
    "4 2 1 2",
    "6 2",
    "3 2",
)
WIDTH = 740
LEFT = 90
TOP = 60
PLOT_SIZE = 500


def _number(value: float) -> str:
    return f"{value:.6g}"


def _aspect_code(aspect: str) -> str:
    labels = {
        "Molecular Function": "MF",
        "Molecular Function (MF)": "MF",
        "Biological Process": "BP",
        "Biological Process (BP)": "BP",
        "Cellular Component": "CC",
        "Cellular Component (CC)": "CC",
    }
    return labels.get(aspect, aspect)


def _line_style(index: int) -> tuple[str, str]:
    color = PALETTE[index % len(PALETTE)]
    dash = DASHES[index % len(DASHES)]
    attribute = f' stroke-dasharray="{dash}"' if dash else ""
    return color, attribute


def _svg_header(title: str, height: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
        f'height="{height}" viewBox="0 0 {WIDTH} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<g font-family="sans-serif" font-size="13" fill="#222">',
        f'<text x="340" y="29" text-anchor="middle" font-size="17">'
        f"{html.escape(title)}</text>",
    ]


def _legend(
    elements: list[str],
    *,
    method: str,
    color: str,
    dash_attribute: str,
    y: int,
) -> None:
    elements.extend(
        [
            f'<path d="M 90 {y} H 122" stroke="{color}" '
            f'stroke-width="1.8"{dash_attribute} fill="none"/>',
            f'<text x="132" y="{y + 4}">{html.escape(method)}</text>',
        ]
    )


def _draw_axes(
    elements: list[str],
    *,
    xlabel: str,
    ylabel: str,
    xmax: float,
    ymax: float,
    xunit: bool,
    yunit: bool,
) -> None:
    for index in range(6):
        fraction = index / 5
        x = LEFT + fraction * PLOT_SIZE
        y = TOP + (1 - fraction) * PLOT_SIZE
        xtick = fraction if xunit else fraction * xmax
        ytick = fraction if yunit else fraction * ymax
        elements.extend(
            [
                f'<path d="M {x:g} {TOP} V {TOP + PLOT_SIZE} '
                f'M {LEFT} {y:g} H {LEFT + PLOT_SIZE}" '
                'stroke="#e4e4e4" stroke-width="0.7" fill="none"/>',
                f'<text x="{x:g}" y="{TOP + PLOT_SIZE + 23}" '
                f'text-anchor="middle">{xtick:.3g}</text>',
                f'<text x="{LEFT - 12}" y="{y + 4:g}" '
                f'text-anchor="end">{ytick:.3g}</text>',
            ]
        )
    elements.extend(
        [
            f'<rect x="{LEFT}" y="{TOP}" width="{PLOT_SIZE}" '
            f'height="{PLOT_SIZE}" fill="none" stroke="#777" '
            'stroke-width="0.8"/>',
            f'<text x="340" y="610" text-anchor="middle">{html.escape(xlabel)}</text>',
            '<text transform="translate(25 310) rotate(-90)" '
            f'text-anchor="middle">{html.escape(ylabel)}</text>',
        ]
    )


def render_metric_svg(
    *,
    aspect: str,
    metric: str,
    series: Mapping[str, Sequence[Mapping[str, float]]],
    ylabel: str,
    fixed_unit_range: bool,
) -> str:
    """Render one threshold metric using the publication-panel styling."""
    values = [
        float(row[metric])
        for rows in series.values()
        for row in rows
        if row.get(metric) is not None
    ]
    maximum = 1.0 if fixed_unit_range else max(values, default=0.0) * 1.08
    if maximum <= 0:
        maximum = 1.0
    ordered_series = sorted(series.items())
    height = 650 + 24 * len(ordered_series)
    elements = _svg_header(f"{ylabel} · {_aspect_code(aspect)}", height)
    _draw_axes(
        elements,
        xlabel="Threshold τ",
        ylabel=ylabel,
        xmax=1.0,
        ymax=maximum,
        xunit=True,
        yunit=fixed_unit_range,
    )
    for index, (method, rows) in enumerate(ordered_series):
        points = []
        for row in sorted(rows, key=lambda item: item["threshold"]):
            value = row.get(metric)
            if value is None:
                continue
            x = LEFT + float(row["threshold"]) * PLOT_SIZE
            y = TOP + (1 - float(value) / maximum) * PLOT_SIZE
            points.append((x, y))
        if not points:
            continue
        color, dash_attribute = _line_style(index)
        coordinates = " ".join(f"{x:.9g},{y:.9g}" for x, y in points)
        elements.append(
            f'<polyline points="{coordinates}" fill="none" '
            f'stroke="{color}"{dash_attribute} stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )
        for x, y in points:
            elements.append(f'<circle cx="{x:.9g}" cy="{y:.9g}" r="2" fill="{color}"/>')
        _legend(
            elements,
            method=method,
            color=color,
            dash_attribute=dash_attribute,
            y=642 + index * 24,
        )
    elements.append("</g></svg>")
    return "\n".join(elements) + "\n"


def render_precision_recall_svg(
    *,
    aspect: str,
    series: Mapping[str, Sequence[Mapping[str, float]]],
) -> str:
    """Render a precision-recall plot in the publication-panel style."""
    ordered_series = sorted(series.items())
    height = 650 + 24 * len(ordered_series)
    title = f"Precision–Recall · {_aspect_code(aspect)}"
    elements = _svg_header(title, height)
    _draw_axes(
        elements,
        xlabel="Recall",
        ylabel="Precision",
        xmax=1.0,
        ymax=1.0,
        xunit=True,
        yunit=True,
    )
    for index, (method, rows) in enumerate(ordered_series):
        points = []
        for row in rows:
            recall = row.get("recall")
            precision = row.get("precision")
            if recall is None or precision is None:
                continue
            x = LEFT + float(recall) * PLOT_SIZE
            y = TOP + (1 - float(precision)) * PLOT_SIZE
            points.append((x, y))
        if not points:
            continue
        color, dash_attribute = _line_style(index)
        coordinates = " ".join(f"{x:.9g},{y:.9g}" for x, y in points)
        elements.append(
            f'<polyline points="{coordinates}" fill="none" '
            f'stroke="{color}"{dash_attribute} stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )
        for x, y in points:
            elements.append(f'<circle cx="{x:.9g}" cy="{y:.9g}" r="2" fill="{color}"/>')
        _legend(
            elements,
            method=method,
            color=color,
            dash_attribute=dash_attribute,
            y=642 + index * 24,
        )
    elements.append("</g></svg>")
    return "\n".join(elements) + "\n"
