#!/usr/bin/env python3
"""Publish the immutable user-facing PROGENY benchmark after science PASS."""

from __future__ import annotations

import argparse
from pathlib import Path

from progeny.alpha_scientific_publish import publish_scientific_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    result = publish_scientific_benchmark(args.dataset, args.run)
    print("SCIENTIFIC_PIPELINE=PASS")
    print("BENCHMARK_PUBLICATION=PASS")
    print(f"BENCHMARK_DIRECTORY={result}")
    print(f"BENCHMARK_FASTA={result / 'ground_truth_targets.fasta'}")
    print(f"BENCHMARK_ANNOTATIONS={result / 'benchmark_terms.tsv'}")
    print(f"BENCHMARK_COHORTS={result / 'target_cohorts.tsv'}")
    print(f"BENCHMARK_REPORT={result / 'report.html'}")


if __name__ == "__main__":
    main()
