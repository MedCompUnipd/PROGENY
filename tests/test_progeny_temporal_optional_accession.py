"""Regression for optional original UniProt accessions in Temporal V2."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from progeny.stage08_temporal_benchmark import (
    crosscheck_stage01_mapping,
    load_target_ids,
    resolve_identical_target_aliases,
)

METADATA_HEADER = ("target_id", "ncbi_taxid", "uniprot_accession")
STAGE01_HEADER = (
    "target_id",
    "raw_taxid",
    "optional_accession",
    "normalized_sequence",
    "sequence_length",
    "sequence_sha256",
    "normalization_policy_version",
)


def _write_tables(tmp_path: Path, rows: list[tuple[str, str, str, str]]):
    metadata = tmp_path / "targets.metadata.tsv"
    stage01 = tmp_path / "01_targets.tsv"
    with (
        metadata.open("w", encoding="utf-8", newline="") as left,
        stage01.open("w", encoding="utf-8", newline="") as right,
    ):
        meta_writer = csv.writer(left, delimiter="\t", lineterminator="\n")
        stage_writer = csv.writer(right, delimiter="\t", lineterminator="\n")
        meta_writer.writerow(METADATA_HEADER)
        stage_writer.writerow(STAGE01_HEADER)
        for target, taxon, accession, sequence in rows:
            digest = hashlib.sha256(sequence.encode("ascii")).hexdigest()
            meta_writer.writerow((target, taxon, accession))
            stage_writer.writerow(
                (
                    target,
                    taxon,
                    accession,
                    sequence,
                    len(sequence),
                    digest,
                    "protein-sequence-v1",
                )
            )
    return metadata, stage01


def test_three_accession_free_targets_remain_independent(tmp_path: Path):
    metadata, stage01 = _write_tables(
        tmp_path,
        [
            ("T000000001", "111", "", "ACDEFGHIKLMNPQRSTVWY"),
            ("T000000002", "111", "", "ACDEFGHIKLMNPQRSTVWY"),
            ("T000000003", "111", "", "MNPQRSTVWYACDEFGHIKL"),
        ],
    )
    mapping = load_target_ids(metadata)
    assert len(mapping) == 3
    assert all(accession == "" for accession in mapping.values())
    assert crosscheck_stage01_mapping(stage01, mapping) == 3
    assert resolve_identical_target_aliases(metadata, stage01, mapping) == ({}, [])
    assert len({accession or target for target, accession in mapping.items()}) == 3


def test_mixed_known_and_unknown_accessions_stay_distinct(tmp_path: Path):
    metadata, stage01 = _write_tables(
        tmp_path,
        [
            ("T000000001", "111", "", "ACDEFGHIKLMNPQRSTVWY"),
            ("T000000002", "111", "P12345", "MNPQRSTVWYACDEFGHIKL"),
            ("T000000003", "111", "", "MNPQRSTVWYACDEFGHIKL"),
        ],
    )
    mapping = load_target_ids(metadata, allow_identical_duplicates=True)
    assert mapping == {
        "T000000001": "",
        "T000000002": "P12345",
        "T000000003": "",
    }
    assert crosscheck_stage01_mapping(stage01, mapping) == 3
    assert resolve_identical_target_aliases(metadata, stage01, mapping) == ({}, [])
    assert {accession or target for target, accession in mapping.items()} == {
        "T000000001",
        "P12345",
        "T000000003",
    }


def test_declared_accession_cannot_collide_with_fallback_id(tmp_path: Path):
    metadata, _ = _write_tables(
        tmp_path,
        [
            ("T000000001", "111", "", "ACDEFGHIKLMNPQRSTVWY"),
            ("T000000002", "111", "T000000001", "MNPQRSTVWYACDEFGHIKL"),
        ],
    )
    with pytest.raises(ValueError, match="collides with internal query ID"):
        load_target_ids(metadata, allow_identical_duplicates=True)


def test_identical_declared_accessions_still_alias(tmp_path: Path):
    sequence = "ACDEFGHIKLMNPQRSTVWY"
    metadata, stage01 = _write_tables(
        tmp_path,
        [
            ("T000000001", "111", "P12345", sequence),
            ("T000000002", "111", "P12345", sequence),
        ],
    )
    with pytest.raises(ValueError, match="Duplicate original accession"):
        load_target_ids(metadata)
    mapping = load_target_ids(metadata, allow_identical_duplicates=True)
    assert crosscheck_stage01_mapping(stage01, mapping) == 2
    aliases, ledger = resolve_identical_target_aliases(metadata, stage01, mapping)
    assert aliases == {"T000000002": "T000000001"}
    assert len(ledger) == 1


def test_nonidentical_declared_accessions_fail_closed(tmp_path: Path):
    metadata, stage01 = _write_tables(
        tmp_path,
        [
            ("T000000001", "111", "P12345", "ACDEFGHIKLMNPQRSTVWY"),
            ("T000000002", "111", "P12345", "MNPQRSTVWYACDEFGHIKL"),
        ],
    )
    mapping = load_target_ids(metadata, allow_identical_duplicates=True)
    with pytest.raises(ValueError, match="Non-identical targets"):
        resolve_identical_target_aliases(metadata, stage01, mapping)


@pytest.mark.parametrize(
    "bad_row",
    [
        ("", "111", ""),
        ("T000000001", "", ""),
        ("T000000001", "111", "P 12345"),
    ],
)
def test_invalid_required_target_fields_still_fail(tmp_path: Path, bad_row):
    metadata, _ = _write_tables(
        tmp_path,
        [(bad_row[0], bad_row[1], bad_row[2], "ACDEFGHIKLMNPQRSTVWY")],
    )
    with pytest.raises(ValueError, match="Invalid"):
        load_target_ids(metadata)
