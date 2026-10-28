from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pytest

from progeny.information_accretion import (
    calculate_information_accretion,
    write_information_accretion,
)
from progeny.ontology import GeneOntology, OntologyTerm
from progeny.stage08_go_closure import GoClosureIndex

ROOT = "GO:0003674"
PARENT_A = "GO:0005488"
PARENT_B = "GO:0005515"
CHILD = "GO:0000010"
ORPHAN = "GO:0000030"
OBSOLETE_BP = "GO:0051238"
MF_REPLACEMENT = "GO:0140487"


def _ontology() -> tuple[GeneOntology, GoClosureIndex]:
    ontology = GeneOntology(
        [
            OntologyTerm(ROOT, namespace="molecular_function"),
            OntologyTerm(PARENT_A, namespace="molecular_function"),
            OntologyTerm(PARENT_B, namespace="molecular_function"),
            OntologyTerm(CHILD, namespace="molecular_function"),
            OntologyTerm(ORPHAN, namespace="molecular_function"),
        ],
        [
            (PARENT_A, "is_a", ROOT),
            (PARENT_B, "is_a", ROOT),
            (CHILD, "is_a", PARENT_A),
            (CHILD, "part_of", PARENT_B),
        ],
    )
    return ontology, GoClosureIndex.from_gene_ontology(ontology)


def _gaf_row(
    protein: str,
    go: str,
    *,
    qualifier: str = "",
    evidence="IEA",
    aspect: str = "F",
) -> str:
    fields = [
        "UniProtKB",
        protein,
        protein,
        qualifier,
        go,
        "GO_REF:0000002",
        evidence,
        "InterPro:IPR000001",
        aspect,
        "example",
        "",
        "protein",
        "taxon:9606",
        "20230125",
        "InterPro",
        "",
        "",
    ]
    return "\t".join(fields) + "\n"


def _write_gaf(path: Path) -> str:
    content = "".join(
        [
            "!gaf-version: 2.2\n",
            _gaf_row("P1", CHILD),
            _gaf_row("P1", CHILD, evidence="EXP"),
            _gaf_row("P2", PARENT_A),
            _gaf_row("P3", PARENT_B),
            _gaf_row("P4", PARENT_A),
            _gaf_row("P4", PARENT_B),
            _gaf_row("P5", CHILD, qualifier="NOT"),
        ]
    )
    path.write_text(content, encoding="ascii")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compute(tmp_path: Path, expected_sha: str | None = None) -> dict:
    gaf = tmp_path / "start.gaf"
    digest = _write_gaf(gaf)
    ontology, graph = _ontology()
    return calculate_information_accretion(
        gaf_path=gaf,
        expected_gaf_sha256=expected_sha or digest,
        ontology=ontology,
        graph=graph,
        scratch_database=tmp_path / "ia.sqlite",
        ontology_sha256="a" * 64,
    )


def test_calculates_smoothed_parent_conjunction_ia(tmp_path: Path) -> None:
    result = _compute(tmp_path)
    assert result["status"] == "COMPUTED"
    assert result["unique_direct_proteins"] == 4
    assert result["unique_direct_pairs"] == 5
    assert result["not_rows_excluded"] == 1
    assert result["evidence_policy"].endswith("including_iea")
    assert result["term_values"][CHILD]["term_count"] == 1
    assert result["term_values"][CHILD]["parent_conjunction_count"] == 2
    assert math.isclose(result["term_values"][CHILD]["ia"], math.log2(1.5))
    assert result["term_values"][ORPHAN]["parent_conjunction_count"] == 4
    assert math.isclose(result["term_values"][ORPHAN]["ia"], math.log2(5))
    assert result["term_values"][ROOT]["ia"] == 0


def test_rejects_wrong_gaf_digest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="GAF SHA-256"):
        _compute(tmp_path, "0" * 64)


