#!/usr/bin/env python3
"""Inspect, run, resume or certify a prepared canonical V2 fresh execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from progeny.canonical_v2.fresh_control import (
    cleanup,
    execute,
    load,
    preflight,
    verify,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--deep", action="store_true")
    commands.add_parser("verify")
    commands.add_parser("cleanup")
    for action in ("first", "resume"):
        command = commands.add_parser(action)
        command.add_argument("--cores", type=int, required=True)
        command.add_argument("--memory-mb", type=int, required=True)
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--performance-profile", type=Path)
        if action == "resume":
            command.add_argument("--confirmed-stopped", action="store_true")
    arguments = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    recipe = load(arguments.recipe, repo)
    if arguments.action == "inspect":
        outcome = preflight(recipe, deep=arguments.deep)
    elif arguments.action == "verify":
        outcome = verify(recipe)
    elif arguments.action == "cleanup":
        outcome = cleanup(recipe)
    else:
        outcome = execute(
            recipe,
            mode=arguments.action,
            cores=arguments.cores,
            memory_mb=arguments.memory_mb,
            confirmed_stopped=getattr(arguments, "confirmed_stopped", False),
            dry_run=arguments.dry_run,
            performance_profile=arguments.performance_profile,
        )
    print(json.dumps(outcome, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
