from __future__ import annotations

from progeny.prediction_plotting import (
    render_metric_svg,
    render_precision_recall_svg,
)


def test_svg_overlays_methods_and_escapes_labels() -> None:
    svg = render_metric_svg(
        aspect="BP",
        metric="f1",
        series={
            "method <A>": [
                {"threshold": 0.1, "f1": 0.2},
                {"threshold": 0.9, "f1": 0.7},
            ],
            "method B": [
                {"threshold": 0.1, "f1": 0.3},
                {"threshold": 0.9, "f1": 0.6},
            ],
        },
        ylabel="F1",
        fixed_unit_range=True,
    )
    assert svg.count("<polyline") == 2
    assert svg.count("<circle") == 4
    assert "method &lt;A&gt;" in svg
    assert "Threshold τ" in svg


def test_svg_renders_marker_for_single_threshold_point() -> None:
    svg = render_metric_svg(
        aspect="MF",
        metric="recall",
        series={"method": [{"threshold": 0.5, "recall": 0.0}]},
        ylabel="Recall",
        fixed_unit_range=True,
    )
    assert "<polyline" in svg
    assert "<circle" in svg


def test_semantic_axis_scales_to_positive_data() -> None:
    svg = render_metric_svg(
        aspect="MF",
        metric="smin",
        series={"m": [{"threshold": 0.5, "smin": 4.0}]},
        ylabel="Smin",
        fixed_unit_range=False,
    )
    assert "MF — smin" in svg
    assert "4.32" in svg


def test_precision_recall_plot_uses_precision_and_recall_coordinates():
    svg = render_precision_recall_svg(
        aspect="Molecular Function",
        series={
            "method_a": [
                {"recall": 0.25, "precision": 0.8},
                {"recall": 0.5, "precision": 0.6},
            ]
        },
    )
    assert "Precision–Recall" in svg
    assert "method_a" in svg
    assert svg.count("<circle") == 2
    assert 'cx="333.5" cy="146"' in svg
