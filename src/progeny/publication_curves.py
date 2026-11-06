"""Standalone scientific SVG panels from existing PROGENY curve tables."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
from collections import defaultdict
from pathlib import Path

ASPECTS = {"F": "MF", "P": "BP", "C": "CC"}
COLORS = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00")
DASHES = ("", "8 4", "2 3", "10 3 2 3", "5 3")
KINDS = {
    "precision_recall": ("recall", "precision", "f1", "Recall", "Precision"),
    "weighted_precision_recall": (
        "weighted_recall",
        "weighted_precision",
        "weighted_f1",
        "Weighted recall",
        "Weighted precision",
    ),
    "ru_mi": (
        "ru",
        "mi",
        "smin",
        "Remaining uncertainty (bits/protein)",
        "Misinformation (bits/protein)",
    ),
}


def read_curves(path: Path) -> dict:
    """Validate complete per-method grids; preserve original sampled values."""
    groups = defaultdict(lambda: defaultdict(list))
    seen = set()
    required = {"method_id", "aspect", "threshold", "coverage"}
    for fields in KINDS.values():
        required.update(fields[:3])
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", strict=True)
        names = reader.fieldnames or []
        if len(set(names)) != len(names) or not required <= set(names):
            raise ValueError("Invalid PROGENY curves.tsv header")
        for raw in reader:
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError(f"Malformed TSV row {reader.line_num}")
            method, aspect = raw["method_id"], raw["aspect"]
            if not method or aspect not in ASPECTS:
                raise ValueError(f"Invalid method/aspect at row {reader.line_num}")
            row = {}
            for key in required - {"method_id", "aspect"}:
                row[key] = float(raw[key]) if raw[key] else None
                if row[key] is not None and (
                    not math.isfinite(row[key]) or row[key] < 0
                ):
                    raise ValueError(f"Invalid {key} at row {reader.line_num}")
                if key not in {"ru", "mi", "smin"} and (
                    row[key] is not None and row[key] > 1
                ):
                    raise ValueError(f"Out-of-range {key}")
            if row["threshold"] is None:
                raise ValueError("Missing threshold")
            key = (method, aspect, row["threshold"])
            if key in seen:
                raise ValueError(f"Duplicate curve row: {key}")
            seen.add(key)
            groups[aspect][method].append(row)
    if not groups:
        raise ValueError("Empty curves table")
    for methods in groups.values():
        grids = {
            tuple(sorted(r["threshold"] for r in rows)) for rows in methods.values()
        }
        if len(grids) != 1:
            raise ValueError("Method threshold grids differ within an aspect")
    return groups


def render_panel(aspect: str, kind: str, series: dict) -> tuple[str, list]:
    """Connect observed points in threshold order; mark the grid optimum."""
    xkey, ykey, bestkey, xlabel, ylabel = KINDS[kind]
    semantic = kind == "ru_mi"
    left, top, size = 90, 60, 500
    valid = {
        method: sorted(
            (r for r in rows if all(r[k] is not None for k in (xkey, ykey, bestkey))),
            key=lambda r: r["threshold"],
            reverse=True,
        )
        for method, rows in sorted(series.items())
    }
    xmax = ymax = 1.0
    if semantic:
        xmax = max((r[xkey] for rows in valid.values() for r in rows), default=0)
        ymax = max((r[ykey] for rows in valid.values() for r in rows), default=0)
        xmax, ymax = xmax * 1.05 or 1, ymax * 1.05 or 1
    height = 650 + 24 * len(valid)
    title = {
        "precision_recall": "Precision–Recall",
        "weighted_precision_recall": "Weighted Precision–Recall",
        "ru_mi": "Remaining Uncertainty–Misinformation",
    }[kind]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="740" '
        f'height="{height}" viewBox="0 0 740 {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<g font-family="sans-serif" font-size="13" fill="#222">',
        f'<text x="340" y="29" text-anchor="middle" font-size="17">'
        f"{title} · {ASPECTS[aspect]}</text>",
    ]
    for i in range(6):
        fraction = i / 5
        x, y = left + fraction * size, top + (1 - fraction) * size
        out.extend(
            [
                f'<path d="M {x:g} {top} V {top + size} '
                f'M {left} {y:g} H {left + size}" '
                'stroke="#e4e4e4" stroke-width="0.7" fill="none"/>',
                f'<text x="{x:g}" y="{top + size + 23}" '
                f'text-anchor="middle">{fraction * xmax:.3g}</text>',
                f'<text x="{left - 12}" y="{y + 4:g}" '
                f'text-anchor="end">{fraction * ymax:.3g}</text>',
            ]
        )
    out.extend(
        [
            f'<rect x="{left}" y="{top}" width="{size}" height="{size}" '
            'fill="none" stroke="#777" stroke-width="0.8"/>',
            f'<text x="340" y="610" text-anchor="middle">{xlabel}</text>',
            '<text transform="translate(25 310) rotate(-90)" '
            f'text-anchor="middle">{ylabel}</text>',
        ]
    )
    best_rows = []
    for i, (method, rows) in enumerate(valid.items()):
        color = COLORS[i % len(COLORS)]
        dash = DASHES[i % len(DASHES)]
        style = f'stroke="{color}" stroke-dasharray="{dash}"'
        if not rows:
            continue
        points = [
            (left + r[xkey] / xmax * size, top + (1 - r[ykey] / ymax) * size)
            for r in rows
        ]
        coords = " ".join(f"{x:.9g},{y:.9g}" for x, y in points)
        out.append(
            f'<polyline points="{coords}" fill="none" {style} stroke-width="1.8"/>'
        )
        if len(points) == 1:
            x, y = points[0]
            out.append(f'<circle cx="{x:.9g}" cy="{y:.9g}" r="2" fill="{color}"/>')
        candidates = [
            r for r in rows if kind == "precision_recall" or r.get("coverage", 1.0) > 0
        ]
        best = None
        if candidates:
            best = (
                min(candidates, key=lambda r: (r[bestkey], -r["threshold"]))
                if semantic
                else max(candidates, key=lambda r: (r[bestkey], r["threshold"]))
            )
            x = left + best[xkey] / xmax * size
            y = top + (1 - best[ykey] / ymax) * size
            out.append(
                f'<circle cx="{x:.9g}" cy="{y:.9g}" '
                f'r="{5 + i % 3}" fill="none" stroke="{color}" '
                'stroke-width="1.8"/>'
            )
        value_label = (
            "Smin" if semantic else ("wFmax" if kind.startswith("weighted") else "Fmax")
        )
        legend_y = 642 + i * 24
        label = method + " (not evaluable)"
        if best is not None:
            label = (
                f"{method} ({value_label}={best[bestkey]:.4f}; τ={best['threshold']:g})"
            )
        out.extend(
            [
                f'<path d="M 90 {legend_y} H 122" {style} '
                'stroke-width="1.8" fill="none"/>',
                f'<text x="132" y="{legend_y + 4}">{html.escape(label)}</text>',
            ]
        )
        if best is None:
            continue
        best_rows.append(
            {
                "method_id": method,
                "aspect": aspect,
                "plot": kind,
                "metric": value_label,
                "value": best[bestkey],
                "threshold": best["threshold"],
                "x": best[xkey],
                "y": best[ykey],
            }
        )
    out.append("</g></svg>")
    return "\n".join(out) + "\n", best_rows


def write_panels(curves: Path, output: Path, *, include_weighted: bool) -> dict:
    """Publish fresh plot outputs; leave the source evaluation untouched."""
    groups = read_curves(curves)
    if output.exists():
        raise ValueError("Output directory must be new")
    kinds = ["precision_recall", "ru_mi"]
    if include_weighted:
        kinds.append("weighted_precision_recall")
    outputs = {}
    best_rows = []
    for aspect, series in sorted(groups.items()):
        for kind in kinds:
            svg, best = render_panel(aspect, kind, series)
            outputs[f"{kind}_{ASPECTS[aspect]}.svg"] = svg
            best_rows.extend(best)
    source_sha = hashlib.sha256(curves.read_bytes()).hexdigest()
    output.mkdir(parents=False)
    for name, svg in outputs.items():
        (output / name).write_text(svg, encoding="utf-8")
    with (output / "best_points.tsv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(best_rows[0])
            if best_rows
            else [
                "method_id",
                "aspect",
                "plot",
                "metric",
                "value",
                "threshold",
                "x",
                "y",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(best_rows)
    report = {
        "schema": "progeny-publication-curves-v1",
        "source_curves_sha256": source_sha,
        "plot_count": len(outputs),
        "aspects": sorted(groups),
        "interpolation": "straight_segments_in_threshold_order",
        "best_points": "best_points.tsv",
        "svg_sha256": {
            name: hashlib.sha256(svg.encode()).hexdigest()
            for name, svg in outputs.items()
        },
    }
    (output / "plot_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
