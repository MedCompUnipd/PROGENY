"""Hand-derived macro metrics and an independent exact rational oracle."""

from __future__ import annotations

import copy
import json
import math
import random
import unittest
from fractions import Fraction

from progeny.prediction_metrics import evaluate_scores, threshold_grid


def go(number):
    return f"GO:{number:07d}"


def oracle(truth, scores, queries, aspect, threshold):
    """Deliberately rescan sets; independent of the production event sweep."""
    precision_sum = Fraction(0)
    recall_sum = Fraction(0)
    covered = tp = fp = fn = 0
    for query in queries:
        actual = truth[(query, aspect)]
        predicted = {
            term
            for (target, value, term), score in scores.items()
            if target == query and value == aspect and score >= threshold
        }
        hits = len(actual & predicted)
        tp += hits
        fp += len(predicted - actual)
        fn += len(actual - predicted)
        recall_sum += Fraction(hits, len(actual))
        if predicted:
            covered += 1
            precision_sum += Fraction(hits, len(predicted))
    precision = precision_sum / covered if covered else Fraction(0)
    recall_full = recall_sum / len(queries)
    recall_covered = recall_sum / covered if covered else Fraction(0)

    def harmonic(recall):
        return (
            2 * precision * recall / (precision + recall) if precision + recall else 0
        )

    return {
        "threshold": threshold,
        "covered_targets": covered,
        "coverage": covered / len(queries),
        "tp": tp,
        "operational_fp": fp,
        "fn": fn,
        "precision": float(precision),
        "recall_full": float(recall_full),
        "f1_full": float(harmonic(recall_full)),
        "recall_covered": float(recall_covered),
        "f1_covered": float(harmonic(recall_covered)),
    }


