#!/usr/bin/env python3
"""Evaluate one prediction TSV against the certified PROGENY benchmark.

Prints a JSON report to stdout. Reads external inputs without publishing or
modifying any file. Fmax is computed; Smin requires a later certified IA input.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
from importlib.metadata import version
from pathlib import Path

from progeny.alpha_identity import _sha
from progeny.prediction_inputs import load_benchmark_inputs
from progeny.prediction_metrics import evaluate_scores, threshold_grid

SCHEMA = "progeny-prediction-evaluation-v1"


def _implementation(repo: Path) -> dict:
    paths = (
        "scripts/evaluation/evaluate_predictions.py",
        "src/progeny/prediction_metrics.py",
        "src/progeny/prediction_contract.py",
        "src/progeny/prediction_inputs.py",
        "src/progeny/ontology.py",
        "src/progeny/parsing/owl.py",
        "src/progeny/relations.py",
        "src/progeny/stage08_go_closure.py",
    )
    return {name: _sha(repo / name) for name in paths}


def _git_head(repo: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--benchmark-sha256", required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--method-id", required=True)
    parser.add_argument("--method-metadata", type=Path)
    parser.add_argument("--aspect", choices=("F", "P", "C"), action="append")
    parser.add_argument("--taxid", action="append")
    parser.add_argument("--threshold-step")
    parser.add_argument("--include-curves", action="store_true")
    args = parser.parse_args()
    if not args.method_id or any(value.isspace() for value in args.method_id):
        parser.error("method-id must be nonempty and contain no whitespace")
    grid = (
        threshold_grid(args.threshold_step) if args.threshold_step is not None else None
    )
    repo = Path(__file__).resolve().parents[2]
    implementation = _implementation(repo)
    method_metadata = None
    metadata_digest = None
    if args.method_metadata is not None:
        if args.method_metadata.is_symlink() or not args.method_metadata.is_file():
            raise ValueError("Method metadata must be a regular non-symlink file")
        metadata_digest = _sha(args.method_metadata)
        method_metadata = json.loads(args.method_metadata.read_text(encoding="utf-8"))
        if not isinstance(method_metadata, dict):
            raise ValueError("Method metadata must be a JSON object")
    benchmark = load_benchmark_inputs(
        dataset=args.dataset,
        run=args.run,
        ontology_path=args.ontology,
        benchmark_sha256=args.benchmark_sha256,
    )
    prediction_digest = _sha(args.predictions)
    prepared = benchmark.prepare(args.predictions)
    metrics = evaluate_scores(
        eligible=benchmark.eligible,
        truth=benchmark.truth,
        scores=prepared.scores,
        species=benchmark.species,
        aspects=tuple(args.aspect) if args.aspect is not None else ("F", "P", "C"),
        taxids=frozenset(args.taxid) if args.taxid is not None else None,
        thresholds=grid,
    )
    if not args.include_curves:
        for report in metrics["aspects"].values():
            del report["curve"]
    if _sha(args.predictions) != prediction_digest:
        raise ValueError("Predictions changed during evaluation")
    if _implementation(repo) != implementation:
        raise ValueError("Implementation changed during evaluation")
    if metadata_digest is not None and _sha(args.method_metadata) != metadata_digest:
        raise ValueError("Method metadata changed during evaluation")
    if _sha(args.run / "results/benchmark/manifest.json") != args.benchmark_sha256:
        raise ValueError("Benchmark manifest changed during evaluation")
    if _sha(args.ontology) != benchmark.provenance["ontology_sha256"]:
        raise ValueError("Pinned ontology changed during evaluation")
    source_identity = {
        name: value
        for name, value in benchmark.provenance.items()
        if name not in {"schema", "status", "metrics_status"}
    }
    report = {
        "schema": SCHEMA,
        "status": metrics["status"],
        "method_id": args.method_id,
        "method_metadata": method_metadata,
        "method_metadata_sha256": metadata_digest,
        "method_metadata_status": (
            "CALLER_DECLARED" if method_metadata is not None else "NOT_PROVIDED"
        ),
        "input_validation_schema": benchmark.provenance["schema"],
        "source_identity": source_identity,
        "predictions": {
            "path": str(args.predictions.absolute()),
            "sha256": prediction_digest,
            "preparation_scope": "full_evaluable_fasta_before_metric_filters",
            "preparation_counts": prepared.counts,
            "go_resolution_audit": prepared.go_audit,
        },
        "threshold_grid_step": args.threshold_step,
        "curves_included": args.include_curves,
        "metrics": metrics,
        "implementation_sha256": implementation,
        "source_git_head": _git_head(repo),
        "python_version": platform.python_version(),
        "rdflib_version": version("rdflib"),
    }
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
