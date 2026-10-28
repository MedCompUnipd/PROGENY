#!/usr/bin/env python3
"""Compute a START-corpus IA table against the pinned GO ontology."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

from progeny.information_accretion import (
    calculate_information_accretion,
    write_information_accretion,
)
from progeny.ontology import GeneOntology
from progeny.stage08_go_closure import GoClosureIndex

MINIMUM_FREE_BYTES = 10 * 1024**3


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _outside_repository(path: Path, repository: Path, *, must_exist: bool) -> Path:
    if must_exist:
        resolved = path.resolve(strict=True)
    else:
        resolved = path.parent.resolve(strict=True) / path.name
    try:
        resolved.relative_to(repository)
    except ValueError:
        return resolved
    raise ValueError("IA output and scratch paths must be outside the source checkout")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gaf", type=Path, required=True)
    parser.add_argument("--gaf-sha256", required=True)
    parser.add_argument("--source-role", choices=("START",), required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--ontology-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    args = parser.parse_args()

    repository = Path(__file__).resolve().parents[2]
    raw_gaf = args.gaf.absolute()
    raw_ontology = args.ontology.absolute()
    gaf_path = args.gaf.resolve(strict=True)
    ontology_path = args.ontology.resolve(strict=True)
    if raw_gaf != gaf_path or raw_ontology != ontology_path:
        raise ValueError("GAF and ontology paths must not contain symlinks")
    if not args.release_id or any(character.isspace() for character in args.release_id):
        raise ValueError("Release ID must be nonempty and contain no whitespace")
    scratch_root = _outside_repository(args.scratch_root, repository, must_exist=True)
    output_dir = _outside_repository(args.output_dir, repository, must_exist=False)
    if gaf_path.is_symlink() or not gaf_path.is_file():
        raise ValueError("GAF input must be a regular file")
    if ontology_path.is_symlink() or not ontology_path.is_file():
        raise ValueError("Ontology input must be a regular file")
    if not scratch_root.is_dir() or output_dir.exists():
        raise ValueError("Scratch root must exist and output directory must be new")
    if args.scratch_root.absolute() != scratch_root:
        raise ValueError("Scratch root must not contain symlink components")
    if args.output_dir.parent.absolute() != output_dir.parent:
        raise ValueError("Output parent must not contain symlink components")
    for protected in (gaf_path.parent, ontology_path.parent):
        try:
            scratch_root.relative_to(protected)
        except ValueError:
            continue
        raise ValueError("IA scratch must be outside source input directories")
    for protected in (gaf_path.parent, ontology_path.parent, scratch_root):
        try:
            output_dir.relative_to(protected)
        except ValueError:
            continue
        raise ValueError("IA output must be separate from sources and scratch")
    ontology_digest = _digest(ontology_path)
    if ontology_digest != args.ontology_sha256.lower():
        raise ValueError("Pinned ontology SHA-256 mismatch")
    ontology = GeneOntology.from_owl(ontology_path)
    graph = GoClosureIndex.from_gene_ontology(ontology)
    free_bytes = shutil.disk_usage(scratch_root).free
    minimum_required = max(
        20 * 1024**3,
        2 * gaf_path.stat().st_size + MINIMUM_FREE_BYTES,
    )
    if free_bytes < minimum_required:
        raise ValueError(
            "Insufficient scratch disk headroom for the streaming IA pass: "
            f"free={free_bytes}, required={minimum_required}"
        )

    def report_progress(message: str) -> None:
        remaining = shutil.disk_usage(scratch_root).free
        print(f"{message}\tSCRATCH_FREE_BYTES={remaining}", file=sys.stderr, flush=True)
        if remaining < MINIMUM_FREE_BYTES:
            raise RuntimeError("IA scratch free space fell below the 10 GiB reserve")

    with tempfile.TemporaryDirectory(
        prefix="progeny-ia-", dir=scratch_root
    ) as temporary:
        database = Path(temporary) / "information-accretion.sqlite"
        result = calculate_information_accretion(
            gaf_path=gaf_path,
            expected_gaf_sha256=args.gaf_sha256,
            ontology=ontology,
            graph=graph,
            scratch_database=database,
            ontology_sha256=ontology_digest,
            progress=report_progress,
        )
        result["source_role"] = args.source_role
        result["source_release_id"] = args.release_id
        result["gaf_path"] = str(gaf_path)
        output_dir.mkdir()
        write_information_accretion(
            result,
            tsv_path=output_dir / "information_accretion.tsv",
            manifest_path=output_dir / "manifest.json",
        )
    print(
        json.dumps(
            {
                "status": "COMPUTED",
                "source_role": args.source_role,
                "source_release_id": args.release_id,
                "gaf_sha256": result["gaf_sha256"],
                "ontology_sha256": ontology_digest,
                "ia_terms": len(result["term_values"]),
                "unique_direct_proteins": result["unique_direct_proteins"],
                "unique_direct_pairs": result["unique_direct_pairs"],
                "output_dir": str(output_dir),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
