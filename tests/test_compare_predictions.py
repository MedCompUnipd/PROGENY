from __future__ import annotations

import csv
import hashlib
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from test_prediction_inputs import bundle as bundle

from progeny.ontology import GO_ROOTS
from progeny.prediction_inputs import load_benchmark_inputs
from progeny.prediction_plotting import render_metric_svg

ROOT = Path(__file__).resolve().parents[1]


def _write_predictions(path: Path, score: float) -> Path:
    path.write_text(
        f"query_id\tgo_id\tscore\nT1\tGO:0000001\t{score}\nT3\tGO:0000003\t{score}\n",
        encoding="utf-8",
    )
    return path


def _ia_artifacts(bundle, directory: Path) -> tuple[Path, Path]:
    benchmark = load_benchmark_inputs(**bundle)
    table = directory / "ia.tsv"
    manifest = directory / "ia-manifest.json"
    with table.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(
            ["go_id", "aspect", "ia", "term_count", "parent_conjunction_count"]
        )
        for term, record in sorted(benchmark.ontology.terms.items()):
            if not record.is_active:
                continue
            try:
                aspect = benchmark.aspect(term)
            except KeyError:
                continue
            weight = 0 if term in GO_ROOTS else 1
            writer.writerow([term, aspect, weight, 0, 1])
    table_sha = hashlib.sha256(table.read_bytes()).hexdigest()
    data = {
        "schema": "progeny-information-accretion-v3",
        "status": "COMPUTED",
        "source_role": "START",
        "source_release_id": "test-start",
        "gaf_sha256": "a" * 64,
        "ontology_sha256": benchmark.provenance["ontology_sha256"],
        "relations": ["is_a", "part_of"],
        "evidence_policy": "all_positive_uniprotkb_gaf_rows_including_iea",
        "go_resolution_policy": (
            "audit_source_namespace_then_follow_only_unambiguous_"
            "replaced_by_to_active_term"
        ),
        "remapped_go_count_policy": "accepted_rows_only",
        "cross_aspect_replacement_policy": "exclude_and_audit",
        "cross_aspect_replacement_rows_excluded": 0,
        "cross_aspect_replacement_mapping_counts": {},
        "source_aspect_mismatch_policy": "exclude_and_audit",
        "source_aspect_mismatch_rows_excluded": 0,
        "source_aspect_mismatch_mapping_counts": {},
        "invalid_gaf_aspect_policy": "exclude_and_audit",
        "invalid_gaf_aspect_rows_excluded": 0,
        "invalid_gaf_aspect_mapping_counts": {},
        "not_policy": "exclude_rows_with_NOT_qualifier",
        "smoothing": "one_synthetic_protein_annotated_to_every_active_term",
        "formula": "log2((count_all_direct_parents+1)/(count_term+1))",
        "ia_table_sha256": table_sha,
        "ia_terms": benchmark.graph.node_count,
    }
    manifest.write_text(json.dumps(data), encoding="utf-8")
    return table, manifest


def _cli(bundle, ia_table, ia_manifest, output, methods, *extra):
    command = [
        sys.executable,
        "-B",
        str(ROOT / "scripts/evaluation/compare_predictions.py"),
        "--dataset",
        str(bundle["dataset"]),
        "--run",
        str(bundle["run"]),
        "--ontology",
        str(bundle["ontology_path"]),
        "--benchmark-sha256",
        bundle["benchmark_sha256"],
        "--ia-table",
        str(ia_table),
        "--ia-manifest",
        str(ia_manifest),
        "--output-dir",
        str(output),
    ]
    for method_id, path in methods:
        command.extend(["--method", f"{method_id}={path}"])
    command.extend(extra)
    return subprocess.run(command, capture_output=True, text=True, check=True)


def test_common_grid_outputs_overlay_plots_by_metric_and_aspect(bundle, tmp_path):
    ia_table, ia_manifest = _ia_artifacts(bundle, tmp_path)
    alpha = _write_predictions(tmp_path / "alpha.tsv", 0.8)
    beta = _write_predictions(tmp_path / "beta.tsv", 0.6)
    output = tmp_path / "comparison"
    result = _cli(
        bundle,
        ia_table,
        ia_manifest,
        output,
        (("alpha", alpha), ("beta", beta)),
        "--threshold-step",
        "0.5",
    )
    assert json.loads(result.stdout)["status"] == "EVALUATED"
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["threshold_profile"]["threshold_count"] == 1
    assert summary["threshold_profile"]["interval"] == "[step, 1)"
    assert set(summary["methods"]) == {"alpha", "beta"}
    assert "curves.tsv" in summary["artifact_sha256"]
    assert "plots/weighted_f1_F.svg" in summary["artifact_sha256"]
    with (output / "curves.tsv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert {row["method_id"] for row in rows} == {"alpha", "beta"}
    assert {row["threshold"] for row in rows} == {"0.5"}
    plot = output / "plots" / "weighted_f1_F.svg"
    assert plot.is_file()
    assert plot.read_text(encoding="utf-8").count("<polyline") == 2
    recall_plot = (output / "plots" / "recall_F.svg").read_text(encoding="utf-8")
    f1_plot = (output / "plots" / "f1_F.svg").read_text(encoding="utf-8")
    assert recall_plot.count("<polyline") == 2
    assert f1_plot.count("<polyline") == 2
    assert recall_plot.count("<circle") > 0
    assert len(summary["plots"]) == 33


def test_ia_manifest_with_wrong_ontology_is_rejected(bundle, tmp_path):
    ia_table, ia_manifest = _ia_artifacts(bundle, tmp_path)
    data = json.loads(ia_manifest.read_text(encoding="utf-8"))
    data["ontology_sha256"] = "0" * 64
    ia_manifest.write_text(json.dumps(data), encoding="utf-8")
    alpha = _write_predictions(tmp_path / "alpha.tsv", 0.8)
    beta = _write_predictions(tmp_path / "beta.tsv", 0.6)
    command = [
        sys.executable,
        "-B",
        str(ROOT / "scripts/evaluation/compare_predictions.py"),
        "--dataset",
        str(bundle["dataset"]),
        "--run",
        str(bundle["run"]),
        "--ontology",
        str(bundle["ontology_path"]),
        "--benchmark-sha256",
        bundle["benchmark_sha256"],
        "--ia-table",
        str(ia_table),
        "--ia-manifest",
        str(ia_manifest),
        "--method",
        f"alpha={alpha}",
        "--method",
        f"beta={beta}",
        "--output-dir",
        str(tmp_path / "bad-comparison"),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "Unsupported IA manifest field" in result.stderr
    assert not (tmp_path / "bad-comparison").exists()


@pytest.mark.parametrize(
    ("step", "expected"),
    [("0.5", (0.5,)), ("0.25", (0.75, 0.5, 0.25))],
)
def test_cafa_threshold_grid_excludes_zero_and_one(step, expected):
    thresholds = runpy.run_path(
        str(ROOT / "scripts/evaluation/compare_predictions.py")
    )["_thresholds"]
    assert thresholds(step) == expected


def test_svg_has_deterministic_method_lines():
    chart = render_metric_svg(
        aspect="MF",
        metric="f1",
        series={
            "A": [{"threshold": 0.5, "f1": 0.3}],
            "B": [{"threshold": 0.5, "f1": 0.4}],
        },
        ylabel="F1",
        fixed_unit_range=True,
    )
    assert chart.count("<polyline") == 2
    assert chart.find("method") == -1
