#!/usr/bin/env python3
"""Validate certified benchmark inputs and optionally prepare prediction scores.

Prints a JSON audit to stdout. Does not publish files or compute metrics.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from progeny.alpha_identity import _sha
from progeny.prediction_contract import PREPARATION_SCHEMA
from progeny.prediction_inputs import load_benchmark_inputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--benchmark-sha256", required=True)
    parser.add_argument("--predictions", type=Path)
    args = parser.parse_args()
    benchmark = load_benchmark_inputs(
        dataset=args.dataset,
        run=args.run,
        ontology_path=args.ontology,
        benchmark_sha256=args.benchmark_sha256,
    )
    audit = dict(benchmark.provenance)
    if args.predictions is not None:
        before = _sha(args.predictions)
        prepared = benchmark.prepare(args.predictions)
        if _sha(args.predictions) != before:
            raise ValueError("Predictions changed during validation")
        audit["prediction_preparation"] = {
            "schema": PREPARATION_SCHEMA,
            "path": str(args.predictions.absolute()),
            "sha256": before,
            "counts": prepared.counts,
            "go_resolution_audit": prepared.go_audit,
        }
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
