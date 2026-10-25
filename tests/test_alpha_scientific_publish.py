"""Scientific collector uses immutable canonical receipts and original IDs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from test_alpha_benchmark_export import _fixture, _json, _sha, _tsv

from progeny.alpha_scientific_publish import publish_scientific_benchmark


def _ready(tmp_path: Path):
    dataset, run = _fixture(tmp_path)
    temporal = next((run / "canonical").glob("*/temporal"))
    _tsv(
        temporal / "benchmark_terms.tsv",
        ("query_id", "aspect", "go_id", "status"),
        [
            ("T000000001", "F", "GO:0000001", "EVAL"),
            ("T000000001", "F", "GO:0000002", "SKIP"),
            ("T000000001", "F", "GO:0000008", "NEUTRAL"),
            ("T000000003", "F", "GO:0000003", "EVAL"),
        ],
    )
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
        [
            ("T000000001", "F", 1, 1, 1, 0, 0, 0),
            ("T000000003", "F", 1, 0, 0, 0, 0, 0),
        ],
    )
    _tsv(
        temporal / "term_audit.tsv",
        ("query_id", "target_id", "aspect", "go_id", "status", "reason"),
        [
            ("T000000001", "T000000001", "F", "GO:0000001", "EVAL", "NOVEL"),
            (
                "T000000001",
                "T000000001",
                "F",
                "GO:0000008",
                "NEUTRAL",
                "CONFLICT_SCORE_END",
            ),
            ("T000000003", "T000000003", "F", "GO:0000003", "EVAL", "CONFIRMATION"),
        ],
    )
    _tsv(
        temporal / "temporal_events.tsv",
        ("query_id", "target_id", "aspect", "go_id", "event", "status"),
        [
            ("T000000001", "T000000001", "F", "GO:0000001", "NOVEL", "EVAL"),
            ("T000000003", "T000000003", "F", "GO:0000003", "CONFIRMATION", "EVAL"),
        ],
    )
    files = sorted(temporal.glob("*.tsv"))
    _json(
        temporal / "manifest.json",
        {
            "source_target_count": 3,
            "counts": {
                "benchmark_EVAL": 2,
                "benchmark_SKIP": 1,
                "benchmark_NEUTRAL": 1,
                "eligible_target_aspects": 2,
            },
            "outputs": {
                p.name: {"sha256": _sha(p), "bytes": p.stat().st_size} for p in files
            },
        },
    )
    certificate = run / "verification" / ("a" * 64 + ".json")
    _json(
        certificate,
        {
            "schema": "progeny-canonical-v2-fresh-completion-v1",
            "status": "PASS",
            "canonical_publications": 16,
            "content_identity_sha256": "a" * 64,
            "receipts": {
                **{f"item-{i}": {} for i in range(15)},
                "temporal:COMMON": {
                    "path": str(temporal.parent / "temporal.snakemake.done"),
                    "sha256": _sha(temporal.parent / "temporal.snakemake.done"),
                },
            },
        },
    )
    return dataset, run, temporal


def test_publish_evals_and_masks_with_full_original_headers(tmp_path):
    dataset, run, temporal = _ready(tmp_path)
    before = _sha(temporal / "benchmark_terms.tsv")
    result = publish_scientific_benchmark(dataset, run)
    assert result == run / "results/benchmark"
    assert result.is_dir()
    assert publish_scientific_benchmark(dataset, run) == result
    assert _sha(temporal / "benchmark_terms.tsv") == before
    assert (
        ">T1 informative description\n"
        in (result / "ground_truth_targets.fasta").read_text()
    )
    assert ">T2" not in (result / "ground_truth_targets.fasta").read_text()
    assert "T1\tF\tGO:0000008\tNEUTRAL" in (result / "benchmark_terms.tsv").read_text()
    assert "T1\tF\tGO:0000008\tNEUTRAL" in (result / "neutral_terms.tsv").read_text()
    assert (
        "T2\tT000000002\tNO_EVAL_IN_ANY_ASPECT"
        in (result / "non_evaluable_targets.tsv").read_text()
    )
    overview = json.loads((result / "statistics.json").read_text())["overview"]
    assert overview == {
        "input_targets": 3,
        "evaluable_targets": 2,
        "target_aspects": 2,
        "EVAL": 2,
        "SKIP": 1,
        "NEUTRAL": 1,
        "NOVEL": 1,
        "CONFIRMATION": 1,
        "direct_end_eval": 2,
    }
    with (result / "target_cohorts.tsv").open(newline="") as handle:
        cohorts = list(csv.DictReader(handle, delimiter="\t"))
    assert len(cohorts) == 2
    assert all(c["knowledge_class"] == "UNCLASSIFIED" for c in cohorts)
    assert cohorts[0]["neutral_terms"] == "1"
    with (result / "species_statistics.tsv").open(newline="") as handle:
        species = list(csv.DictReader(handle, delimiter="\t"))
    mf = next(x for x in species if x["species_taxid"] == "111" and x["aspect"] == "F")
    assert mf["evaluable_targets"] == "2"
    assert mf["eval"] == "2"
    assert json.loads((result / "manifest.json").read_text())["status"] == "PUBLISHED"


def test_missing_completion_certificate_blocks_publication(tmp_path):
    dataset, run, _ = _ready(tmp_path)
    for path in (run / "verification").glob("*.json"):
        path.unlink()
    with pytest.raises(ValueError, match="certified"):
        publish_scientific_benchmark(dataset, run)
    assert not (run / "results/benchmark").exists()


def test_tampered_temporal_file_fails_without_partial_publication(tmp_path):
    dataset, run, temporal = _ready(tmp_path)
    with (temporal / "benchmark_terms.tsv").open("a") as output:
        output.write("T000000001\tF\tGO:9999999\tEVAL\n")
    with pytest.raises(ValueError, match="checksum"):
        publish_scientific_benchmark(dataset, run)
    assert not (run / "results/benchmark").exists()


def test_existing_publication_tamper_refused(tmp_path):
    dataset, run, _ = _ready(tmp_path)
    result = publish_scientific_benchmark(dataset, run)
    (result / "neutral_terms.tsv").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        publish_scientific_benchmark(dataset, run)
