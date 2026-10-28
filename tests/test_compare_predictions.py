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

from progeny.knowledge_cohorts import SCORE_EVIDENCE_CODES
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


def _cohort_artifacts(bundle, directory: Path) -> Path:
    benchmark = load_benchmark_inputs(**bundle)
    identity_path = bundle["run"] / "results/benchmark/target_identity_map.tsv"
    with identity_path.open(encoding="utf-8", newline="") as stream:
        identities = {
            row["original_id"]: row["internal_target_id"]
            for row in csv.DictReader(stream, delimiter="\t")
            if row["benchmark_status"] == "EVALUABLE"
        }
    directory.mkdir()
    table = directory / "knowledge_cohorts.tsv"
    rows = [
        (
            query,
            identities[query],
            aspect,
            "NK" if query == "T1" else "PK",
            benchmark.species[query],
            "" if query == "T1" else aspect,
        )
        for query, aspect in sorted(benchmark.eligible)
    ]
    with table.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "original_id",
                "internal_target_id",
                "aspect",
                "knowledge_class",
                "species_taxid",
                "direct_start_score_aspects",
            ]
        )
        writer.writerows(rows)
    digest = hashlib.sha256(table.read_bytes()).hexdigest()
    audit = directory / "direct_start_go_resolution_audit.tsv"
    audit.write_text(
        "original_id\tsource_go_id\tsource_aspect\tcanonical_go_id\t"
        "canonical_aspect\tresolution\taction\tevidence_code\trid\tassertion_id\t"
        "release_id\tinternal_target_id\tdonor_accession\tpolarity\t"
        "normalized_gaf_line\tgaf_relation\tgaf_qualifier\n",
        encoding="utf-8",
    )
    audit_digest = hashlib.sha256(audit.read_bytes()).hexdigest()
    class_counts = {}
    for row in rows:
        aspect, knowledge = row[2], row[3]
        key = f"{aspect}_{knowledge}"
        class_counts[key] = class_counts.get(key, 0) + 1
    class_counts = {
        f"{aspect}_{knowledge}": class_counts.get(f"{aspect}_{knowledge}", 0)
        for aspect in ("F", "P", "C")
        for knowledge in ("NK", "LK", "PK")
    }
    manifest = {
        "schema": "progeny-start-knowledge-cohorts-v1",
        "status": "PUBLISHED",
        "classification_policy": (
            "exact_target_positive_direct_START_SCORE_evidence_by_aspect_v1"
        ),
        "score_evidence_codes": sorted(SCORE_EVIDENCE_CODES),
        "not_policy": "NOT_excluded",
        "donor_policy": "donor_accession_must_equal_original_target_accession",
        "propagation_policy": "direct_source_GO_only_no_closure",
        "replacement_policy": (
            "accept_only_unambiguous_active_replacement_in_same_aspect"
        ),
        "benchmark_sha256": benchmark.provenance["benchmark_sha256"],
        "ontology_sha256": benchmark.provenance["ontology_sha256"],
        "temporal_manifest_sha256": benchmark.provenance["temporal_manifest_sha256"],
        "m10c_manifest_sha256": benchmark.provenance["m10c_manifest_sha256"],
        "start_release": "test-start",
        "start_gaf_sha256": "a" * 64,
        "eligible_targets": len(benchmark.target_ids),
        "eligible_target_aspects": len(benchmark.eligible),
        "class_counts_by_aspect": class_counts,
        "direct_evidence_rows_audited": 0,
        "direct_evidence_rows_kept": 0,
        "cross_aspect_replacements_excluded": 0,
        "unresolved_go_rows_excluded": 0,
        "unsupported_go_rows_excluded": 0,
        "evidence_counts_by_code": {},
        "artifacts": {
            table.name: {"bytes": table.stat().st_size, "sha256": digest},
            audit.name: {"bytes": audit.stat().st_size, "sha256": audit_digest},
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def _cli(bundle, ia_table, ia_manifest, output, methods, *extra):
    cohorts = _cohort_artifacts(bundle, output.parent / f"{output.name}-cohorts")
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
        "--cohorts",
        str(cohorts),
        "--aspect",
        "F",
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
    assert "filtered_predictions_alpha.tsv" in summary["artifact_sha256"]
    with (output / "curves.tsv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert {row["method_id"] for row in rows} == {"alpha", "beta"}
    assert {row["threshold"] for row in rows} == {"0.5"}
    plot = output / "plots" / "weighted_f1_F.svg"
    assert plot.is_file()
    assert plot.read_text(encoding="utf-8").count("<polyline") == 2
    assert (output / "plots" / "recall_F.svg").read_text(encoding="utf-8").count(
        "<polyline"
    ) == 2
    assert (output / "plots" / "f1_F.svg").read_text(encoding="utf-8").count(
        "<polyline"
    ) == 2
    assert (output / "plots" / "recall_F.svg").read_text(encoding="utf-8").count(
        "<circle"
    ) > 0
    assert len(summary["plots"]) == 12
    assert (output / "plots/precision_recall_F.svg").is_file()
    with (output / "filtered_predictions_alpha.tsv").open(
        encoding="utf-8", newline=""
    ) as stream:
        filtered = list(csv.DictReader(stream, delimiter="\t"))
    assert {row["protein_id"] for row in filtered} == {"T1", "T3"}
    assert {row["knowledge_status"] for row in filtered} == {"NK", "PK"}


def test_ia_manifest_with_wrong_ontology_is_rejected(bundle, tmp_path):
    ia_table, ia_manifest = _ia_artifacts(bundle, tmp_path)
    data = json.loads(ia_manifest.read_text(encoding="utf-8"))
    data["ontology_sha256"] = "0" * 64
    ia_manifest.write_text(json.dumps(data), encoding="utf-8")
    alpha = _write_predictions(tmp_path / "alpha.tsv", 0.8)
    beta = _write_predictions(tmp_path / "beta.tsv", 0.6)
    cohorts = _cohort_artifacts(bundle, tmp_path / "cohorts")
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
        "--cohorts",
        str(cohorts),
        "--aspect",
        "F",
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


def test_knowledge_filter_restricts_denominator_and_prediction_export(bundle, tmp_path):
    ia_table, ia_manifest = _ia_artifacts(bundle, tmp_path)
    alpha = _write_predictions(tmp_path / "alpha.tsv", 0.8)
    beta = _write_predictions(tmp_path / "beta.tsv", 0.6)
    output = tmp_path / "pk-comparison"
    result = _cli(
        bundle,
        ia_table,
        ia_manifest,
        output,
        (("alpha", alpha), ("beta", beta)),
        "--knowledge",
        "PK",
    )
    assert json.loads(result.stdout)["status"] == "EVALUATED"
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["knowledge_classes"] == ["PK"]
    assert summary["selected_target_aspects"] == 1
    with (output / "filtered_predictions_alpha.tsv").open(
        encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert {row["protein_id"] for row in rows} == {"T3"}


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
