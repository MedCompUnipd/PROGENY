#!/usr/bin/env python3
"""Import strict tab-delimited source FASTA into PROGENY canonical target inputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "progeny-target-import-v2"
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*\Z", re.ASCII)
TAXID = re.compile(r"[1-9][0-9]*\Z", re.ASCII)
UNIPROT = re.compile(
    r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]"
    r"|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})\Z",
    re.ASCII,
)


@dataclass(frozen=True, slots=True)
class Record:
    number: int
    header_line: int
    source_id: str
    taxid: str
    sequence: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_header(header: str, path: Path, line_number: int) -> tuple[str, str]:
    fields = header.split("\t")
    if len(fields) != 2:
        raise ValueError(
            f"{path}:{line_number}: header requires exactly one TAB: "
            ">SOURCE_ID<TAB>NCBI_TAXID"
        )
    source_id, taxid = fields
    if IDENTIFIER.fullmatch(source_id) is None:
        raise ValueError(
            f"{path}:{line_number}: invalid source ID {source_id!r}; "
            "use ASCII letters, digits, underscore, dot, colon or hyphen"
        )
    if TAXID.fullmatch(taxid) is None:
        raise ValueError(
            f"{path}:{line_number}: invalid NCBI TaxID {taxid!r}; "
            "only canonical positive decimal digits are permitted"
        )
    return source_id, taxid


def records(path: Path) -> Iterator[Record]:
    source_id: str | None = None
    taxid = ""
    header_line = 0
    sequence_lines: list[str] = []
    number = 0

    def complete() -> Record | None:
        if source_id is None:
            return None
        sequence = "".join(sequence_lines)
        if not sequence:
            raise ValueError(f"{path}:{header_line}: empty protein sequence")
        if any(char.isspace() for char in sequence):
            raise ValueError(
                f"{path}:{header_line}: whitespace inside a sequence is invalid"
            )
        return Record(number, header_line, source_id, taxid, sequence)

    with path.open(encoding="ascii", newline="") as handle:
        for line_number, raw in enumerate(handle, 1):
            line = raw.rstrip("\r\n")
            if line.startswith(">"):
                if previous := complete():
                    yield previous
                number += 1
                if number > 999_999_999:
                    raise ValueError("maximum number of source records exceeded")
                source_id, taxid = parse_header(line[1:], path, line_number)
                header_line = line_number
                sequence_lines = []
            elif source_id is None:
                if line:
                    raise ValueError(
                        f"{path}:{line_number}: sequence before first FASTA header"
                    )
            elif line:
                sequence_lines.append(line)
    if previous := complete():
        yield previous


def inspect_source(
    source: Path,
    accession_ids: bool,
    database: Path,
) -> tuple[set[str], int, dict[int, int]]:
    """Identify identical records by exact comparison without holding FASTA in RAM."""
    wanted: set[str] = set()
    duplicate_of: dict[int, int] = {}
    source_count = 0
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE seen ("
            "source_id TEXT PRIMARY KEY, taxid TEXT NOT NULL, "
            "sequence TEXT NOT NULL, first_record INTEGER NOT NULL)"
        )
        for record in records(source):
            source_count += 1
            wanted.add(record.taxid)
            if accession_ids and UNIPROT.fullmatch(record.source_id) is None:
                raise ValueError(
                    f"{source}:{record.header_line}: not a UniProt accession: "
                    f"{record.source_id!r}"
                )
            previous = connection.execute(
                "SELECT taxid, sequence, first_record FROM seen WHERE source_id = ?",
                (record.source_id,),
            ).fetchone()
            if previous is None:
                connection.execute(
                    "INSERT INTO seen "
                    "(source_id, taxid, sequence, first_record) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        record.source_id,
                        record.taxid,
                        record.sequence,
                        record.number,
                    ),
                )
            elif previous[0] == record.taxid and previous[1] == record.sequence:
                duplicate_of[record.number] = previous[2]
            else:
                raise ValueError(
                    f"{source}:{record.header_line}: conflicting duplicate ID "
                    f"{record.source_id!r}; header or sequence differs from "
                    f"source record {previous[2]}"
                )
    if source_count == 0:
        raise ValueError("input FASTA has no records")
    return wanted, source_count, duplicate_of


def taxid_decisions(
    wanted: set[str],
    nodes: Path | None,
    merged: Path | None,
) -> dict[str, tuple[str, str]]:
    if nodes is None:
        if merged is not None:
            raise ValueError("--taxonomy-merged requires --taxonomy-nodes")
        return {taxid: ("NOT_CHECKED", taxid) for taxid in wanted}

    aliases: dict[str, str] = {}
    if merged is not None:
        with merged.open(encoding="ascii") as handle:
            for line in handle:
                fields = line.split("|")
                if len(fields) >= 2:
                    source, current = fields[0].strip(), fields[1].strip()
                    if source in wanted:
                        aliases[source] = current

    candidates = wanted | set(aliases.values())
    present: set[str] = set()
    with nodes.open(encoding="ascii") as handle:
        for line in handle:
            current = line.split("|", 1)[0].strip()
            if current in candidates:
                present.add(current)

    results = {}
    for taxid in wanted:
        if taxid in present:
            results[taxid] = ("CURRENT", taxid)
        elif aliases.get(taxid) in present:
            results[taxid] = ("MERGED", aliases[taxid])
        else:
            results[taxid] = ("UNKNOWN_TAXID", "")
    return results


def _check_destination(destination: Path) -> None:
    if not destination.is_absolute():
        raise ValueError("--output-directory must be an absolute path")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"output directory must not exist: {destination}")
    checkout = next(
        (
            parent
            for parent in Path(__file__).resolve().parents
            if (parent / ".git").exists() and (parent / "pyproject.toml").exists()
        ),
        None,
    )
    if checkout is not None and (
        checkout == destination or checkout in destination.parents
    ):
        raise ValueError("output directory must be outside the Git checkout")


def _write_json(path: Path, value: dict) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def import_targets(
    source: Path,
    destination: Path,
    *,
    nodes: Path | None = None,
    merged: Path | None = None,
    accession_ids: bool = False,
    fresh_spec: Path | None = None,
    minlen: int = 10,
) -> dict:
    source = source.resolve(strict=True)
    if not source.is_file():
        raise ValueError("input must be a regular FASTA file")
    if isinstance(minlen, bool) or not isinstance(minlen, int) or minlen < 0:
        raise ValueError("--minlen must be a non-negative integer")
    for label, path in (("nodes", nodes), ("merged", merged)):
        if path is not None and not path.is_file():
            raise FileNotFoundError(f"{label}: {path}")
    if not destination.is_absolute():
        raise ValueError("--output-directory must be an absolute path")
    destination = destination.resolve(strict=False)
    _check_destination(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".progeny-stage00-preflight-", dir=destination.parent
    ) as directory:
        wanted, source_count, duplicate_of = inspect_source(
            source,
            accession_ids,
            Path(directory) / "seen.sqlite",
        )
    input_sha256 = sha256_file(source)
    decisions = taxid_decisions(wanted, nodes, merged)

    spec_data: dict | None = None
    if fresh_spec is not None:
        spec_data = json.loads(fresh_spec.read_text(encoding="utf-8"))
        if not isinstance(spec_data, dict) or not all(
            isinstance(spec_data.get(name), dict) for name in ("pipeline", "recipe")
        ):
            raise ValueError("fresh spec requires pipeline and recipe mappings")
        targets = spec_data["pipeline"].get("targets")
        if not isinstance(targets, dict):
            raise ValueError("fresh spec requires pipeline.targets mapping")
        if targets.get("mode") != "canonical":
            raise ValueError("fresh spec requires pipeline.targets.mode=canonical")

    staging = Path(tempfile.mkdtemp(prefix=".progeny-stage00-", dir=destination.parent))
    try:
        fasta_path = staging / "targets.fasta"
        metadata_path = staging / "targets.metadata.tsv"
        mapping_path = staging / "targets.mapping.tsv"
        rejected_path = staging / "targets.rejected.tsv"
        accepted = 0
        rejected = 0
        residues = 0
        merged_count = 0
        duplicate_count = 0
        short_count = 0
        with (
            fasta_path.open("w", encoding="ascii", newline="\n") as fasta,
            metadata_path.open("w", encoding="utf-8", newline="") as metadata,
            mapping_path.open("w", encoding="utf-8", newline="") as mapping,
            rejected_path.open("w", encoding="utf-8", newline="") as reject,
        ):
            metadata_tsv = csv.writer(metadata, delimiter="\t", lineterminator="\n")
            mapping_tsv = csv.writer(mapping, delimiter="\t", lineterminator="\n")
            rejected_tsv = csv.writer(reject, delimiter="\t", lineterminator="\n")
            metadata_tsv.writerow(("target_id", "ncbi_taxid", "uniprot_accession"))
            mapping_tsv.writerow(
                (
                    "target_id",
                    "source_record",
                    "header_line",
                    "source_id",
                    "raw_taxid",
                    "resolved_taxid",
                    "taxonomy_status",
                    "sequence_length",
                    "sequence_sha256",
                )
            )
            rejected_tsv.writerow(
                (
                    "source_record",
                    "header_line",
                    "source_id",
                    "raw_taxid",
                    "reason",
                    "first_source_record",
                )
            )
            for record in records(source):
                first = duplicate_of.get(record.number)
                if first is not None:
                    duplicate_count += 1
                    rejected += 1
                    rejected_tsv.writerow(
                        (
                            record.number,
                            record.header_line,
                            record.source_id,
                            record.taxid,
                            "DUPLICATE_IDENTICAL_RECORD",
                            first,
                        )
                    )
                    continue
                if len(record.sequence) < minlen:
                    short_count += 1
                    rejected += 1
                    rejected_tsv.writerow(
                        (
                            record.number,
                            record.header_line,
                            record.source_id,
                            record.taxid,
                            "BELOW_MINLEN",
                            "",
                        )
                    )
                    continue
                status, resolved = decisions[record.taxid]
                if status == "UNKNOWN_TAXID":
                    rejected += 1
                    rejected_tsv.writerow(
                        (
                            record.number,
                            record.header_line,
                            record.source_id,
                            record.taxid,
                            "UNKNOWN_TAXID",
                            "",
                        )
                    )
                    continue
                target_id = f"T{record.number:09d}"
                accession = record.source_id if accession_ids else ""
                fasta.write(f">{target_id}\n{record.sequence}\n")
                metadata_tsv.writerow((target_id, record.taxid, accession))
                mapping_tsv.writerow(
                    (
                        target_id,
                        record.number,
                        record.header_line,
                        record.source_id,
                        record.taxid,
                        resolved,
                        status,
                        len(record.sequence),
                        hashlib.sha256(record.sequence.encode("ascii")).hexdigest(),
                    )
                )
                accepted += 1
                residues += len(record.sequence)
                merged_count += status == "MERGED"
            for handle in (fasta, metadata, mapping, reject):
                handle.flush()
                os.fsync(handle.fileno())
        if sha256_file(source) != input_sha256:
            raise RuntimeError("FASTA changed during conversion")
        if accepted == 0:
            raise ValueError(
                "no acceptable targets; review --minlen, duplicate records "
                "and supplied taxonomy"
            )
        if accepted + rejected != source_count:
            raise RuntimeError("Stage 00 record accounting mismatch")

        summary = {
            "schema": SCHEMA,
            "source_records": source_count,
            "accepted_targets": accepted,
            "rejected_targets": rejected,
            "minlen": minlen,
            "rejected_below_minlen": short_count,
            "deduplicated_identical_records": duplicate_count,
            "rejected_unknown_taxid": rejected - short_count - duplicate_count,
            "merged_taxid_targets": merged_count,
            "total_residues": residues,
            "taxonomy_verification": "ENABLED" if nodes else "NOT_CHECKED",
            "uniprot_accession_mode": "EXPLICIT" if accession_ids else "NONE",
            "source_sha256": input_sha256,
        }
        _write_json(staging / "00_summary.json", summary)
        if spec_data is not None:
            spec_data["pipeline"]["targets"].update(
                {
                    "fasta": str(destination / "targets.fasta"),
                    "metadata": str(destination / "targets.metadata.tsv"),
                }
            )
            spec_data["recipe"]["targets_input"] = str(
                destination / "targets.metadata.tsv"
            )
            _write_json(staging / "fresh_spec.stage00.json", spec_data)

        manifest = {
            "schema": SCHEMA,
            "parameters": {
                "minlen": minlen,
                "identical_duplicate_policy": "KEEP_FIRST_AND_AUDIT_REST",
                "conflicting_duplicate_policy": "FAIL_CLOSED",
                "header_ids_are_uniprot_accessions": accession_ids,
            },
            "source": {"path": str(source), "sha256": input_sha256},
            "taxonomy": {
                "nodes": str(nodes.resolve()) if nodes else None,
                "nodes_sha256": sha256_file(nodes) if nodes else None,
                "merged": str(merged.resolve()) if merged else None,
                "merged_sha256": sha256_file(merged) if merged else None,
            },
            "files": {
                path.name: sha256_file(path)
                for path in sorted(staging.iterdir())
                if path.is_file() and path.name != "00_manifest.json"
            },
        }
        _write_json(staging / "00_manifest.json", manifest)
        _check_destination(destination)
        os.rename(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--minlen",
        type=int,
        default=10,
        help="Minimum sequence length; non-negative integer (default: 10)",
    )
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--taxonomy-nodes", type=Path)
    parser.add_argument("--taxonomy-merged", type=Path)
    parser.add_argument("--header-ids-are-uniprot-accessions", action="store_true")
    parser.add_argument("--fresh-spec-template", type=Path)
    args = parser.parse_args(argv)
    try:
        result = import_targets(
            args.input,
            args.output_directory,
            nodes=args.taxonomy_nodes,
            merged=args.taxonomy_merged,
            accession_ids=args.header_ids_are_uniprot_accessions,
            fresh_spec=args.fresh_spec_template,
            minlen=args.minlen,
        )
    except (OSError, ValueError, RuntimeError, UnicodeError) as exc:
        print(f"STAGE00_ERROR={exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"STAGE00_DATASET={args.output_directory.absolute()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
