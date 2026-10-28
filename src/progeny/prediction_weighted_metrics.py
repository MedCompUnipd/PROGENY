"""CAFA-style IA-weighted curves for prepared PROGENY predictions."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence, Set
from numbers import Real

from progeny.prediction_contract import ASPECTS, GO_ID, ROOTS, Pair, TermKey


class _CompensatedSum:
    def __init__(self) -> None:
        self.total = 0.0
        self.correction = 0.0

    def add(self, value: float) -> None:
        adjusted = value - self.correction
        total = self.total + adjusted
        self.correction = (total - self.total) - adjusted
        self.total = total


def _harmonic(precision: float, recall: float) -> float:
    total = precision + recall
    return 2 * precision * recall / total if total else 0.0


def _valid_taxid(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.isascii()
        and value.isdecimal()
        and not value.startswith("0")
    )


def _unit(value: float) -> float:
    if not -1e-12 <= value <= 1 + 1e-12:
        raise ArithmeticError("Weighted macro metric outside [0, 1]")
    return max(0.0, min(1.0, value))


def _best(curve: list[dict], field: str, *, maximize: bool) -> dict:
    if not curve:
        return {"value": None, "threshold": None}
    if maximize:
        point = max(curve, key=lambda row: (row[field], row["threshold"]))
    else:
        point = min(curve, key=lambda row: (row[field], -row["threshold"]))
    return {"value": point[field], "threshold": point["threshold"]}


def evaluate_weighted_scores(
    *,
    eligible: Set[Pair],
    truth: Mapping[Pair, Set[str]],
    scores: Mapping[TermKey, float],
    information_accretion: Mapping[str, float],
    species: Mapping[str, str],
    aspects: Sequence[str],
    thresholds: Sequence[float],
    taxids: Set[str] | None = None,
) -> dict[str, dict]:
    """Compute weighted P/R/F and Smin on one shared threshold grid.

    The normalization follows the CAFA profile: weighted precision is macro
    over targets with positive predicted IA; weighted recall and RU/MI use all
    eligible targets in that aspect. Predictions are already propagated and
    masked by M1.
    """
    if not aspects or len(set(aspects)) != len(aspects) or not set(aspects) <= ASPECTS:
        raise ValueError("Aspects must be distinct F, P or C values")
    if set(truth) != set(eligible) or any(not truth[pair] for pair in eligible):
        raise ValueError("Truth must cover exactly the nonempty eligible population")
    if taxids is not None and (
        not taxids
        or any(
            not isinstance(taxid, str)
            or not taxid.isascii()
            or not taxid.isdecimal()
            or taxid.startswith("0")
            for taxid in taxids
        )
    ):
        raise ValueError("TaxID filters must be nonempty positive decimal strings")
    if not thresholds or any(
        not isinstance(tau, Real)
        or isinstance(tau, bool)
        or not math.isfinite(tau)
        or not 0 <= tau < 1
        for tau in thresholds
    ):
        raise ValueError("CAFA thresholds must be finite numbers in [0, 1)")
    threshold_values = tuple(sorted({float(tau) for tau in thresholds}, reverse=True))
    selected_aspects = tuple(value for value in ("F", "P", "C") if value in aspects)
    selected = {
        pair for pair in eligible if taxids is None or species.get(pair[0]) in taxids
    }
    selected_pairs = {
        aspect: sorted(pair for pair in selected if pair[1] == aspect)
        for aspect in selected_aspects
    }
    for pair in eligible:
        if not _valid_taxid(species.get(pair[0])):
            raise ValueError("Missing original target species TaxID")
        if pair not in truth or not truth[pair]:
            raise ValueError("Every eligible pair requires nonempty EVAL truth")
    for go in {go for values in truth.values() for go in values}:
        if go not in information_accretion:
            raise ValueError(f"IA table lacks EVAL term: {go}")
    for key, score in scores.items():
        if (
            not isinstance(key, tuple)
            or len(key) != 3
            or key[:2] not in eligible
            or not isinstance(key[2], str)
            or not GO_ID.fullmatch(key[2])
            or key[2] in ROOTS
            or not isinstance(score, Real)
            or isinstance(score, bool)
            or not math.isfinite(score)
            or not 0 <= score <= 1
        ):
            raise ValueError("Invalid M1-prepared score record")
        if key[2] not in information_accretion:
            raise ValueError(f"IA table lacks predicted term: {key[2]}")
    if any(
        not isinstance(term, str)
        or not GO_ID.fullmatch(term)
        or isinstance(weight, bool)
        or not isinstance(weight, Real)
        or not math.isfinite(weight)
        or weight < 0
        for term, weight in information_accretion.items()
    ):
        raise ValueError("IA values must be finite nonnegative GO term weights")

    reports = {}
    for aspect in selected_aspects:
        pairs = selected_pairs[aspect]
        queries = [query for query, _ in pairs]
        population = len(queries)
        truth_by_query = {query: truth[(query, aspect)] for query in queries}
        truth_weight = {
            query: math.fsum(information_accretion[go] for go in truth_by_query[query])
            for query in queries
        }
        events = sorted(
            (
                float(score),
                query,
                go,
                float(information_accretion[go]),
                go in truth_by_query[query],
            )
            for (query, score_aspect, go), score in scores.items()
            if score_aspect == aspect and (query, score_aspect) in selected
        )
        events.sort(key=lambda row: (-row[0], row[1], row[2]))
        predictions = {query: 0.0 for query in queries}
        unweighted_predictions = {query: 0 for query in queries}
        true_positive = {query: 0.0 for query in queries}
        precision_sum = _CompensatedSum()
        recall_sum = _CompensatedSum()
        false_negative_sum = math.fsum(truth_weight.values())
        false_positive_sum = 0.0
        covered = 0
        unweighted_covered = 0
        position = 0
        curve = []
        thresholds_to_evaluate = threshold_values if population else ()
        for threshold in thresholds_to_evaluate:
            changes: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
            while position < len(events) and events[position][0] >= threshold:
                _, query, _, weight, is_true = events[position]
                changes[query][0] += weight
                changes[query][2] += 1
                if is_true:
                    changes[query][1] += weight
                else:
                    false_positive_sum += weight
                position += 1
            for query in sorted(changes):
                added_prediction, added_true, added_count = changes[query]
                old_prediction = predictions[query]
                old_true = true_positive[query]
                old_precision = old_true / old_prediction if old_prediction else 0.0
                predictions[query] += added_prediction
                unweighted_predictions[query] += int(added_count)
                true_positive[query] += added_true
                if old_prediction == 0 and predictions[query] > 0:
                    covered += 1
                new_precision = (
                    true_positive[query] / predictions[query]
                    if predictions[query]
                    else 0.0
                )
                precision_sum.add(new_precision - old_precision)
                denominator = truth_weight[query]
                if denominator:
                    recall_sum.add(added_true / denominator)
                false_negative_sum -= added_true
                if unweighted_predictions[query] == int(added_count):
                    unweighted_covered += 1
            weighted_precision = _unit(
                precision_sum.total / covered if covered else 0.0
            )
            weighted_recall = _unit(
                recall_sum.total / population if population else 0.0
            )
            if false_negative_sum < -1e-10:
                raise ArithmeticError("Weighted false negatives became negative")
            ru = max(0.0, false_negative_sum) / population if population else None
            mi = false_positive_sum / population if population else None
            curve.append(
                {
                    "threshold": threshold,
                    "weighted_precision": weighted_precision,
                    "weighted_recall": weighted_recall,
                    "weighted_f1": _harmonic(weighted_precision, weighted_recall),
                    "weighted_coverage": covered / population if population else None,
                    "weighted_covered_targets": covered,
                    "scorable_targets": unweighted_covered,
                    "coverage": (
                        unweighted_covered / population if population else None
                    ),
                    "ru": ru,
                    "mi": mi,
                    "smin": math.hypot(ru, mi) if population else None,
                }
            )
        scorable_curve = [row for row in curve if row["scorable_targets"] > 0]
        reports[aspect] = {
            "status": (
                "NO_ELIGIBLE_TARGETS"
                if not population
                else "NO_SCORABLE_PREDICTIONS"
                if not scorable_curve
                else "EVALUATED"
            ),
            "eligible_targets": population,
            "truth_ia_sum": math.fsum(truth_weight.values()),
            "weighted_fmax": (
                _best(scorable_curve, "weighted_f1", maximize=True)
                if scorable_curve
                else {"value": None, "threshold": None}
            ),
            "smin": (
                _best(scorable_curve, "smin", maximize=False)
                if scorable_curve
                else {"value": None, "threshold": None}
            ),
            "curve": curve,
        }
    return reports
