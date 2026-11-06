"""Small independent examples for evaluator policy options."""

from __future__ import annotations

import math

from progeny.prediction_contract import GoResolution, Prediction, prepare_predictions
from progeny.prediction_exclusions import apply_exclusions
from progeny.prediction_metrics import evaluate_scores
from progeny.prediction_weighted_metrics import evaluate_weighted_scores

ROOT = "GO:0003674"
LEFT = "GO:0000001"
RIGHT = "GO:0000002"
LEAF = "GO:0000003"


def test_fill_respects_positive_ancestor_and_multiple_parent_paths():
    parents = {ROOT: (), LEFT: (ROOT,), RIGHT: (ROOT,), LEAF: (LEFT, RIGHT)}
    ancestors = {ROOT: (), LEFT: (ROOT,), RIGHT: (ROOT,), LEAF: (LEFT, RIGHT, ROOT)}
    records = [
        Prediction("q", LEAF, 0.9),
        Prediction("q", LEFT, 0.2),
        Prediction("q", RIGHT, 0.0),
    ]
    kwargs = {
        "target_ids": frozenset({"q"}),
        "eligible": frozenset({("q", "F")}),
        "masks": {},
        "resolve": lambda go: GoResolution(go, "active"),
        "aspect": lambda go: "F",
        "ancestors": ancestors.__getitem__,
        "direct_parents": parents.__getitem__,
    }
    filled = prepare_predictions(records, propagation="fill", **kwargs).scores
    maximal = prepare_predictions(records, propagation="max", **kwargs).scores
    assert filled["q", "F", LEFT] == 0.2
    assert filled["q", "F", RIGHT] == 0.9
    assert maximal["q", "F", LEFT] == 0.9
    assert filled["q", "F", LEAF] == maximal["q", "F", LEAF] == 0.9


def test_micro_uses_pooled_pairs_and_weighted_pooled_ia():
    truth = {("a", "F"): {LEFT, RIGHT}, ("b", "F"): {LEAF}}
    scores = {
        ("a", "F", LEFT): 0.9,
        ("a", "F", LEAF): 0.9,
        ("b", "F", LEAF): 0.9,
    }
    args = {
        "eligible": set(truth),
        "truth": truth,
        "scores": scores,
        "species": {"a": "9606", "b": "9606"},
        "aspects": ["F"],
        "thresholds": [0.5],
    }
    raw = evaluate_scores(**args)["aspects"]["F"]["curve"][0]
    assert raw["micro_precision"] == 2 / 3
    assert raw["micro_recall"] == 2 / 3
    assert raw["micro_f1"] == 2 / 3
    weighted = evaluate_weighted_scores(
        **args, information_accretion={LEFT: 2.0, RIGHT: 3.0, LEAF: 5.0}
    )["F"]["curve"][0]
    assert math.isclose(weighted["weighted_micro_precision"], 7 / 12)
    assert math.isclose(weighted["weighted_micro_recall"], 7 / 10)


def test_exact_exclusion_removes_empty_truth_aspect_without_descendants():
    eligible = {("a", "F"), ("b", "F")}
    truth = {("a", "F"): {LEFT}, ("b", "F"): {LEAF}}
    scores = {("a", "F", LEFT): 0.8, ("b", "F", LEAF): 0.9}
    kept, filtered_truth, filtered_scores, audit = apply_exclusions(
        eligible,
        truth,
        scores,
        {"path": "ids.txt", "sha256": "x", "go_ids": [LEFT]},
    )
    assert kept == {("b", "F")}
    assert filtered_truth[("b", "F")] == {LEAF}
    assert filtered_scores == {("b", "F", LEAF): 0.9}
    assert audit["empty_truth_target_aspects"] == [{"query_id": "a", "aspect": "F"}]


def test_excluding_ancestor_keeps_descendant_for_same_target():
    eligible = {("a", "F"), ("a", "P"), ("b", "F")}
    truth = {("a", "F"): {LEFT, LEAF}, ("a", "P"): {LEFT}, ("b", "F"): {LEFT}}
    scores = {
        ("a", "F", LEFT): 0.9,
        ("a", "F", LEAF): 0.8,
        ("b", "F", LEAF): 0.7,
    }
    kept, filtered_truth, filtered_scores, audit = apply_exclusions(
        eligible, truth, scores, {"path": None, "sha256": None, "go_ids": [LEFT]}
    )
    assert kept == {("a", "F")}
    assert filtered_truth == {("a", "F"): {LEAF}}
    assert filtered_scores == {("a", "F", LEAF): 0.8}
    assert audit["empty_truth_target_aspects"] == [
        {"query_id": "a", "aspect": "P"},
        {"query_id": "b", "aspect": "F"},
    ]
    assert (audit["truth_pairs_before"], audit["truth_pairs_after"]) == (4, 1)
    assert (audit["prediction_pairs_before"], audit["prediction_pairs_after"]) == (3, 1)
