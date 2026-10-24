"""Preserve user FASTA headers without changing Stage 00 scientific identifiers."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

HEADER_FIELDS = (
    "target_id",
    "source_record",
    "source_id",
    "original_header",
    "sequence_sha256",
)


def _rows(path: Path):
    with path.open(encoding="utf-8", newline="") as stream:
        yield from csv.DictReader(stream, delimiter="\t")


def preserve_headers(original: Path, stage00: Path, destination: Path) -> Path:
    """Match original records by ordinal, ID and literal sequence SHA-256.

    The original header (including description or tab-delimited TaxID) is data;
    it never becomes a documentary UniProt accession or a canonical ID.
    """
    records = {}
    for row in _rows(stage00 / "targets.mapping.tsv"):
        number = int(row["source_record"])
        if number in records:
            raise ValueError("Duplicate Stage 00 source record")
        records[number] = row
    if not records:
        raise ValueError("Stage 00 contains no accepted target")

    source_digest = hashlib.sha256()
    destination.mkdir(parents=True, exist_ok=False)
    path = destination / "original_headers.tsv"
    observed = set()
    ordinal = 0
    header: str | None = None
    residues = []

    def finish(writer):
        if header is None:
            return
        row = records.get(ordinal)
        if row is None:
            return
        if "\t" in header:
            source_id = header.split("\t", 1)[0]
        else:
            source_id = header.split(None, 1)[0]
        sequence = "".join(residues)
        digest = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        if row["source_id"] != source_id or row["sequence_sha256"] != digest:
            raise ValueError(f"Original FASTA identity mismatch: record {ordinal}")
        writer.writerow(
            (
                row["target_id"],
                row["source_record"],
                source_id,
                header,
                digest,
            )
        )
        observed.add(ordinal)

    with (
        original.open("rb") as source,
        path.open("x", encoding="utf-8", newline="") as output,
    ):
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow(HEADER_FIELDS)
        for raw in source:
            source_digest.update(raw)
            line = raw.decode("ascii").rstrip("\r\n")
            if line.startswith(">"):
                finish(writer)
                ordinal += 1
                header = line[1:]
                residues = []
            elif line:
                residues.append(line)
        finish(writer)

    if observed != set(records):
        raise ValueError("Source FASTA is missing accepted Stage 00 records")
    identity = {
        "schema": "progeny-original-fasta-headers-v1",
        "source_fasta_sha256": source_digest.hexdigest(),
        "stage00_mapping_sha256": _sha(stage00 / "targets.mapping.tsv"),
        "original_headers_sha256": _sha(path),
        "accepted_targets": len(records),
    }
    (destination / "manifest.json").write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
