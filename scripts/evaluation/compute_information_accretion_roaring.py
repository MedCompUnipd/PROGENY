#!/usr/bin/env python3
"""Compute START Information Accretion with the pinned native Roaring backend."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from progeny.evaluation_artifacts import ia_fingerprint
from progeny.information_accretion import write_information_accretion
from progeny.information_accretion_roaring import (
    calculate_information_accretion_roaring,
    digest_file,
)
from progeny.ontology import GeneOntology
from progeny.stage08_go_closure import GoClosureIndex


def external(path: Path, repository: Path, *, existing: bool) -> Path:
    resolved = (
        path.resolve(strict=True)
        if existing
        else (path.parent.resolve(strict=True) / path.name)
    )
    if path.absolute() != resolved or resolved.is_relative_to(repository):
        raise ValueError("Path must be outside checkout and without symlinks")
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gaf", type=Path, required=True)
    parser.add_argument("--gaf-sha256", required=True)
    parser.add_argument("--source-role", choices=("START",), required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--ontology-sha256", required=True)
    parser.add_argument("--native-binary", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--max-address-space-gib", type=int, default=128)
    args = parser.parse_args()
    args.gaf = args.gaf.absolute()
    args.ontology = args.ontology.absolute()
    repository = Path(__file__).resolve().parents[2]
    scratch = external(args.scratch_root, repository, existing=True)
    output = external(args.output_dir, repository, existing=False)
    if output.exists() or output.is_symlink() or not scratch.is_dir():
        raise ValueError("Output must be new and scratch must exist")
    if args.gaf.absolute() != args.gaf.resolve(strict=True):
        raise ValueError("GAF path must not contain symlinks")
    if args.ontology.absolute() != args.ontology.resolve(strict=True):
        raise ValueError("Ontology path must not contain symlinks")
    for protected in (args.gaf.parent, args.ontology.parent):
        if scratch.is_relative_to(protected) or output.is_relative_to(protected):
            raise ValueError("Scratch/output must be separate from input directories")
    if output.is_relative_to(scratch):
        raise ValueError("Output must be separate from scratch")
    if not args.release_id or any(c.isspace() for c in args.release_id):
        raise ValueError("Invalid release identifier")
    ontology_sha = digest_file(args.ontology)
    if ontology_sha != args.ontology_sha256.lower():
        raise ValueError("Pinned ontology SHA-256 mismatch")
    ontology = GeneOntology.from_owl(args.ontology)
    graph = GoClosureIndex.from_gene_ontology(ontology)
    implementation = [
        Path(__file__),
        repository / "src/progeny/evaluation_artifacts.py",
        repository / "src/progeny/information_accretion_roaring.py",
        repository / "src/progeny/information_accretion.py",
        repository / "src/progeny/ontology.py",
        repository / "src/progeny/stage08_go_closure.py",
    ]
    hashes = {str(p.relative_to(repository)): digest_file(p) for p in implementation}
    result = calculate_information_accretion_roaring(
        gaf_path=args.gaf,
        expected_gaf_sha256=args.gaf_sha256,
        ontology=ontology,
        graph=graph,
        scratch_root=scratch,
        ontology_sha256=ontology_sha,
        binary_path=args.native_binary,
        threads=args.threads,
        max_address_space_bytes=args.max_address_space_gib * 1024**3,
        progress=lambda message: print(message, file=sys.stderr, flush=True),
    )
    if digest_file(args.ontology) != ontology_sha:
        raise ValueError("Ontology changed during calculation")
    if hashes != {
        str(p.relative_to(repository)): digest_file(p) for p in implementation
    }:
        raise ValueError("Implementation changed during calculation")
    result.update(
        {
            "source_role": args.source_role,
            "source_release_id": args.release_id,
            "gaf_path": str(args.gaf),
            "implementation_sha256": hashes,
            "artifact_fingerprint": ia_fingerprint(
                {
                    "release_id": args.release_id,
                    "gaf_sha256": args.gaf_sha256.lower(),
                    "ontology_sha256": ontology_sha,
                }
            ),
        }
    )
    output.mkdir()
    write_information_accretion(
        result,
        tsv_path=output / "information_accretion.tsv",
        manifest_path=output / "manifest.json",
    )
    print(
        json.dumps(
            {
                "status": "COMPUTED",
                "output_dir": str(output),
                "ia_terms": len(result["term_values"]),
                "backend": result["backend"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
