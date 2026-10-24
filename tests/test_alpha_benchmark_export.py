"""Fixture-only tests: user IDs and HTML do not alter canonical publications."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from progeny.alpha_advanced import validate_advanced
from progeny.alpha_export import export_benchmark
from progeny.alpha_identity import preserve_headers

ROOT = Path(__file__).resolve().parents[1]


def _tsv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path):
    raw = tmp_path / "original.fasta"
    raw.write_text(
        ">T1 informative description\nACDEFGHIKLMNPQRSTVWY\n"
        ">T2 no benchmark hits\nAACDEFGHIKLMNPQRSTVW\n"
        ">T3 another description\nMNPQRSTVWYACDEFGHIKLM\n",
        encoding="ascii",
    )
    tagged = tmp_path / "with_taxid.fasta"
    tagged.write_text(
        ">T1\t111\nACDEFGHIKLMNPQRSTVWY\n"
        ">T2\t111\nAACDEFGHIKLMNPQRSTVW\n"
        ">T3\t111\nMNPQRSTVWYACDEFGHIKLM\n",
        encoding="ascii",
    )
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/pipeline/00_import_targets.py"),
            "--input",
            str(tagged),
            "--output-directory",
            str(dataset / "targets"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    preserve_headers(raw, dataset / "targets", dataset / "identity")
    run = tmp_path / "run"
    temporal = run / "canonical/v2-policy-test/temporal"
    temporal.mkdir(parents=True)
    (temporal.parent / "temporal.snakemake.done").write_text("complete")
    _tsv(
        temporal / "benchmark_terms.tsv",
        ("query_id", "aspect", "go_id", "status"),
        [
            ("T000000001", "F", "GO:0000001", "EVAL"),
            ("T000000001", "F", "GO:0000002", "SKIP"),
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
        [("T000000001", "F", 1, 1, 0, 0, 0, 0), ("T000000003", "F", 1, 0, 0, 0, 0, 0)],
    )
    _tsv(
        temporal / "temporal_events.tsv",
        ("query_id", "target_id", "aspect", "go_id", "event", "status"),
        [
            ("T000000001", "T000000001", "F", "GO:0000001", "CONFIRMATION", "EVAL"),
            ("T000000003", "T000000003", "F", "GO:0000003", "NOVEL", "EVAL"),
        ],
    )
    _tsv(
        temporal / "term_audit.tsv",
        ("query_id", "target_id", "aspect", "go_id", "status", "reason"),
        [("T000000001", "T000000001", "F", "GO:0000001", "EVAL", "NOVEL")],
    )
    _tsv(
        temporal / "negative_terms.tsv",
        ("query_id", "target_id", "aspect", "go_id", "reason"),
        [],
    )
    _tsv(
        temporal / "duplicate_targets.tsv",
        (
            "query_id",
            "canonical_target_id",
            "duplicate_target_id",
            "ncbi_taxid",
            "sequence_sha256",
        ),
        [],
    )
    _tsv(
        temporal.parent / "stage07/07_accepted_associations.tsv",
        ("release", "target_id", "annotation_donor"),
        [("2026_03", "T000000001", "YES"), ("2026_03", "T000000003", "YES")],
    )
    files = sorted(temporal.glob("*.tsv"))
    _json(
        temporal / "manifest.json",
        {
            "source_target_count": 3,
            "counts": {"benchmark_EVAL": 2, "benchmark_SKIP": 1},
            "outputs": {
                p.name: {"sha256": _sha(p), "bytes": p.stat().st_size} for p in files
            },
        },
    )
    _tsv(
        run / "work/pipeline-v2/START/02B/02B_target_taxonomy.tsv",
        ("target_id", "species_taxid"),
        [(f"T{i:09d}", "111") for i in range(1, 4)],
    )
    for role in ("START", "END"):
        _json(
            run / f"work/pipeline-v2/{role}/01A_FULL/01A_full_v2.summary.json",
            {
                "totals": {"records_seen": 100, "records_written": 95},
                "inputs": [
                    {"records_seen": 40, "records_written": 35},
                    {"records_seen": 60, "records_written": 60},
                ],
            },
        )
        _json(
            run / f"work/pipeline-v2/{role}/01B1/goa.stats.json",
            {"retained_annotation_count": 12},
        )
    return dataset, run


def test_export_with_original_headers_and_internal_audit(tmp_path):
    dataset, run = _fixture(tmp_path)
    temporal = next((run / "canonical").glob("*/temporal"))
    original = _sha(temporal / "benchmark_terms.tsv")
    out = export_benchmark(dataset, run)
    assert (
        (out / "ground_truth_targets.fasta")
        .read_text()
        .startswith(">T1 informative description\n")
    )
    fasta = (out / "ground_truth_targets.fasta").read_text()
    assert ">T3 another description\n" in fasta
    assert ">T2" not in fasta
    assert "T000000001" not in (out / "benchmark_terms.tsv").read_text()
    assert "T1\tF\tGO:0000001\tEVAL" in (out / "benchmark_terms.tsv").read_text()
    assert "T1\tF\tGO:0000002\tSKIP" in (out / "skip_terms.tsv").read_text()
    assert "T000000001" in (out / "target_identity_map.tsv").read_text()
    assert (
        "T2\tT000000002\tNO_EVAL_IN_ANY_ASPECT"
        in (out / "non_evaluable_targets.tsv").read_text()
    )
    assert "PROGENY ground-truth report" in (out / "report.html").read_text()
    assert export_benchmark(dataset, run) == out
    statistics = json.loads((out / "statistics.json").read_text())
    uni = statistics["release_statistics"]["START"]["uniprot_full"]
    assert uni["records_written"] == 95
    assert uni["sprot_records_written"] == 35
    assert uni["trembl_records_written"] == 60
    assert _sha(temporal / "benchmark_terms.tsv") == original
    assert (
        json.loads((out / "statistics.json").read_text())["aspects"]["F"][
            "evaluable_targets"
        ]
        == 2
    )


def test_export_fails_closed_if_header_ledger_tampered(tmp_path):
    dataset, run = _fixture(tmp_path)
    headers = dataset / "identity/original_headers.tsv"
    headers.write_text(headers.read_text().replace("T1", "FORGED"))
    with pytest.raises(ValueError, match="modified"):
        export_benchmark(dataset, run)
    assert not (run / "results/benchmark").exists()


def test_advanced_evidence_configuration(tmp_path):
    registry = ROOT / "config/stage08_evidence_registry.example.json"
    temporal = ROOT / "config/stage08_evidence_classes_v2.example.json"
    profile = tmp_path / "runtime.json"
    _json(
        profile,
        {
            "schema": "progeny-fresh-runtime-resources-v1",
            "m8_workers": 2,
            "temporal_workers": 4,
            "m8_mem_mb": 1024,
            "m10c_mem_mb": 2048,
            "temporal_mem_mb": 4096,
        },
    )
    config = tmp_path / "advanced.json"
    _json(
        config,
        {
            "schema": "progeny-guided-advanced-v1",
            "threads": 4,
            "performance_profile": str(profile),
            "temporal_policy": str(temporal),
            "checkpoint_rows": 128,
        },
    )
    overrides, policy, runtime = validate_advanced(
        config, registry=registry, base_cores=1
    )
    assert overrides == {"threads": 4, "checkpoint_rows": 128}
    assert policy == temporal and runtime == profile
    data = json.loads(config.read_text())
    data["threads"] = 1
    _json(config, data)
    with pytest.raises(ValueError, match="workers exceed"):
        validate_advanced(config, registry=registry, base_cores=1)