def test_rejects_nonempty_scratch_database(tmp_path: Path) -> None:
    gaf = tmp_path / "start.gaf"
    digest = _write_gaf(gaf)
    database = tmp_path / "ia.sqlite"
    database.touch()
    ontology, graph = _ontology()
    with pytest.raises(ValueError, match="must not already exist"):
        calculate_information_accretion(
            gaf_path=gaf,
            expected_gaf_sha256=digest,
            ontology=ontology,
            graph=graph,
            scratch_database=database,
            ontology_sha256="a" * 64,
        )


def test_excludes_replaced_go_across_aspects_and_audits_it(tmp_path: Path) -> None:
    ontology = GeneOntology(
        [
            OntologyTerm(ROOT, namespace="molecular_function"),
            OntologyTerm(
                MF_REPLACEMENT,
                namespace="molecular_function",
            ),
            OntologyTerm(
                OBSOLETE_BP,
                namespace="biological_process",
                obsolete=True,
                replaced_by=(MF_REPLACEMENT,),
            ),
        ],
        [(MF_REPLACEMENT, "is_a", ROOT)],
    )
    graph = GoClosureIndex.from_gene_ontology(ontology)
    gaf = tmp_path / "start-cross-aspect.gaf"
    gaf.write_text(
        "!gaf-version: 2.2\n"
        + _gaf_row("P1", OBSOLETE_BP, aspect="P")
        + _gaf_row("P2", MF_REPLACEMENT, aspect="F"),
        encoding="ascii",
    )
    digest = hashlib.sha256(gaf.read_bytes()).hexdigest()
    result = calculate_information_accretion(
        gaf_path=gaf,
        expected_gaf_sha256=digest,
        ontology=ontology,
        graph=graph,
        scratch_database=tmp_path / "cross-aspect.sqlite",
        ontology_sha256="a" * 64,
    )

    assert result["cross_aspect_replacement_rows_excluded"] == 1
    assert result["cross_aspect_replacement_mapping_counts"] == {
        f"{OBSOLETE_BP}|P->{MF_REPLACEMENT}|F": 1
    }
    assert result["unique_direct_pairs"] == 1
    assert result["aspect_protein_counts"] == {"F": 1}
    assert result["term_values"][MF_REPLACEMENT]["term_count"] == 1
    assert result["schema"] == "progeny-information-accretion-v3"


def test_retains_replaced_go_within_the_same_aspect(tmp_path: Path) -> None:
    bp_root = "GO:0008150"
    bp_replacement = "GO:0000002"
    ontology = GeneOntology(
        [
            OntologyTerm(bp_root, namespace="biological_process"),
            OntologyTerm(bp_replacement, namespace="biological_process"),
            OntologyTerm(
                OBSOLETE_BP,
                namespace="biological_process",
                obsolete=True,
                replaced_by=(bp_replacement,),
            ),
        ],
        [(bp_replacement, "is_a", bp_root)],
    )
    graph = GoClosureIndex.from_gene_ontology(ontology)
    gaf = tmp_path / "start-same-aspect-replacement.gaf"
    gaf.write_text(
        "!gaf-version: 2.2\n" + _gaf_row("P1", OBSOLETE_BP, aspect="P"),
        encoding="ascii",
    )
    digest = hashlib.sha256(gaf.read_bytes()).hexdigest()

    result = calculate_information_accretion(
        gaf_path=gaf,
        expected_gaf_sha256=digest,
        ontology=ontology,
        graph=graph,
        scratch_database=tmp_path / "same-aspect.sqlite",
        ontology_sha256="a" * 64,
    )

    assert result["cross_aspect_replacement_rows_excluded"] == 0
    assert result["remapped_go_rows"] == 1
    assert result["unique_direct_pairs"] == 1
    assert result["aspect_protein_counts"] == {"P": 1}


