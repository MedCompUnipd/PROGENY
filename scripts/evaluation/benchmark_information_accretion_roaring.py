#!/usr/bin/env python3
"""Compare SQLite and Roaring exactly on a bounded prefix of one GAF snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from progeny.information_accretion import (
    calculate_information_accretion,
    write_information_accretion,
)
from progeny.information_accretion_roaring import (
    calculate_information_accretion_roaring,
    digest_file,
)
from progeny.ontology import GeneOntology
from progeny.stage08_go_closure import GoClosureIndex


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gaf", type=Path, required=True)
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--ontology-sha256", required=True)
    parser.add_argument("--native-binary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-data-rows", type=int, default=100_000)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--max-address-space-gib", type=int, default=4)
    args = parser.parse_args()
    args.gaf = args.gaf.absolute()
    args.ontology = args.ontology.absolute()
    repository = Path(__file__).resolve().parents[2]
    output = args.output_dir.absolute()
    if output.exists() or output.is_symlink() or output.is_relative_to(repository):
        raise ValueError("Benchmark output must be new and outside checkout")
    if output.parent.resolve(strict=True) != output.parent:
        raise ValueError("Output parent must exist and contain no symlinks")
    if not 1 <= args.max_data_rows <= 1_000_000:
        raise ValueError("Prefix benchmark is limited to 1 through 1,000,000 rows")
    for source in (args.gaf, args.ontology):
        if source.absolute() != source.resolve(strict=True) or not source.is_file():
            raise ValueError("Input must be a regular file without symlinks")
        if output.is_relative_to(source.parent):
            raise ValueError("Output must be separate from input directories")
    ontology_sha = digest_file(args.ontology)
    if ontology_sha != args.ontology_sha256.lower():
        raise ValueError("Ontology SHA-256 mismatch")
    initial = args.gaf.stat()
    output.mkdir()
    prefix = output / "prefix.gaf"
    digest = hashlib.sha256()
    rows = 0
    with args.gaf.open("rb") as source, prefix.open("xb") as target:
        for line in source:
            target.write(line)
            digest.update(line)
            if not line.startswith(b"!") and line.strip():
                rows += 1
                if rows >= args.max_data_rows:
                    break
    final = args.gaf.stat()
    if (initial.st_dev, initial.st_ino, initial.st_size, initial.st_mtime_ns) != (
        final.st_dev,
        final.st_ino,
        final.st_size,
        final.st_mtime_ns,
    ):
        raise ValueError("Source GAF changed while copying the prefix")
    ontology = GeneOntology.from_owl(args.ontology)
    graph = GoClosureIndex.from_gene_ontology(ontology)
    arguments = dict(
        gaf_path=prefix,
        expected_gaf_sha256=digest.hexdigest(),
        ontology=ontology,
        graph=graph,
        ontology_sha256=ontology_sha,
    )
    started = time.monotonic()
    reference = calculate_information_accretion(
        **arguments, scratch_database=output / "reference.sqlite"
    )
    sqlite_seconds = time.monotonic() - started
    started = time.monotonic()
    native = calculate_information_accretion_roaring(
        **arguments,
        scratch_root=output,
        binary_path=args.native_binary,
        threads=args.threads,
        max_address_space_bytes=args.max_address_space_gib * 1024**3,
    )
    roaring_seconds = time.monotonic() - started
    scientific = {key: value for key, value in native.items() if key != "backend"}
    if scientific != reference:
        differing = sorted(
            key
            for key in set(reference) | set(scientific)
            if reference.get(key) != scientific.get(key)
        )
        raise ValueError(f"SQLite/Roaring scientific mismatch: {differing}")
    for name, result in (("sqlite", reference), ("roaring", native)):
        write_information_accretion(
            result,
            tsv_path=output / f"{name}.tsv",
            manifest_path=output / f"{name}.json",
        )
    if (output / "sqlite.tsv").read_bytes() != (output / "roaring.tsv").read_bytes():
        raise ValueError("SQLite/Roaring IA tables are not byte-identical")
    if digest_file(args.ontology) != ontology_sha:
        raise ValueError("Ontology changed during benchmark")
    report = {
        "schema": "progeny-ia-roaring-prefix-equivalence-v1",
        "status": "PASS",
        "data_rows": rows,
        "source_gaf_path": str(args.gaf),
        "source_gaf_bytes": initial.st_size,
        "source_full_sha256_status": "NOT_REVERIFIED_FOR_PREFIX_BENCHMARK",
        "prefix_sha256": digest.hexdigest(),
        "ontology_sha256": ontology_sha,
        "sqlite_seconds": sqlite_seconds,
        "roaring_seconds": roaring_seconds,
        "speedup": sqlite_seconds / roaring_seconds,
        "execution_order": ["sqlite", "roaring"],
        "cache_policy": "filesystem_cache_not_flushed",
        "ia_table_sha256": digest_file(output / "sqlite.tsv"),
        "native_backend": native["backend"],
        "scope": "prefix_only_not_a_full_corpus_performance_estimate",
    }
    (output / "equivalence.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
