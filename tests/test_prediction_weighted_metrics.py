from __future__ import annotations

import math

import pytest

from progeny.prediction_weighted_metrics import evaluate_weighted_scores


def _inputs():
    eligible = {("Q1", "F"), ("Q2", "F")}
    truth = {
        ("Q1", "F"): {"GO:0000001"},
        ("Q2", "F"): {"GO:0000002"},
    }
    scores = {
        ("Q1", "F", "GO:0000001"): 0.9,
        ("Q1", "F", "GO:0000003"): 0.8,
        ("Q2", "F", "GO:0000002"): 0.7,
    }
    weights = {
        "GO:0000001": 2.0,
        "GO:0000002": 1.0,
        "GO:0000003": 1.0,
    }
    species = {"Q1": "9606", "Q2": "10090"}
    return eligible, truth, scores, weights, species


def test_weighted_curves_use_macro_cafa_normalization() -> None:
    eligible, truth, scores, weights, species = _inputs()
    result = evaluate_weighted_scores(
        eligible=eligible,
        truth=truth,
        scores=scores,
        information_accretion=weights,
        species=species,
        aspects=("F",),
        thresholds=(0.8, 0.5, 0.01),
    )["F"]
    first = result["curve"][0]
    assert first["threshold"] == 0.8
    assert math.isclose(first["weighted_precision"], 2 / 3)
    assert math.isclose(first["weighted_recall"], 0.5)
    assert math.isclose(first["ru"], 0.5)
    assert math.isclose(first["mi"], 0.5)
    assert math.isclose(first["smin"], math.sqrt(0.5))
    second = result["curve"][1]
    assert second["threshold"] == 0.5
    assert math.isclose(second["weighted_precision"], 5 / 6)
    assert second["weighted_recall"] == 1.0
    assert result["weighted_fmax"]["threshold"] == 0.5
    assert result["smin"]["threshold"] == 0.5


def test_taxid_filter_applies_to_truth_and_predictions() -> None:
    eligible, truth, scores, weights, species = _inputs()
    result = evaluate_weighted_scores(
        eligible=eligible,
        truth=truth,
        scores=scores,
        information_accretion=weights,
        species=species,
        aspects=("F",),
        thresholds=(0.5,),
        taxids={"9606"},
    )["F"]
    assert result["eligible_targets"] == 1
    assert result["curve"][0]["weighted_recall"] == 1.0
    assert result["curve"][0]["ru"] == 0.0


def test_missing_term_weight_is_fail_closed() -> None:
    eligible, truth, scores, weights, species = _inputs()
    del weights["GO:0000003"]
    with pytest.raises(ValueError, match="IA table lacks predicted term"):
        evaluate_weighted_scores(
            eligible=eligible,
            truth=truth,
            scores=scores,
            information_accretion=weights,
            species=species,
            aspects=("F",),
            thresholds=(0.5,),
        )


def test_empty_taxid_population_has_null_scalar_metrics() -> None:
    eligible, truth, scores, weights, species = _inputs()
    result = evaluate_weighted_scores(
        eligible=eligible,
        truth=truth,
        scores=scores,
        information_accretion=weights,
        species=species,
        aspects=("F",),
        thresholds=(0.5,),
        taxids={"999"},
    )["F"]
    assert result["eligible_targets"] == 0
    assert result["weighted_fmax"] == {"value": None, "threshold": None}
    assert result["smin"] == {"value": None, "threshold": None}


def test_rejects_invalid_threshold_endpoint() -> None:
    eligible, truth, scores, weights, species = _inputs()
    with pytest.raises(ValueError, match=r"\[0, 1\)"):
        evaluate_weighted_scores(
            eligible=eligible,
            truth=truth,
            scores=scores,
            information_accretion=weights,
            species=species,
            aspects=("F",),
            thresholds=(1.0,),
        )