def test_excludes_and_audits_aspect_mismatches(tmp_path: Path) -> None:
    ontology = GeneOntology(
        [
            OntologyTerm(ROOT, namespace="molecular_function"),
            OntologyTerm(
                MF_REPLACEMENT,
                namespace="molecular_function",
            ),
            OntologyTerm(
                OBSOLETE_BP,
                namespace="biological_process",
                obsolete=True,
                replaced_by=(MF_REPLACEMENT,),
            ),
        ],
        [(MF_REPLACEMENT, "is_a", ROOT)],
    )
    graph = GoClosureIndex.from_gene_ontology(ontology)
    gaf = tmp_path / "start-aspect-mismatch.gaf"
    gaf.write_text(
        "!gaf-version: 2.2\n"
        + _gaf_row("P1", OBSOLETE_BP, aspect="F")
        + _gaf_row("P2", MF_REPLACEMENT, aspect="?"),
        encoding="ascii",
    )
    digest = hashlib.sha256(gaf.read_bytes()).hexdigest()

    result = calculate_information_accretion(
        gaf_path=gaf,
        expected_gaf_sha256=digest,
        ontology=ontology,
        graph=graph,
        scratch_database=tmp_path / "aspect-mismatch.sqlite",
        ontology_sha256="a" * 64,
    )

    assert result["source_aspect_mismatch_rows_excluded"] == 1
    assert result["source_aspect_mismatch_mapping_counts"] == {
        f"{OBSOLETE_BP}|GAF=F|source=P": 1
    }
    assert result["invalid_gaf_aspect_rows_excluded"] == 1
    assert result["invalid_gaf_aspect_mapping_counts"] == {
        f"{MF_REPLACEMENT}|GAF=?|source=F": 1
    }
    assert result["unique_direct_pairs"] == 0


def test_excludes_obsolete_go_without_unambiguous_replacement(
    tmp_path: Path,
) -> None:
    ambiguous = "GO:0099001"
    replacement_a = "GO:0099002"
    replacement_b = "GO:0099003"
    ontology = GeneOntology(
        [
            OntologyTerm(ROOT, namespace="molecular_function"),
            OntologyTerm(replacement_a, namespace="molecular_function"),
            OntologyTerm(replacement_b, namespace="molecular_function"),
            OntologyTerm(
                ambiguous,
                namespace="biological_process",
                obsolete=True,
                replaced_by=(replacement_a, replacement_b),
            ),
        ],
        [
            (replacement_a, "is_a", ROOT),
            (replacement_b, "is_a", ROOT),
        ],
    )
    graph = GoClosureIndex.from_gene_ontology(ontology)
    gaf = tmp_path / "start-ambiguous-replacement.gaf"
    gaf.write_text(
        "!gaf-version: 2.2\n" + _gaf_row("P1", ambiguous, aspect="P"),
        encoding="ascii",
    )
    digest = hashlib.sha256(gaf.read_bytes()).hexdigest()
    result = calculate_information_accretion(
        gaf_path=gaf,
        expected_gaf_sha256=digest,
        ontology=ontology,
        graph=graph,
        scratch_database=tmp_path / "ambiguous-replacement.sqlite",
        ontology_sha256="a" * 64,
    )

    assert result["unresolved_go_rows_excluded"] == 1
    assert result["go_resolution_status_counts"] == {"obsolete": 1}
    assert result["cross_aspect_replacement_rows_excluded"] == 0
    assert result["cross_aspect_replacement_mapping_counts"] == {}
    assert result["unique_direct_pairs"] == 0


def test_writes_table_and_provenance_deterministically(tmp_path: Path) -> None:
    result = _compute(tmp_path)
    result["source_role"] = "START"
    result["source_release_id"] = "2023_01"
    result["gaf_path"] = "/input/start.gaf"
    tsv = tmp_path / "out.tsv"
    manifest = tmp_path / "manifest.json"
    write_information_accretion(
        result,
        tsv_path=tsv,
        manifest_path=manifest,
    )
    assert tsv.read_text(encoding="utf-8").splitlines()[0].startswith("go_id\t")
    assert '"source_role": "START"' in manifest.read_text(encoding="utf-8")
    assert '"ia_table_sha256"' in manifest.read_text(encoding="utf-8")
    assert '"schema": "progeny-information-accretion-v3"' in manifest.read_text(
        encoding="utf-8"
    )
    assert '"cross_aspect_replacement_policy": "exclude_and_audit"' in (
        manifest.read_text(encoding="utf-8")
    )
