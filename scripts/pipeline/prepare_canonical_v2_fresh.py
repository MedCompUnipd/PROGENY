#!/usr/bin/env python3
"""Prepare controls for a virgin canonical V2 fresh run, without running it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from progeny.canonical_v2.fresh_preparation import prepare


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--hash-biological-inputs", action="store_true")
    args = parser.parse_args()
    result = prepare(
        repo=args.repo,
        run=args.run,
        spec_path=args.spec,
        hash_biological_inputs=args.hash_biological_inputs,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
