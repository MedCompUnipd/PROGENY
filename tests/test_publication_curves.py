import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from progeny.publication_curves import render_panel, write_panels


def points():
    return [
        {
            "threshold": 0.8,
            "recall": 0.2,
            "precision": 0.9,
            "f1": 0.3272727273,
            "ru": 5.0,
            "mi": 1.0,
            "smin": 26**0.5,
        },
        {
            "threshold": 0.4,
            "recall": 0.7,
            "precision": 0.8,
            "f1": 0.7466666667,
            "ru": 2.0,
            "mi": 1.5,
            "smin": 2.5,
        },
        {
            "threshold": 0.2,
            "recall": 0.9,
            "precision": 0.4,
            "f1": 0.5538461538,
            "ru": 1.0,
            "mi": 4.0,
            "smin": 17**0.5,
        },
    ]


def test_optimum_is_measured_point_and_overlap_has_distinct_styles():
    svg, best = render_panel(
        "F", "precision_recall", {"A < B": points(), "copy": points()}
    )
    root = ET.fromstring(svg)
    ns = {"s": "http://www.w3.org/2000/svg"}
    curves = root.findall(".//s:polyline", ns)
    assert len(curves) == 2
    assert curves[0].attrib["points"] == curves[1].attrib["points"]
    assert (
        curves[0].attrib["stroke-dasharray"] != (curves[1].attrib["stroke-dasharray"])
    )
    assert all(r["threshold"] == 0.4 for r in best)
    assert all(r["x"] == 0.7 and r["y"] == 0.8 for r in best)
    assert "A &lt; B" in svg
    assert len(root.findall(".//s:circle", ns)) == 2


def test_ru_mi_uses_semantic_axes_and_minimum():
    svg, best = render_panel("P", "ru_mi", {"A": points()})
    ET.fromstring(svg)
    assert best[0]["value"] == 2.5
    assert best[0]["threshold"] == 0.4
    assert best[0]["x"] == 2.0 and best[0]["y"] == 1.5
    assert "Remaining uncertainty" in svg
    assert "Misinformation" in svg


def test_publishing_requires_new_directory():
    with tempfile.TemporaryDirectory() as directory:
        _publishing(Path(directory))


def _publishing(tmp_path):
    curves = tmp_path / "curves.tsv"
    header = [
        "method_id",
        "aspect",
        "threshold",
        "precision",
        "recall",
        "f1",
        "weighted_precision",
        "weighted_recall",
        "weighted_f1",
        "ru",
        "mi",
        "smin",
        "coverage",
    ]
    curves.write_text(
        "\t".join(header) + "\n"
        "A\tF\t0.4\t0.8\t0.7\t0.7467\t0.8\t0.7\t0.7467"
        "\t2\t1.5\t2.5\t1\n"
    )
    output = tmp_path / "plots"
    before = curves.read_bytes()
    result = write_panels(curves, output, include_weighted=True)
    assert result["plot_count"] == 3
    assert len(list(output.glob("*.svg"))) == 3
    assert curves.read_bytes() == before
    with unittest.TestCase().assertRaisesRegex(ValueError, "must be new"):
        write_panels(curves, output, include_weighted=True)


if __name__ == "__main__":
    test_optimum_is_measured_point_and_overlap_has_distinct_styles()
    test_ru_mi_uses_semantic_axes_and_minimum()
    test_publishing_requires_new_directory()
    print("PUBLICATION_PLOT_CHECKS=PASS")
