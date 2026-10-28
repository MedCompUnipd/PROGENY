"""Exact SQLite/Roaring equivalence; opt in with a separately built binary."""

from __future__ import annotations

import hashlib
import os
import random
import subprocess
import tempfile
import unittest
from pathlib import Path

from progeny.information_accretion import (
    calculate_information_accretion,
    write_information_accretion,
)
from progeny.information_accretion_roaring import (
    calculate_information_accretion_roaring,
    write_native_inputs,
)
from progeny.ontology import GeneOntology, OntologyTerm
from progeny.stage08_go_closure import GoClosureIndex

BINARY = os.environ.get("PROGENY_IA_ROARING_BINARY")
ROOT = "GO:0003674"


def gaf_row(protein, term, aspect="F", qualifier="", db="UniProtKB"):
    return (
        "\t".join(
            [
                db,
                protein,
                "symbol",
                qualifier,
                term,
                "GO_REF:0000002",
                "IEA",
                "",
                aspect,
                "name",
                "",
                "protein",
                "taxon:9606",
                "20230125",
                "test",
                "",
                "",
            ]
        )
        + "\n"
    )


@unittest.skipUnless(BINARY, "Optional Roaring binary not requested")
class RoaringEquivalenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = Path(BINARY).resolve(strict=True)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ia-equivalence-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.counter = 0

    def compare(self, ontology, lines, *, threads=2):
        self.counter += 1
        directory = self.directory / str(self.counter)
        directory.mkdir()
        gaf = directory / "corpus.gaf"
        gaf.write_text("!gaf-version: 2.2\n" + "".join(lines), encoding="ascii")
        digest = hashlib.sha256(gaf.read_bytes()).hexdigest()
        graph = GoClosureIndex.from_gene_ontology(ontology)
        reference = calculate_information_accretion(
            gaf_path=gaf,
            expected_gaf_sha256=digest,
            ontology=ontology,
            graph=graph,
            scratch_database=directory / "reference.sqlite",
            ontology_sha256="a" * 64,
        )
        native = calculate_information_accretion_roaring(
            gaf_path=gaf,
            expected_gaf_sha256=digest,
            ontology=ontology,
            graph=graph,
            scratch_root=directory,
            ontology_sha256="a" * 64,
            binary_path=self.binary,
            threads=threads,
            max_address_space_bytes=2 * 1024**3,
        )
        scientific = {k: v for k, v in native.items() if k != "backend"}
        self.assertEqual(reference, scientific)
        for label, result in (("sqlite", reference), ("roaring", native)):
            write_information_accretion(
                result,
                tsv_path=directory / f"{label}.tsv",
                manifest_path=directory / f"{label}.json",
            )
        self.assertEqual(
            (directory / "sqlite.tsv").read_bytes(),
            (directory / "roaring.tsv").read_bytes(),
        )
        return native

    def test_overlaps_diamond_three_parents_roots_orphans_and_multiple_aspects(self):
        ids = [f"GO:{i:07d}" for i in range(9000001, 9000007)]
        ontology = GeneOntology(
            [OntologyTerm(ROOT, namespace="molecular_function")]
            + [OntologyTerm(i, namespace="molecular_function") for i in ids]
            + [OntologyTerm("GO:0008150", namespace="biological_process")],
            [(i, "is_a", ROOT) for i in ids[:3]]
            + [(ids[3], "is_a", i) for i in ids[:3]]
            + [
                (ids[4], "part_of", ids[0]),
                (ids[4], "is_a", ids[1]),
                (ids[3], "is_a", "GO:0008150"),
            ],
        )
        rows = [
            gaf_row("P1", ids[3]),
            gaf_row("P1", ids[4]),
            gaf_row("P1", ids[3]),
            gaf_row("P2", ids[0]),
            gaf_row("P2", ids[1]),
            gaf_row("P2", ids[2]),
            gaf_row("P3", ids[5]),
            gaf_row("P1", "GO:0008150", "P"),
            gaf_row("P4", ROOT),
            gaf_row("P5", ids[3], qualifier="NOT"),
        ]
        result = self.compare(ontology, rows)
        self.assertEqual(result["term_values"][ids[3]]["parent_conjunction_count"], 2)
        self.assertEqual(result["aspect_protein_counts"], {"F": 4, "P": 1})
        self.compare(ontology, list(reversed(rows)), threads=1)

    def test_alias_replacement_anomalies_ambiguity_unknown_and_not(self):
        old, cross, child, alias, ambiguous, deprecated = [
            f"GO:{i:07d}" for i in range(9000021, 9000027)
        ]
        ontology = GeneOntology(
            [
                OntologyTerm(ROOT, namespace="molecular_function"),
                OntologyTerm(
                    child, namespace="molecular_function", alternate_ids=(alias,)
                ),
                OntologyTerm(
                    old,
                    namespace="molecular_function",
                    obsolete=True,
                    replaced_by=(child,),
                ),
                OntologyTerm(
                    cross,
                    namespace="biological_process",
                    obsolete=True,
                    replaced_by=(child,),
                ),
                OntologyTerm(
                    ambiguous,
                    namespace="molecular_function",
                    obsolete=True,
                    replaced_by=(ROOT, child),
                ),
                OntologyTerm(
                    deprecated, namespace="molecular_function", deprecated=True
                ),
            ],
            [(child, "is_a", ROOT)],
        )
        self.compare(
            ontology,
            [
                gaf_row("P1", alias),
                gaf_row("P1", old),
                gaf_row("P2", child),
                gaf_row("P3", cross, "P"),
                gaf_row("P3", cross, "F"),
                gaf_row("P3", child, "?"),
                gaf_row("P3", ambiguous),
                gaf_row("P3", deprecated),
                gaf_row("P3", "GO:9999999"),
                gaf_row("P3", child, qualifier="enables|NOT"),
                gaf_row("P3", child, db="RNAcentral"),
            ],
        )

    def test_empty_and_not_only_corpora(self):
        ontology = GeneOntology([OntologyTerm(ROOT, namespace="molecular_function")])
        self.compare(ontology, [])
        self.compare(ontology, [gaf_row("P1", ROOT, qualifier="NOT")])

    def test_seeded_random_dags_and_unordered_proteins(self):
        for seed in range(12):
            rng = random.Random(seed)
            ids = [ROOT] + [f"GO:{9000100 + i:07d}" for i in range(25)]
            terms = [OntologyTerm(i, namespace="molecular_function") for i in ids]
            edges = []
            for i in range(1, len(ids)):
                for parent in rng.sample(ids[:i], rng.randrange(min(4, i) + 1)):
                    edges.append((ids[i], rng.choice(["is_a", "part_of"]), parent))
            ontology = GeneOntology(terms, edges)
            rows = [
                gaf_row(f"P{rng.randrange(70)}", rng.choice(ids)) for _ in range(400)
            ]
            rows += rows[:50]
            rng.shuffle(rows)
            self.compare(ontology, rows, threads=1 + seed % 3)

    def test_bitmap_containers_across_65536_protein_ids(self):
        child = "GO:9000200"
        ontology = GeneOntology(
            [
                OntologyTerm(ROOT, namespace="molecular_function"),
                OntologyTerm(child, namespace="molecular_function"),
            ],
            [(child, "is_a", ROOT)],
        )
        rows = [gaf_row(f"P{i}", child if i % 3 else ROOT) for i in range(70_000)]
        rows += rows[::7]
        result = self.compare(ontology, rows)
        self.assertEqual(result["unique_direct_proteins"], 70_000)
        self.assertEqual(result["term_values"][ROOT]["term_count"], 70_000)

    def test_wrong_gaf_hash_fails_closed(self):
        gaf = self.directory / "wrong.gaf"
        gaf.write_text("!gaf-version: 2.2\n" + gaf_row("P1", ROOT), encoding="ascii")
        ontology = GeneOntology([OntologyTerm(ROOT, namespace="molecular_function")])
        with self.assertRaisesRegex(ValueError, "GAF SHA-256"):
            calculate_information_accretion_roaring(
                gaf_path=gaf,
                expected_gaf_sha256="0" * 64,
                ontology=ontology,
                graph=GoClosureIndex.from_gene_ontology(ontology),
                scratch_root=self.directory,
                ontology_sha256="a" * 64,
                binary_path=self.binary,
                max_address_space_bytes=2 * 1024**3,
            )

    def test_native_rejects_cycles_before_reading_input(self):
        graph_path = self.directory / "graph.tsv"
        graph_path.write_text(
            "go_id\taspect\tis_root\tparents\n"
            "GO:9000001\tF\t0\tGO:9000002\n"
            "GO:9000002\tF\t0\tGO:9000001\n",
            encoding="ascii",
        )
        result = subprocess.run(
            [
                str(self.binary),
                str(graph_path),
                str(self.directory / "no-policy"),
                str(self.directory / "counts"),
                str(self.directory / "audit"),
                "1",
                str(2 * 1024**3),
            ],
            input=b"",
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"cyclic graph", result.stderr)
        self.assertFalse((self.directory / "counts").exists())

    def test_native_refuses_existing_outputs(self):
        ontology = GeneOntology([OntologyTerm(ROOT, namespace="molecular_function")])
        graph, policy = write_native_inputs(
            ontology, GoClosureIndex.from_gene_ontology(ontology), self.directory
        )
        counts = self.directory / "counts"
        counts.write_bytes(b"preserve")
        result = subprocess.run(
            [
                str(self.binary),
                str(graph),
                str(policy),
                str(counts),
                str(self.directory / "audit"),
                "1",
                str(2 * 1024**3),
            ],
            input=b"",
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(counts.read_bytes(), b"preserve")

    def test_malformed_gaf_fails_closed(self):
        gaf = self.directory / "malformed.gaf"
        gaf.write_text("only\ttwo\n", encoding="ascii")
        ontology = GeneOntology([OntologyTerm(ROOT, namespace="molecular_function")])
        with self.assertRaisesRegex(ValueError, "Native IA engine"):
            calculate_information_accretion_roaring(
                gaf_path=gaf,
                expected_gaf_sha256=digest_file_for_test(gaf),
                ontology=ontology,
                graph=GoClosureIndex.from_gene_ontology(ontology),
                scratch_root=self.directory,
                ontology_sha256="a" * 64,
                binary_path=self.binary,
                max_address_space_bytes=2 * 1024**3,
            )


def digest_file_for_test(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
