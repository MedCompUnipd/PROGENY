"""End-to-end tests for the public, strict Stage 00 FASTA adapter."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/pipeline/00_import_targets.py"


def run_adapter(
    tmp_path: Path, fasta: str, *options: str
) -> tuple[subprocess.CompletedProcess[str], Path]:
    source = tmp_path / "source.fasta"
    source.write_text(fasta, encoding="utf-8")
    destination = tmp_path / "dataset"
    arguments = [
        sys.executable,
        str(SCRIPT),
        "--input",
        str(source),
        "--output-directory",
        str(destination),
        *options,
    ]
    # Existing Stage 00 tests exercise layout and taxonomy independently of
    # the alpha's default minimum length; each opts out explicitly here.
    if "--minlen" not in options and "--use-default-minlen" not in options:
        arguments.extend(("--minlen", "0"))
    if "--use-default-minlen" in arguments:
        arguments.remove("--use-default-minlen")
    result = subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, destination


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_multiline_and_literal_ambiguous_symbols(tmp_path: Path) -> None:
    result, dest = run_adapter(
        tmp_path, ">CAFA_1\t9606\nACD\nXBJZ\n>CAFA_2\t10090\nMNP\n"
    )
    assert result.returncode == 0, result.stderr
    assert (dest / "targets.fasta").read_text() == (
        ">T000000001\nACDXBJZ\n>T000000002\nMNP\n"
    )
    metadata = read_tsv(dest / "targets.metadata.tsv")
    assert metadata[0] == {
        "target_id": "T000000001",
        "ncbi_taxid": "9606",
        "uniprot_accession": "",
    }
    mapping = read_tsv(dest / "targets.mapping.tsv")
    assert mapping[0]["source_id"] == "CAFA_1"
    assert mapping[0]["sequence_sha256"] == hashlib.sha256(b"ACDXBJZ").hexdigest()
    assert mapping[0]["taxonomy_status"] == "NOT_CHECKED"
    assert len(read_tsv(dest / "targets.rejected.tsv")) == 0
    manifest = json.loads((dest / "00_manifest.json").read_text())
    assert (
        manifest["files"]["targets.fasta"]
        == hashlib.sha256((dest / "targets.fasta").read_bytes()).hexdigest()
    )
    assert len(manifest["files"]) == 5


def test_invalid_headers_fail_whole_conversion(tmp_path: Path) -> None:
    bad_headers = (
        ">ABC 123\t9606",
        ">ABC_1 9606",
        ">ABC_1\tX9606",
        ">ABC_1\t9606.0",
        ">ABC_1\t+9606",
        ">ABC_1\t0",
        ">ABC_1\t0009606",
        ">ABC_1\t9606\tmore",
        ">ABC/1\t9606",
        ">ABC_1\t9606 ",
        ">\t9606",
        ">ABC_1\t",
    )
    for index, header in enumerate(bad_headers):
        location = tmp_path / str(index)
        location.mkdir()
        result, dest = run_adapter(location, f"{header}\nACDE\n")
        assert result.returncode == 2, (header, result.stderr)
        assert not dest.exists(), header


def test_duplicate_source_id_rejected(tmp_path: Path) -> None:
    result, dest = run_adapter(tmp_path, ">A\t9606\nACDE\n>A\t9606\nMNPQ\n")
    assert result.returncode == 2
    assert "duplicate ID" in result.stderr
    assert not dest.exists()


def test_empty_input_and_empty_sequence_fail(tmp_path: Path) -> None:
    for index, text in enumerate(("", ">A\t9606\n", "ACDE\n")):
        folder = tmp_path / str(index)
        folder.mkdir()
        result, dest = run_adapter(folder, text)
        assert result.returncode == 2
        assert not dest.exists()


def test_taxonomy_unknown_rejected_and_merged_preserved(tmp_path: Path) -> None:
    nodes = tmp_path / "nodes.dmp"
    nodes.write_text("9606\t|\t1\t|\n10090\t|\t1\t|\n")
    merged = tmp_path / "merged.dmp"
    merged.write_text("123\t|\t9606\t|\n")
    result, dest = run_adapter(
        tmp_path,
        ">KNOWN\t9606\nAC\n>OLD\t123\nBX\n>UNKNOWN\t999999\nJZ\n",
        "--taxonomy-nodes",
        str(nodes),
        "--taxonomy-merged",
        str(merged),
    )
    assert result.returncode == 0, result.stderr
    assert (dest / "targets.fasta").read_text() == (
        ">T000000001\nAC\n>T000000002\nBX\n"
    )
    data = read_tsv(dest / "targets.mapping.tsv")
    assert data[1]["taxonomy_status"] == "MERGED"
    assert data[1]["raw_taxid"] == "123"
    assert data[1]["resolved_taxid"] == "9606"
    assert read_tsv(dest / "targets.rejected.tsv")[0]["source_id"] == "UNKNOWN"
    summary = json.loads((dest / "00_summary.json").read_text())
    assert summary["rejected_unknown_taxid"] == 1
    assert summary["merged_taxid_targets"] == 1


def test_all_unknown_taxids_fail_without_dataset(tmp_path: Path) -> None:
    nodes = tmp_path / "nodes.dmp"
    nodes.write_text("9606\t|\t1\t|\n")
    result, dest = run_adapter(
        tmp_path, ">UNKNOWN\t123\nACDE\n", "--taxonomy-nodes", str(nodes)
    )
    assert result.returncode == 2
    assert "no acceptable targets" in result.stderr
    assert not dest.exists()


def test_explicit_uniprot_accession_mode(tmp_path: Path) -> None:
    result, dest = run_adapter(
        tmp_path,
        ">P12345\t9606\nACDE\n",
        "--header-ids-are-uniprot-accessions",
    )
    assert result.returncode == 0, result.stderr
    assert read_tsv(dest / "targets.metadata.tsv")[0]["uniprot_accession"] == "P12345"


def test_false_uniprot_accession_rejected(tmp_path: Path) -> None:
    result, dest = run_adapter(
        tmp_path,
        ">CAFA_ID1\t9606\nACDE\n",
        "--header-ids-are-uniprot-accessions",
    )
    assert result.returncode == 2
    assert "not a UniProt accession" in result.stderr
    assert not dest.exists()


def test_fresh_spec_paths_updated_without_creating_run(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    original = {
        "pipeline": {"targets": {"mode": "canonical", "fasta": "OLD"}},
        "recipe": {"targets_input": "OLD"},
    }
    spec.write_text(json.dumps(original))
    result, dest = run_adapter(
        tmp_path, ">A\t9606\nACDE\n", "--fresh-spec-template", str(spec)
    )
    assert result.returncode == 0, result.stderr
    new = json.loads((dest / "fresh_spec.stage00.json").read_text())
    assert new["pipeline"]["targets"]["fasta"] == str(dest / "targets.fasta")
    assert new["recipe"]["targets_input"] == str(dest / "targets.metadata.tsv")
    assert original == json.loads(spec.read_text())


def test_existing_destination_is_never_overwritten(tmp_path: Path) -> None:
    destination = tmp_path / "dataset"
    destination.mkdir()
    sentinel = destination / "sentinel.txt"
    sentinel.write_text("PRESERVE")
    result, _ = run_adapter(tmp_path, ">A\t9606\nACDE\n")
    assert result.returncode == 2
    assert sentinel.read_text() == "PRESERVE"


def test_default_minlen_10_excludes_short_records(tmp_path: Path) -> None:
    result, dest = run_adapter(
        tmp_path,
        ">SHORT\t9606\nABCDEFGHI\n>EXACT10\t9606\nABCDEFGHIJ\n"
        ">LONGER\t9606\nABCDEFGHIJK\n",
        "--use-default-minlen",
    )
    assert result.returncode == 0, result.stderr
    assert (dest / "targets.fasta").read_text() == (
        ">T000000002\nABCDEFGHIJ\n>T000000003\nABCDEFGHIJK\n"
    )
    rejected = read_tsv(dest / "targets.rejected.tsv")
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "BELOW_MINLEN"
    assert rejected[0]["source_id"] == "SHORT"
    summary = json.loads((dest / "00_summary.json").read_text())
    assert summary["minlen"] == 10
    manifest = json.loads((dest / "00_manifest.json").read_text())
    assert manifest["parameters"]["minlen"] == 10
    assert manifest["parameters"]["conflicting_duplicate_policy"] == "FAIL_CLOSED"
    assert summary["accepted_targets"] == 2
    assert summary["rejected_below_minlen"] == 1
    assert summary["rejected_targets"] == 1
    assert summary["source_records"] == 3


def test_minlen_zero_accepts_two_residues(tmp_path: Path) -> None:
    result, dest = run_adapter(tmp_path, ">TWO\t9606\nAX\n", "--minlen", "0")
    assert result.returncode == 0, result.stderr
    assert (dest / "targets.fasta").read_text() == ">T000000001\nAX\n"
    summary = json.loads((dest / "00_summary.json").read_text())
    assert summary["minlen"] == 0


def test_minlen_one_excludes_nothing_nonempty(tmp_path: Path) -> None:
    result, dest = run_adapter(tmp_path, ">ONE\t9606\nA\n", "--minlen", "1")
    assert result.returncode == 0, result.stderr
    assert len(read_tsv(dest / "targets.mapping.tsv")) == 1


def test_invalid_minlen_rejected_atomically(tmp_path: Path) -> None:
    for index, invalid in enumerate(("-1", "1.5", "not_an_int")):
        location = tmp_path / f"invalid-{index}"
        location.mkdir()
        result, dest = run_adapter(
            location, ">ONE\t9606\nABCDEFGHIJK\n", "--minlen", invalid
        )
        assert result.returncode == 2, (invalid, result.stderr)
        assert not dest.exists()


def test_identical_header_and_sequence_are_deduplicated(tmp_path: Path) -> None:
    result, dest = run_adapter(
        tmp_path,
        ">A_01\t9606\nABCDE\nFGHIJ\n"
        ">B_02\t9606\nABCDEFGHIJ\n"
        ">A_01\t9606\nABCDEFGHIJ\n"
        ">A_01\t9606\nABC\nDEFGHIJ\n",
    )
    assert result.returncode == 0, result.stderr
    assert (dest / "targets.fasta").read_text() == (
        ">T000000001\nABCDEFGHIJ\n>T000000002\nABCDEFGHIJ\n"
    )
    mapping = read_tsv(dest / "targets.mapping.tsv")
    assert [row["source_id"] for row in mapping] == ["A_01", "B_02"]
    rejected = read_tsv(dest / "targets.rejected.tsv")
    assert [row["source_record"] for row in rejected] == ["3", "4"]
    assert [row["first_source_record"] for row in rejected] == ["1", "1"]
    assert all(row["reason"] == "DUPLICATE_IDENTICAL_RECORD" for row in rejected)
    summary = json.loads((dest / "00_summary.json").read_text())
    assert summary["source_records"] == 4
    assert summary["accepted_targets"] == 2
    assert summary["deduplicated_identical_records"] == 2
    assert summary["rejected_targets"] == 2


def test_same_id_different_sequence_or_taxid_fails(tmp_path: Path) -> None:
    bad = (
        ">A\t9606\nABCDEFGHIJ\n>A\t9606\nABCDEFGHI\n",
        ">A\t9606\nABCDEFGHIJ\n>A\t10090\nABCDEFGHIJ\n",
    )
    for index, text in enumerate(bad):
        location = tmp_path / f"conflict-{index}"
        location.mkdir()
        result, dest = run_adapter(location, text)
        assert result.returncode == 2
        assert "conflicting duplicate ID" in result.stderr
        assert not dest.exists()


def test_below_minlen_and_duplicate_are_both_audited(tmp_path: Path) -> None:
    result, dest = run_adapter(
        tmp_path,
        ">SHORT\t9606\nAB\n>SHORT\t9606\nAB\n>VALID\t9606\nABCDEFGHIJ\n",
        "--minlen",
        "10",
    )
    assert result.returncode == 0, result.stderr
    rejected = read_tsv(dest / "targets.rejected.tsv")
    assert [row["reason"] for row in rejected] == [
        "BELOW_MINLEN",
        "DUPLICATE_IDENTICAL_RECORD",
    ]
    assert rejected[1]["first_source_record"] == "1"
    assert (dest / "targets.fasta").read_text() == ">T000000003\nABCDEFGHIJ\n"


def test_all_records_below_minlen_have_no_published_dataset(tmp_path: Path) -> None:
    result, dest = run_adapter(tmp_path, ">SHORT\t9606\nAB\n", "--use-default-minlen")
    assert result.returncode == 2
    assert "no acceptable targets" in result.stderr
    assert not dest.exists()


def test_invalid_taxid_aborts_even_when_too_short(tmp_path: Path) -> None:
    result, dest = run_adapter(
        tmp_path,
        ">BAD\tabc\nAB\n>GOOD\t9606\nABCDEFGHIJ\n",
        "--minlen",
        "10",
    )
    assert result.returncode == 2
    assert "invalid NCBI TaxID" in result.stderr
    assert not dest.exists()


def test_distinct_ids_same_sequence_not_collapsed(tmp_path: Path) -> None:
    result, dest = run_adapter(
        tmp_path,
        ">X\t9606\nABCDEFGHIJ\n>Y\t9606\nABCDEFGHIJ\n",
        "--use-default-minlen",
    )
    assert result.returncode == 0, result.stderr
    assert len(read_tsv(dest / "targets.mapping.tsv")) == 2
    summary = json.loads((dest / "00_summary.json").read_text())
    assert summary["deduplicated_identical_records"] == 0


def test_unknown_taxid_duplicate_counted_separately(tmp_path: Path) -> None:
    nodes = tmp_path / "nodes.dmp"
    nodes.write_text("9606\t|\t1\t|\n")
    result, dest = run_adapter(
        tmp_path,
        ">UNKNOWN\t999999\nABCDEFGHIJ\n"
        ">UNKNOWN\t999999\nABCDEFGHIJ\n"
        ">KNOWN\t9606\nABCDEFGHIJ\n",
        "--taxonomy-nodes",
        str(nodes),
        "--use-default-minlen",
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads((dest / "00_summary.json").read_text())
    assert summary["deduplicated_identical_records"] == 1
    assert summary["rejected_unknown_taxid"] == 1
    assert summary["accepted_targets"] == 1
    assert summary["rejected_targets"] == 2
