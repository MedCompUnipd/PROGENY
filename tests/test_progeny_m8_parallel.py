"""Synthetic START/END M8 exact-byte parity and worker failure isolation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from progeny.stage08_annotations import NormalizedGafSource
from progeny.stage08_collection_inputs import GafCollectionInput
from progeny.stage08_collection_publish import _scan_releases
from progeny.stage08_donors import DonorAssociation, DonorIndex
from progeny.workflow.artifacts import Artifact


def _association(release: str, accession: str, rid: int) -> DonorAssociation:
    return DonorAssociation(
        release=release,
        target_id=f"T{rid}",
        rid=str(rid),
        target_accession=".",
        candidate_accession=accession,
        annotation_donor="YES",
        decision_basis="TEST_EXACT",
        sequence_relation="EXACT",
        exact_sequence="1",
        scope="PRIMARY",
        evaluation_scope="PRIMARY",
        audit_outcome=".",
        accepted_candidates_for_target_release="1",
    )


def _gaf_line(accession: str, go: str, qualifier: str = "") -> str:
    return (
        "\t".join(
            (
                "UniProtKB",
                accession,
                "symbol",
                qualifier,
                go,
                "PMID:12",
                "EXP",
                "",
                "F",
                "name",
                "",
                "protein",
                "taxon:1",
                "20260910",
                "UniProt",
                "",
                "",
            )
        )
        + "\n"
    )


def _fixture(tmp_path: Path, repeats: int = 4):
    releases = {"START": "2023_01", "END": "2026_03"}
    associations = []
    gafs = []
    for index, (role, release) in enumerate(releases.items(), 1):
        accession = f"P{index}"
        associations.append(_association(release, accession, index))
        rows = ["!gaf-version: 2.2\n"]
        for _ in range(repeats):
            rows.append(_gaf_line(accession, "GO:0001111"))
            rows.append(_gaf_line(accession, "GO:0002222", "NOT"))
            rows.append(_gaf_line("OTHER", "GO:0003333"))
        data = "".join(rows).encode()
        path = tmp_path / f"{role}.gaf"
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        source = NormalizedGafSource(release, str(path), digest)
        artifact = Artifact(str(path), len(data), digest)
        gafs.append(GafCollectionInput(role, source, len(data), artifact, str(path)))
    donors = DonorIndex(
        associations,
        start_release_id=releases["START"],
        end_release_id=releases["END"],
        source_database="UniProtKB",
    )
    return SimpleNamespace(gafs=tuple(gafs), donors=donors)


def _files(folder: Path):
    return {
        str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize("repeat", [1, 40])
def test_serial_parallel_m8_complete_file_parity(tmp_path, repeat):
    inputs = _fixture(tmp_path, repeats=repeat)
    serial = tmp_path / "serial"
    parallel = tmp_path / "parallel"
    serial.mkdir()
    parallel.mkdir()
    serial_results = _scan_releases(inputs, serial, 1)
    parallel_results = _scan_releases(inputs, parallel, 2)
    assert serial_results == parallel_results
    assert _files(serial) == _files(parallel)
    assert len(_files(serial)) == 10
    assert [x.retrieved_source_rows for x in parallel_results] == [repeat * 2] * 2
    assert [x.annotation_links for x in parallel_results] == [repeat * 2] * 2
    assert all(x.coverage_certified for x in parallel_results)


def test_bad_gaf_sha_fails_closed_and_no_cross_release_write(tmp_path):
    inputs = _fixture(tmp_path)
    bad = inputs.gafs[1]
    bad_source = NormalizedGafSource(bad.source.release, bad.source.path, "f" * 64)
    inputs.gafs = (
        inputs.gafs[0],
        GafCollectionInput(
            bad.role,
            bad_source,
            bad.size_bytes,
            bad.upstream_manifest,
            bad.policy_reference_path,
        ),
    )
    output = tmp_path / "failed"
    output.mkdir()
    with pytest.raises(RuntimeError, match="END.*SHA256"):
        _scan_releases(inputs, output, 2)
    # Nothing was published or promoted from the private role subdirectories.
    assert sorted(path.name for path in output.iterdir()) == ["END", "START"]


@pytest.mark.parametrize("workers", [0, -1, 3, True, 1.5])
def test_reject_unsupported_parallel_worker_count(tmp_path, workers):
    inputs = _fixture(tmp_path)
    output = tmp_path / "bad"
    output.mkdir()
    with pytest.raises(ValueError, match="workers"):
        _scan_releases(inputs, output, workers)
    assert not list(output.iterdir())
