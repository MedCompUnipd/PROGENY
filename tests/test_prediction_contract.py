"""Independent small score oracles; no real predictions or GO data required."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from progeny.ontology import GeneOntology, OntologyTerm
from progeny.prediction_contract import (
    GoResolution,
    Prediction,
    prepare_predictions,
    read_predictions,
)
from progeny.prediction_inputs import BenchmarkInputs
from progeny.stage08_go_closure import GoClosureIndex

ROOT = "GO:0003674"
LEAF = "GO:0000001"
SKIP = "GO:0000002"
NEUTRAL = "GO:0000003"
ANCESTOR = "GO:0000004"
OTHER = "GO:0000005"
BP = "GO:0000006"
ALIAS = "GO:0000007"
REPLACED = "GO:0000008"


class PredictionContractTests(unittest.TestCase):
    def prepare(self, records, **changes):
        parents = {
            ROOT: (),
            LEAF: (SKIP,),
            SKIP: (NEUTRAL,),
            NEUTRAL: (ANCESTOR,),
            ANCESTOR: (ROOT,),
            OTHER: (ROOT,),
            BP: (),
        }

        def closure(go):
            result = {go}
            queue = [go]
            while queue:
                for parent in parents[queue.pop()]:
                    if parent not in result:
                        result.add(parent)
                        queue.append(parent)
            return result

        options = {
            "target_ids": frozenset({"A", "B"}),
            "eligible": frozenset({("A", "F"), ("B", "F")}),
            "masks": {("A", "F", SKIP): "SKIP", ("A", "F", NEUTRAL): "NEUTRAL"},
            "resolve": lambda go: GoResolution(
                LEAF if go in {ALIAS, REPLACED} else go if go in parents else None,
                "alternate_id"
                if go == ALIAS
                else "replaced"
                if go == REPLACED
                else "active"
                if go in parents
                else "unknown",
            ),
            "aspect": lambda go: "P" if go == BP else "F",
            "ancestors": closure,
        }
        options.update(changes)
        return prepare_predictions(records, **options)

    def read(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "predictions.tsv"
            path.write_text(text, encoding="utf-8")
            return list(read_predictions(path))

    def test_propagates_through_both_masks_before_exclusion(self):
        prepared = self.prepare([Prediction("A", LEAF, 0.8)])
        self.assertEqual(
            prepared.scores,
            {("A", "F", LEAF): 0.8, ("A", "F", ANCESTOR): 0.8},
        )
        self.assertEqual(prepared.counts["propagated_pairs"], 5)
        self.assertEqual(prepared.counts["root_pairs_excluded"], 1)
        self.assertEqual(prepared.counts["skip_pairs_excluded"], 1)
        self.assertEqual(prepared.counts["neutral_pairs_excluded"], 1)

    def test_masks_are_target_specific(self):
        prepared = self.prepare([Prediction("B", LEAF, 0.8)])
        self.assertIn(("B", "F", SKIP), prepared.scores)
        self.assertIn(("B", "F", NEUTRAL), prepared.scores)

    def test_duplicates_take_maximum_after_resolution(self):
        prepared = self.prepare(
            [Prediction("A", LEAF, 0.2), Prediction("A", ALIAS, 0.9)]
        )
        self.assertEqual(prepared.scores[("A", "F", ANCESTOR)], 0.9)
        self.assertEqual(prepared.counts["duplicate_rows_after_resolution"], 1)
        self.assertEqual(prepared.counts["remapped_rows"], 1)

    def test_unambiguous_replacement_is_audited(self):
        prepared = self.prepare([Prediction("A", REPLACED, 0.6)])
        self.assertEqual(prepared.scores[("A", "F", LEAF)], 0.6)
        self.assertEqual(prepared.counts["remapped_rows"], 1)

    def test_ancestor_gets_maximum_of_direct_and_inherited_scores(self):
        prepared = self.prepare(
            [Prediction("A", LEAF, 0.4), Prediction("A", ANCESTOR, 0.7)]
        )
        self.assertEqual(prepared.scores[("A", "F", LEAF)], 0.4)
        self.assertEqual(prepared.scores[("A", "F", ANCESTOR)], 0.7)

    def test_ineligible_aspect_is_excluded_and_counted(self):
        prepared = self.prepare([Prediction("A", BP, 0.9)])
        self.assertEqual(prepared.scores, {})
        self.assertEqual(prepared.counts["ineligible_pairs_excluded"], 1)

    def test_empty_predictions_do_not_invent_scores(self):
        prepared = self.prepare([])
        self.assertEqual(prepared.scores, {})
        self.assertEqual(prepared.counts["submitted_rows"], 0)

    def test_explicit_zero_is_preserved(self):
        prepared = self.prepare([Prediction("A", OTHER, 0.0)])
        self.assertEqual(prepared.scores, {("A", "F", OTHER): 0.0})

    def test_unknown_and_internal_target_ids_fail(self):
        for query in ("UNKNOWN", "T000000001"):
            with (
                self.subTest(query=query),
                self.assertRaisesRegex(ValueError, "Unknown original target"),
            ):
                self.prepare([Prediction(query, LEAF, 0.4)])

    def test_unresolved_go_is_excluded_and_audited(self):
        result = self.prepare([Prediction("A", "GO:9999999", 0.4)])
        self.assertEqual(result.scores, {})
        self.assertEqual(result.counts["unresolved_rows_excluded"], 1)
        self.assertEqual(result.go_audit[0]["submitted_go_id"], "GO:9999999")
        self.assertEqual(result.go_audit[0]["action"], "EXCLUDED")
        self.assertEqual(result.go_audit[0]["ontology_status"], "unknown")

    def test_unknown_go_does_not_abort_valid_rows(self):
        result = self.prepare(
            [Prediction("A", "GO:9999999", 0.9), Prediction("A", OTHER, 0.4)]
        )
        self.assertEqual(result.scores, {("A", "F", OTHER): 0.4})
        self.assertEqual(result.counts["submitted_rows"], 2)
        self.assertEqual(result.counts["accepted_rows"], 1)
        self.assertEqual(result.go_audit[0]["input_row"], 1)

    def test_already_propagated_predictions_are_idempotent(self):
        direct = self.prepare([Prediction("A", LEAF, 0.8)])
        expanded = self.prepare(
            [Prediction("A", go, 0.8) for go in (LEAF, SKIP, NEUTRAL, ANCESTOR, ROOT)]
        )
        self.assertEqual(expanded.scores, direct.scores)

    def test_unsupported_aspect_is_excluded_and_audited(self):
        result = self.prepare(
            [Prediction("A", LEAF, 0.5)], aspect=lambda _: "UNSUPPORTED"
        )
        self.assertEqual(result.scores, {})
        self.assertEqual(result.counts["unsupported_aspect_rows_excluded"], 1)
        self.assertEqual(result.go_audit[0]["reason"], "UNSUPPORTED_ASPECT")

    def test_invalid_scores_fail_even_for_programmatic_records(self):
        for score in (float("nan"), float("inf"), -0.1, 1.1, True):
            with self.subTest(score=score), self.assertRaises(ValueError):
                self.prepare([Prediction("A", LEAF, score)])

    def test_cross_aspect_closure_fails(self):
        with self.assertRaisesRegex(ValueError, "Cross-aspect"):
            self.prepare(
                [Prediction("A", LEAF, 0.5)],
                ancestors=lambda _: [BP],
            )

    def test_invalid_mask_population_fails(self):
        with self.assertRaisesRegex(ValueError, "mask"):
            self.prepare([], masks={("A", "P", BP): "SKIP"})

    def test_root_only_predictions_leave_no_scorable_terms(self):
        prepared = self.prepare([Prediction("A", ROOT, 1.0)])
        self.assertEqual(prepared.scores, {})
        self.assertEqual(prepared.counts["root_pairs_excluded"], 1)

    def test_input_order_does_not_change_scores(self):
        records = [Prediction("A", LEAF, 0.8), Prediction("B", OTHER, 0.3)]
        self.assertEqual(
            self.prepare(records).scores,
            self.prepare(reversed(records)).scores,
        )

    def test_header_only_input_is_valid(self):
        self.assertEqual(self.read("query_id\tgo_id\tscore\n"), [])

    def test_crlf_and_scientific_notation(self):
        self.assertEqual(
            self.read(f"query_id\tgo_id\tscore\r\nA\t{LEAF}\t8e-1\r\n"),
            [Prediction("A", LEAF, 0.8)],
        )

    def test_invalid_tsv_records_fail(self):
        invalid = (
            "",
            "query_id\tgo_id\tprobability\n",
            "query_id\tgo_id\tscore\textra\n",
            "query_id\tgo_id\tscore\n\n",
            f"query_id\tgo_id\tscore\nA\t{LEAF}\t0.8\textra\n",
            f"query_id\tgo_id\tscore\nA B\t{LEAF}\t0.8\n",
            "query_id\tgo_id\tscore\nA\tGO:1\t0.8\n",
            f"query_id\tgo_id\tscore\nA\t{LEAF}\tNaN\n",
            f"query_id\tgo_id\tscore\nA\t{LEAF}\tinf\n",
            f"query_id\tgo_id\tscore\nA\t{LEAF}\t 0.8\n",
            f"query_id\tgo_id\tscore\nA\t{LEAF}\t1.1\n",
        )
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.read(text)

    def test_symlink_input_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.tsv"
            original.write_text("query_id\tgo_id\tscore\n")
            alias = Path(directory) / "alias.tsv"
            alias.symlink_to(original)
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                list(read_predictions(alias))


class PinnedOntologyResolutionTests(unittest.TestCase):
    """Exercise the actual PROGENY resolver and closure on in-memory terms."""

    def setUp(self):
        namespace = "molecular_function"

        def term(number, **options):
            return OntologyTerm(f"GO:{number:07d}", namespace=namespace, **options)

        ontology = GeneOntology(
            [
                term(3674),
                term(1, alternate_ids=("GO:0000009",)),
                term(2),
                term(3),
                term(4, obsolete=True),
                term(5, deprecated=True, replaced_by=("GO:0000001",)),
                term(6, obsolete=True, consider=("GO:0000001",)),
                term(7, obsolete=True, replaced_by=("GO:0000001", "GO:0000002")),
                term(8, obsolete=True, replaced_by=("GO:0000005",)),
                term(10, obsolete=True, replaced_by=("GO:0000011",)),
                term(11, obsolete=True, replaced_by=("GO:0000010",)),
                term(12, obsolete=True, replaced_by=("GO:9999998",)),
            ],
            [("GO:0000001", "is_a", "GO:0000003")],
        )
        self.inputs = BenchmarkInputs(
            target_ids=frozenset({"A", "B"}),
            eligible=frozenset({("A", "F"), ("B", "F")}),
            truth={
                ("A", "F"): frozenset({"GO:0000001", "GO:0000003"}),
                ("B", "F"): frozenset({"GO:0000002"}),
            },
            masks={},
            species={"A": "9606", "B": "9606"},
            ontology=ontology,
            graph=GoClosureIndex.from_gene_ontology(ontology),
            provenance={},
        )

    def prepare(self, go):
        return prepare_predictions(
            [Prediction("A", go, 0.7)],
            target_ids=self.inputs.target_ids,
            eligible=self.inputs.eligible,
            masks=self.inputs.masks,
            resolve=self.inputs.resolve_prediction,
            aspect=self.inputs.aspect,
            ancestors=self.inputs.graph.ancestors,
        )

    def test_alias_and_replacement_chains_use_pinned_active_go(self):
        for go in ("GO:0000009", "GO:0000005", "GO:0000008"):
            with self.subTest(go=go):
                result = self.prepare(go)
                self.assertEqual(
                    result.scores,
                    {("A", "F", "GO:0000001"): 0.7, ("A", "F", "GO:0000003"): 0.7},
                )
                self.assertEqual(result.go_audit[0]["canonical_go_id"], "GO:0000001")
                self.assertEqual(result.go_audit[0]["action"], "REMAPPED")

    def test_obsolete_without_replacement_is_excluded(self):
        result = self.prepare("GO:0000004")
        self.assertEqual(result.scores, {})
        self.assertEqual(result.go_audit[0]["ontology_status"], "obsolete")

    def test_consider_alone_is_not_an_automatic_replacement(self):
        result = self.prepare("GO:0000006")
        self.assertEqual(result.scores, {})
        self.assertEqual(result.go_audit[0]["candidate_go_ids"], ["GO:0000001"])
        self.assertIsNone(result.go_audit[0]["canonical_go_id"])

    def test_divergent_replacements_are_excluded_without_choosing(self):
        result = self.prepare("GO:0000007")
        self.assertEqual(result.scores, {})
        self.assertEqual(
            result.go_audit[0]["candidate_go_ids"],
            ["GO:0000001", "GO:0000002"],
        )

    def test_replacement_cycles_and_missing_destinations_are_excluded(self):
        for go in ("GO:0000010", "GO:0000012"):
            with self.subTest(go=go):
                self.assertEqual(self.prepare(go).scores, {})

    def test_go_absent_from_pinned_ontology_is_excluded(self):
        result = self.prepare("GO:9999999")
        self.assertEqual(result.scores, {})
        self.assertEqual(result.go_audit[0]["ontology_status"], "unknown")

    def test_all_excluded_submission_retains_full_truth_and_population(self):
        before = dict(self.inputs.truth)
        result = self.prepare("GO:9999999")
        self.assertEqual(result.scores, {})
        self.assertEqual(self.inputs.truth, before)
        self.assertEqual(len(self.inputs.eligible), 2)


if __name__ == "__main__":
    unittest.main()
