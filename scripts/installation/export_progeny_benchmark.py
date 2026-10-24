#!/usr/bin/env python3
"""Publish the user-facing benchmark, original FASTA IDs and HTML report."""

from __future__ import annotations

import argparse
from pathlib import Path

from progeny.alpha_export import export_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    published = export_benchmark(args.dataset, args.run)
    print(f"PROGENY_BENCHMARK_EXPORT=PASS\nOUTPUT={published}")


if __name__ == "__main__":
    main()
