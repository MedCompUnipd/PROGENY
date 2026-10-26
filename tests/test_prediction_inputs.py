"""Synthetic integration of certified collector inputs and prediction preparation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_alpha_benchmark_export import _json, _sha, _tsv
from test_alpha_scientific_publish import _ready

from progeny.alpha_scientific_publish import publish_scientific_benchmark
from progeny.prediction_inputs import load_benchmark_inputs

ROOT = Path(__file__).resolve().parents[1]


def _owl(path):
    obo = "http://purl.obolibrary.org/obo/"
    classes = []
    parents = {1: 2, 3: 3674, 4: 3674, 5: 3674, 6: 3674, 8: 4, 10: 8150}
    for number in (1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 3674, 8150, 5575):
        namespace = (
            "biological_process"
            if number in {10, 8150}
            else "cellular_component"
            if number == 5575
            else "molecular_function"
        )
        label = (
            f"obsolete term {number}" if number in {11, 12, 13} else f"term {number}"
        )
        content = [
            f"<owl:Class rdf:about='{obo}GO_{number:07d}'>",
            f"<rdfs:label>{label}</rdfs:label>",
            f"<oboInOwl:hasOBONamespace>{namespace}</oboInOwl:hasOBONamespace>",
        ]
        if number in parents:
            parent = parents[number]
            content.append(f"<rdfs:subClassOf rdf:resource='{obo}GO_{parent:07d}'/>")
        if number == 2:
            content.append(
                "<rdfs:subClassOf><owl:Restriction>"
                f"<owl:onProperty rdf:resource='{obo}BFO_0000050'/>"
                f"<owl:someValuesFrom rdf:resource='{obo}GO_0000008'/>"
                "</owl:Restriction></rdfs:subClassOf>"
            )
        if number == 1:
            content.append(
                f"<rdfs:subClassOf rdf:resource='{obo}GO_0000010'/>"
                "<rdfs:subClassOf><owl:Restriction>"
                f"<owl:onProperty rdf:resource='{obo}RO_0002211'/>"
                f"<owl:someValuesFrom rdf:resource='{obo}GO_0000005'/>"
                "</owl:Restriction></rdfs:subClassOf>"
            )
        if number == 6:
            content.append(
                "<oboInOwl:hasAlternativeId>GO:0000009</oboInOwl:hasAlternativeId>"
            )
        if number == 7:
            content.append(
                "<owl:deprecated rdf:datatype='http://www.w3.org/2001/"
                "XMLSchema#boolean'>true</owl:deprecated>"
                f"<obo:IAO_0100001 rdf:resource='{obo}GO_0000006'/>"
            )
        if number == 12:
            content.append("<oboInOwl:consider>GO:0000006</oboInOwl:consider>")
        if number == 13:
            for replacement in (5, 6):
                content.append(
                    f"<obo:IAO_0100001 rdf:resource='{obo}GO_{replacement:07d}'/>"
                )
        classes.append("".join([*content, "</owl:Class>"]))
    path.write_text(
        "<?xml version='1.0'?>"
        "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#' "
        "xmlns:rdfs='http://www.w3.org/2000/01/rdf-schema#' "
        "xmlns:owl='http://www.w3.org/2002/07/owl#' "
        f"xmlns:obo='{obo}' "
        "xmlns:oboInOwl='http://www.geneontology.org/formats/oboInOwl#'>"
        "<owl:Ontology rdf:about='http://purl.obolibrary.org/obo/go.owl'>"
        "<owl:versionIRI rdf:resource='http://purl.obolibrary.org/obo/go/"
        "releases/2026-03-01/go.owl'/></owl:Ontology>"
        + "".join(classes)
        + "</rdf:RDF>",
        encoding="utf-8",
    )


@pytest.fixture
def bundle(tmp_path):
    dataset, run, temporal = _ready(tmp_path)
    owl = tmp_path / "synthetic.owl"
    _owl(owl)
    with (temporal / "benchmark_terms.tsv").open("a") as stream:
        stream.write("T000000001\tF\tGO:0000004\tEVAL\n")
    with (temporal / "term_audit.tsv").open("a") as stream:
        stream.write("T000000001\tT000000001\tF\tGO:0000004\tEVAL\tNOVEL\n")
    _tsv(
        temporal / "target_aspects.tsv",
        (
            "query_id",
            "aspect",
            "eval_terms",
            "skip_terms",
            "neutral_terms",
            "negative_terms",
            "known_start_score",
            "known_start_non_score",
        ),
        [("T000000001", "F", 2, 1, 1, 0, 0, 0), ("T000000003", "F", 1, 0, 0, 0, 0, 0)],
    )
    temporal_data = json.loads((temporal / "manifest.json").read_text())
    temporal_data.update(
        schema_version="stage08-temporal-eval-skip-neutral-v3",
        ontology_sha256=_sha(owl),
        class_fingerprint="b" * 64,
        registry_fingerprint="c" * 64,
        policy_sha256="d" * 64,
    )
    temporal_data["counts"]["benchmark_EVAL"] = 3
    temporal_data["outputs"] = {
        path.name: {"sha256": _sha(path), "bytes": path.stat().st_size}
        for path in temporal.glob("*.tsv")
    }
    _json(temporal / "manifest.json", temporal_data)
    _json(
        temporal.parent / "m10c/manifest.json",
        {
            "schema_version": "stage08-m10c-compact-interpretation-v1",
            "ontology_sha256": _sha(owl),
            "graph_terms": 11,
            "graph_edges": 8,
            "not_policy": "preserved_no_veto",
        },
    )
    publication = publish_scientific_benchmark(dataset, run)
    return {
        "dataset": dataset,
        "run": run,
        "ontology_path": owl,
        "benchmark_sha256": _sha(publication / "manifest.json"),
    }


def _repin(bundle, path):
    manifest_path = bundle["run"] / "results/benchmark/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for item in manifest["inputs"].values():
        if item["path"] == str(path):
            item.update(sha256=_sha(path), bytes=path.stat().st_size)
    if path.parent == manifest_path.parent:
        manifest["outputs"][path.name].update(
            sha256=_sha(path), bytes=path.stat().st_size
        )
    _json(manifest_path, manifest)
    bundle["benchmark_sha256"] = _sha(manifest_path)


def test_certified_bundle_preserves_full_denominator_without_predictions(bundle):
    inputs = load_benchmark_inputs(**bundle)
    assert inputs.target_ids == frozenset({"T1", "T3"})
    assert inputs.eligible == frozenset({("T1", "F"), ("T3", "F")})
    assert inputs.truth == {
        ("T1", "F"): frozenset({"GO:0000001", "GO:0000004"}),
        ("T3", "F"): frozenset({"GO:0000003"}),
    }
    # The existing OWL relation policy excludes the cross-aspect edge first.
    assert inputs.graph.ignored_cross_aspect_edges == 0
    assert "GO:0000010" not in inputs.graph.ancestors("GO:0000001")
    assert inputs.provenance["metrics_status"] == "NOT_COMPUTED"


def test_real_projection_part_of_masks_regulates_and_original_ids(bundle, tmp_path):
    inputs = load_benchmark_inputs(**bundle)
    predictions = tmp_path / "predictions.tsv"
    predictions.write_text("query_id\tgo_id\tscore\nT1\tGO:0000001\t0.8\n")
    result = inputs.prepare(predictions)
    assert result.scores == {
        ("T1", "F", "GO:0000001"): 0.8,
        ("T1", "F", "GO:0000004"): 0.8,
    }
    assert result.counts["skip_pairs_excluded"] == 1
    assert result.counts["neutral_pairs_excluded"] == 1
    assert ("T1", "F", "GO:0000005") not in result.scores
    assert ("T1", "P", "GO:0000010") not in result.scores


def test_real_alias_and_obsolete_resolution(bundle, tmp_path):
    inputs = load_benchmark_inputs(**bundle)
    predictions = tmp_path / "predictions.tsv"
    predictions.write_text(
        "query_id\tgo_id\tscore\nT1\tGO:0000009\t0.6\nT1\tGO:0000007\t0.9\n"
    )
    result = inputs.prepare(predictions)
    assert result.scores == {("T1", "F", "GO:0000006"): 0.9}
    assert result.counts["remapped_rows"] == 2
    assert result.counts["duplicate_rows_after_resolution"] == 1
    assert all(row["action"] == "REMAPPED" for row in result.go_audit)


def test_mixed_ontology_submission_excludes_only_unresolvable_go(bundle, tmp_path):
    inputs = load_benchmark_inputs(**bundle)
    predictions = tmp_path / "mixed_ontologies.tsv"
    predictions.write_text(
        "query_id\tgo_id\tscore\n"
        "T1\tGO:0000001\t0.8\n"
        "T1\tGO:0000009\t0.6\n"
        "T1\tGO:0000007\t0.9\n"
        "T1\tGO:0000011\t0.9\n"
        "T1\tGO:0000012\t0.9\n"
        "T1\tGO:0000013\t0.9\n"
        "T1\tGO:9999999\t0.99\n"
    )
    result = inputs.prepare(predictions)
    assert result.scores == {
        ("T1", "F", "GO:0000001"): 0.8,
        ("T1", "F", "GO:0000004"): 0.8,
        ("T1", "F", "GO:0000006"): 0.9,
    }
    assert result.counts["submitted_rows"] == 7
    assert result.counts["accepted_rows"] == 3
    assert result.counts["unresolved_rows_excluded"] == 4
    assert result.counts["remapped_rows"] == 2
    assert len(result.go_audit) == 6
    excluded = {
        row["submitted_go_id"]: row
        for row in result.go_audit
        if row["action"] == "EXCLUDED"
    }
    assert excluded["GO:0000012"]["candidate_go_ids"] == ["GO:0000006"]
    assert excluded["GO:0000013"]["candidate_go_ids"] == ["GO:0000005", "GO:0000006"]
    assert excluded["GO:9999999"]["ontology_status"] == "unknown"


def test_all_unresolvable_rows_do_not_remove_eligible_targets(bundle, tmp_path):
    inputs = load_benchmark_inputs(**bundle)
    predictions = tmp_path / "unresolvable.tsv"
    predictions.write_text("query_id\tgo_id\tscore\nT1\tGO:9999999\t0.9\n")
    before_truth = dict(inputs.truth)
    before_population = inputs.eligible
    result = inputs.prepare(predictions)
    assert result.scores == {}
    assert inputs.truth == before_truth
    assert inputs.eligible == before_population
    assert len(inputs.eligible) == 2


def test_wrong_expected_digest_fails(bundle):
    bundle["benchmark_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Benchmark digest"):
        load_benchmark_inputs(**bundle)


def test_wrong_ontology_bytes_fail_before_loading(bundle):
    with bundle["ontology_path"].open("a") as stream:
        stream.write("<!-- modified -->")
    with pytest.raises(ValueError, match="ontology digest"):
        load_benchmark_inputs(**bundle)


def test_wrong_m10c_projection_fails_even_with_reconciled_checksums(bundle):
    path = next((bundle["run"] / "canonical").glob("*/m10c/manifest.json"))
    value = json.loads(path.read_text())
    value["graph_edges"] += 1
    _json(path, value)
    _repin(bundle, path)
    with pytest.raises(ValueError, match="projection differs"):
        load_benchmark_inputs(**bundle)


def test_unknown_temporal_schema_fails(bundle):
    path = next((bundle["run"] / "canonical").glob("*/temporal/manifest.json"))
    value = json.loads(path.read_text())
    value["schema_version"] = "unsupported-schema"
    _json(path, value)
    _repin(bundle, path)
    with pytest.raises(ValueError, match="Temporal schema"):
        load_benchmark_inputs(**bundle)


def test_non_temporal_receipt_tamper_fails(bundle):
    path = next((bundle["run"] / "canonical").glob("*/m8.snakemake.done"))
    path.write_text("tampered")
    with pytest.raises(ValueError, match="receipt checksum"):
        load_benchmark_inputs(**bundle)


def test_extra_benchmark_file_fails(bundle):
    path = bundle["run"] / "results/benchmark/unrecorded.txt"
    path.write_text("unrecorded")
    with pytest.raises(ValueError, match="output inventory"):
        load_benchmark_inputs(**bundle)


def test_incomplete_mask_fails_even_with_reconciled_checksums(bundle):
    path = bundle["run"] / "results/benchmark/skip_terms.tsv"
    _tsv(path, ("query_id", "aspect", "go_id", "status"), [])
    _repin(bundle, path)
    with pytest.raises(ValueError, match="Incomplete convenience mask"):
        load_benchmark_inputs(**bundle)


def test_conflicting_status_fails_even_with_reconciled_checksums(bundle):
    path = bundle["run"] / "results/benchmark/benchmark_terms.tsv"
    with path.open("a") as stream:
        stream.write("T1\tF\tGO:0000001\tSKIP\n")
    _repin(bundle, path)
    with pytest.raises(ValueError, match="benchmark term"):
        load_benchmark_inputs(**bundle)


def test_foreign_dataset_fails(bundle, tmp_path):
    foreign = tmp_path / "foreign_dataset"
    foreign.mkdir()
    bundle["dataset"] = foreign
    with pytest.raises(ValueError, match="Foreign benchmark input"):
        load_benchmark_inputs(**bundle)


def test_validation_reads_only(bundle, tmp_path):
    def snapshot():
        return {str(path): _sha(path) for path in tmp_path.rglob("*") if path.is_file()}

    before = snapshot()
    load_benchmark_inputs(**bundle)
    assert snapshot() == before


def test_cli_without_predictions_is_read_only_and_computes_no_metrics(bundle):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/evaluation/validate_prediction_inputs.py"),
            "--dataset",
            str(bundle["dataset"]),
            "--run",
            str(bundle["run"]),
            "--ontology",
            str(bundle["ontology_path"]),
            "--benchmark-sha256",
            bundle["benchmark_sha256"],
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    audit = json.loads(result.stdout)
    assert audit["status"] == "VALIDATED"
    assert audit["metrics_status"] == "NOT_COMPUTED"
    assert "prediction_preparation" not in audit
