#!/usr/bin/env python3
"""Draw isolated PR and RU-MI SVG panels from an existing PROGENY curves.tsv."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from progeny.publication_curves import write_panels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curves", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--include-weighted", action="store_true")
    args = parser.parse_args()
    report = write_panels(
        args.curves, args.output_dir, include_weighted=args.include_weighted
    )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