class PredictionMetricsTests(unittest.TestCase):
    def evaluate(self, scores=None, truth=None, **options):
        if truth is None:
            truth = {("A", "F"): {go(1)}, ("B", "F"): {go(1)}}
        parameters = {
            "eligible": frozenset(truth),
            "truth": truth,
            "scores": scores or {},
            "species": {"A": "9606", "B": "10090"},
        }
        parameters.update(options)
        return evaluate_scores(**parameters)

    def test_perfect_prediction_and_highest_threshold_tie(self):
        report = self.evaluate({("A", "F", go(1)): 0.8, ("B", "F", go(1)): 0.8})
        result = report["aspects"]["F"]
        self.assertEqual(result["full"]["fmax"], 1.0)
        self.assertEqual(result["full"]["threshold"], 0.8)
        self.assertEqual(result["full"]["coverage"], 1.0)
        self.assertEqual(result["thresholds_examined"], 3)

    def test_full_denominator_includes_target_without_predictions(self):
        result = self.evaluate({("A", "F", go(1)): 0.9})["aspects"]["F"]
        self.assertEqual(result["eligible_targets"], 2)
        self.assertEqual(result["full"]["precision"], 1.0)
        self.assertEqual(result["full"]["recall"], 0.5)
        self.assertAlmostEqual(result["full"]["fmax"], 2 / 3)
        self.assertEqual(result["full"]["coverage"], 0.5)
        self.assertEqual(result["covered_normalization_secondary"]["fmax"], 1.0)

    def test_macro_is_not_micro_or_mean_of_target_f1(self):
        truth = {("A", "F"): {go(1)}, ("B", "F"): {go(i) for i in range(1, 5)}}
        scores = {
            ("A", "F", go(1)): 0.8,
            ("A", "F", go(5)): 0.8,
            ("A", "F", go(6)): 0.8,
            ("B", "F", go(1)): 0.8,
        }
        result = self.evaluate(scores, truth)["aspects"]["F"]
        self.assertAlmostEqual(result["full"]["precision"], 2 / 3)
        self.assertAlmostEqual(result["full"]["recall"], 5 / 8)
        self.assertAlmostEqual(result["full"]["fmax"], 20 / 31)
        self.assertNotAlmostEqual(result["full"]["fmax"], 4 / 9)
        self.assertNotAlmostEqual(result["full"]["fmax"], 0.45)

    def test_threshold_is_global_not_optimized_for_each_target(self):
        scores = {
            ("A", "F", go(2)): 0.9,
            ("A", "F", go(1)): 0.1,
            ("B", "F", go(1)): 0.9,
            ("B", "F", go(2)): 0.1,
        }
        result = self.evaluate(scores)["aspects"]["F"]
        self.assertAlmostEqual(result["full"]["fmax"], 2 / 3)
        self.assertEqual(result["full"]["threshold"], 0.1)

    def test_equal_score_group_is_activated_atomically(self):
        truth = {("A", "F"): {go(1)}}
        scores = {("A", "F", go(1)): 0.5, ("A", "F", go(2)): 0.5}
        result = self.evaluate(scores, truth)["aspects"]["F"]
        self.assertAlmostEqual(result["full"]["fmax"], 2 / 3)
        self.assertEqual([row["threshold"] for row in result["curve"]], [1, 0.5, 0])

    def test_zero_threshold_does_not_create_absent_predictions(self):
        result = self.evaluate({("A", "F", go(1)): 0.8})["aspects"]["F"]
        point = result["curve"][-1]
        self.assertEqual(point["threshold"], 0)
        self.assertEqual(point["covered_targets"], 1)
        self.assertEqual((point["tp"], point["operational_fp"], point["fn"]), (1, 0, 1))

    def test_explicit_zero_counts_only_at_zero(self):
        result = self.evaluate({("A", "F", go(1)): 0.0})["aspects"]["F"]
        self.assertEqual(result["curve"][0]["covered_targets"], 0)
        self.assertEqual(result["curve"][-1]["covered_targets"], 1)
        self.assertEqual(result["full"]["threshold"], 0)
        self.assertAlmostEqual(result["full"]["fmax"], 2 / 3)
        self.assertEqual(result["coverage_any_score"], 0.5)

    def test_threshold_includes_exact_equality(self):
        result = self.evaluate(
            {("A", "F", go(1)): 0.5},
            thresholds=(math.nextafter(0.5, 1), 0.5),
        )["aspects"]["F"]
        self.assertEqual(result["curve"][0]["tp"], 0)
        self.assertEqual(result["curve"][1]["tp"], 1)

    def test_no_predictions_has_zero_metrics_and_full_false_negatives(self):
        result = self.evaluate()["aspects"]["F"]
        self.assertEqual(result["status"], "NO_SCORABLE_PREDICTIONS")
        self.assertEqual(result["full"]["fmax"], 0)
        self.assertEqual(result["full"]["threshold"], 1)
        self.assertTrue(all(row["fn"] == 2 for row in result["curve"]))

    def test_no_eligible_aspect_has_null_metrics(self):
        result = self.evaluate()["aspects"]["P"]
        self.assertEqual(result["status"], "NO_ELIGIBLE_TARGETS")
        self.assertIsNone(result["full"]["fmax"])
        self.assertIsNone(result["full"]["threshold"])
        self.assertIsNone(result["coverage_any_score"])
        self.assertEqual(result["curve"], [])
        json.dumps(result, allow_nan=False)

    def test_taxid_filter_changes_truth_denominator_and_predictions(self):
        scores = {("A", "F", go(1)): 0.8, ("B", "F", go(2)): 0.9}
        result = self.evaluate(scores, taxids=frozenset({"9606"}))
        self.assertEqual(result["population_after_filters"]["target_aspects"], 1)
        self.assertEqual(result["aspects"]["F"]["full"]["fmax"], 1)
        self.assertEqual(result["aspects"]["F"]["scorable_pairs"], 1)

    def test_multiple_taxids_use_union(self):
        scores = {("A", "F", go(1)): 0.8}
        result = self.evaluate(scores, taxids=frozenset({"9606", "10090"}))
        self.assertEqual(result["population_after_filters"]["evaluable_targets"], 2)

    def test_unrepresented_taxid_is_explicit_empty_population(self):
        result = self.evaluate(taxids=frozenset({"999999"}))
        self.assertEqual(result["status"], "NO_ELIGIBLE_TARGETS")
        self.assertEqual(result["filters"]["taxids_not_in_evaluable_fasta"], ["999999"])
        self.assertIsNone(result["aspects"]["F"]["full"]["fmax"])

    def test_protein_and_target_aspect_counts_are_distinct(self):
        truth = {("A", "F"): {go(1)}, ("A", "P"): {go(2)}}
        result = self.evaluate(truth=truth)
        self.assertEqual(
            result["population_before_filters"],
            {
                "evaluable_targets": 1,
                "target_aspects": 2,
            },
        )
        self.assertEqual(result["aspects"]["F"]["eligible_targets"], 1)
        self.assertEqual(result["aspects"]["P"]["eligible_targets"], 1)

    def test_aspect_selection_changes_both_population_counts(self):
        truth = {("A", "F"): {go(1)}, ("B", "P"): {go(2)}}
        result = self.evaluate(truth=truth, aspects=("P",))
        self.assertEqual(list(result["aspects"]), ["P"])
        self.assertEqual(result["population_after_filters"]["evaluable_targets"], 1)

    def test_exact_sweep_can_find_optimum_between_grid_points(self):
        truth = {("A", "F"): {go(1)}}
        scores = {("A", "F", go(1)): 0.505, ("A", "F", go(2)): 0.504}
        exact = self.evaluate(scores, truth)["aspects"]["F"]
        grid = self.evaluate(scores, truth, thresholds=threshold_grid("0.01"))
        self.assertEqual(exact["full"]["fmax"], 1)
        self.assertAlmostEqual(grid["aspects"]["F"]["full"]["fmax"], 2 / 3)
        self.assertEqual(grid["threshold_policy"]["mode"], "explicit_thresholds")

    def test_grid_decimal_values_and_endpoints(self):
        self.assertEqual(threshold_grid("0.3"), (1.0, 0.9, 0.6, 0.3, 0.0))
        self.assertEqual(len(threshold_grid("0.01")), 101)
        self.assertEqual(len(threshold_grid("0.0001")), 10001)
        self.assertEqual(threshold_grid("1"), (1.0, 0.0))

    def test_invalid_grids_fail(self):
        for step in ("0", "-1", "NaN", "inf", "0.00001", "2", "bad", " 0.1", True):
            with self.subTest(step=step), self.assertRaises(ValueError):
                threshold_grid(step)

    def test_invalid_thresholds_fail(self):
        for values in ((), (float("nan"),), (float("inf"),), (-0.1,), (1.1,), (True,)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.evaluate(thresholds=values)

    def test_invalid_aspects_fail(self):
        for aspects in ((), ("MF",), ("F", "F")):
            with self.subTest(aspects=aspects), self.assertRaises(ValueError):
                self.evaluate(aspects=aspects)

    def test_invalid_taxid_filters_fail(self):
        for taxids in (frozenset(), frozenset({"0"}), frozenset({"09606"}), "9606"):
            with self.subTest(taxids=taxids), self.assertRaises(ValueError):
                self.evaluate(taxids=taxids)

    def test_truth_must_cover_full_eligible_population(self):
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.evaluate(eligible=frozenset({("A", "F")}))

    def test_empty_truth_and_root_truth_fail(self):
        for values in (set(), {"GO:0003674"}, {"bad"}, {None}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.evaluate(truth={("A", "F"): values})

    def test_missing_target_species_fails(self):
        with self.assertRaisesRegex(ValueError, "species"):
            self.evaluate(species={"A": "9606"})

    def test_invalid_or_unprepared_scores_fail_even_outside_filter(self):
        cases = (
            {("UNKNOWN", "F", go(1)): 0.9},
            {("A", "P", go(1)): 0.9},
            {("A", "F", "GO:0003674"): 0.9},
            {("A", "F", "bad"): 0.9},
            {("A", "F", go(1)): float("nan")},
            {("A", "F", go(1)): -0.1},
            {("A", "F", go(1)): True},
        )
        for scores in cases:
            with self.subTest(scores=scores), self.assertRaises(ValueError):
                self.evaluate(scores, taxids=frozenset({"999999"}))

    def test_input_order_is_irrelevant_and_inputs_are_unchanged(self):
        scores = {("B", "F", go(2)): 0.8, ("A", "F", go(1)): 0.4}
        truth = {("A", "F"): {go(1)}, ("B", "F"): {go(1)}}
        before = copy.deepcopy((scores, truth))
        first = self.evaluate(scores, truth)
        second = self.evaluate(dict(reversed(list(scores.items()))), truth)
        self.assertEqual(first, second)
        self.assertEqual((scores, truth), before)

    def test_exact_fmax_is_invariant_under_order_preserving_rescaling(self):
        scores = {("A", "F", go(1)): 0.8, ("B", "F", go(2)): 0.4}
        original = self.evaluate(scores)["aspects"]["F"]["full"]["fmax"]
        rescaled = self.evaluate({key: value / 2 for key, value in scores.items()})
        self.assertEqual(rescaled["aspects"]["F"]["full"]["fmax"], original)

    def test_smin_remains_explicitly_unavailable(self):
        result = self.evaluate()
        self.assertEqual(
            result["smin_status"],
            "NOT_COMPUTED_PENDING_CERTIFIED_INFORMATION_ACCRETION",
        )

    def test_long_decreasing_precision_sweep_stays_numerically_stable(self):
        scores = {("A", "F", go(i + 10000)): 1 - (i - 1) / 5000 for i in range(1, 5001)}
        result = self.evaluate(scores, {("A", "F"): {go(10001)}})["aspects"]["F"]
        self.assertEqual(result["full"]["fmax"], 1)
        self.assertAlmostEqual(result["curve"][-1]["precision"], 1 / 5000, places=12)
        self.assertEqual(result["curve"][-1]["operational_fp"], 4999)

    def test_sweep_matches_independent_rational_oracle(self):
        for seed in range(20):
            rng = random.Random(seed)
            truth = {}
            scores = {}
            species = {f"Q{i}": "9606" if i % 2 else "10090" for i in range(6)}
            for query in species:
                for aspect in ("F", "P", "C"):
                    if rng.random() < 0.3:
                        continue
                    truth[(query, aspect)] = {go(i) for i in rng.sample(range(1, 9), 3)}
                    for term in rng.sample(range(1, 12), rng.randrange(7)):
                        scores[(query, aspect, go(term))] = rng.choice(
                            (0, 0.1, 0.5, 0.9, 1)
                        )
            taxids = frozenset({"9606"}) if seed % 2 else None
            thresholds = threshold_grid("0.2") if seed % 3 else None
            report = evaluate_scores(
                eligible=frozenset(truth),
                truth=truth,
                scores=scores,
                species=species,
                taxids=taxids,
                thresholds=thresholds,
            )
            for aspect, result in report["aspects"].items():
                queries = sorted(
                    query
                    for query, value in truth
                    if value == aspect and (taxids is None or species[query] in taxids)
                )
                expected_points = []
                for point in result["curve"]:
                    expected = oracle(
                        truth, scores, queries, aspect, point["threshold"]
                    )
                    expected_points.append(expected)
                    for key, value in expected.items():
                        with self.subTest(seed=seed, aspect=aspect, key=key):
                            self.assertAlmostEqual(point[key], value, places=12)
                if expected_points:
                    self.assertAlmostEqual(
                        result["full"]["fmax"],
                        max(point["f1_full"] for point in expected_points),
                        places=12,
                    )


if __name__ == "__main__":
    unittest.main()
