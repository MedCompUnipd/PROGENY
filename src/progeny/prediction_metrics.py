"""PROGENY macro metrics on already propagated and masked prediction scores.

This module never changes truth, propagates scores, or invents absent pairs.
The threshold sweep is sparse: each submitted scorable pair is activated once.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence, Set
from decimal import Decimal, InvalidOperation
from numbers import Real

from progeny.prediction_contract import ASPECTS, GO_ID, ROOTS, Pair, TermKey

SCHEMA = "progeny-prediction-macro-metrics-v1"
ASPECT_ORDER = ("F", "P", "C")
MAX_GRID_POINTS = 10001


def _taxid(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.isascii()
        and value.isdecimal()
        and not value.startswith("0")
    )


def threshold_grid(step: str) -> tuple[float, ...]:
    """An explicit PROGENY grid includes 0, 1 and decimal multiples of step."""
    if not isinstance(step, str) or not step or step.strip() != step:
        raise ValueError("Threshold step must be a decimal string")
    try:
        increment = Decimal(step)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid threshold step") from exc
    if not increment.is_finite() or not Decimal("0.0001") <= increment <= Decimal(1):
        raise ValueError("Threshold step must be between 0.0001 and 1")
    values = {0.0, 1.0}
    for index in range(1, MAX_GRID_POINTS):
        value = increment * index
        if value >= 1:
            break
        values.add(float(value))
    if len(values) > MAX_GRID_POINTS:
        raise ValueError("Too many grid thresholds")
    return tuple(sorted(values, reverse=True))


class _Sum:
    """Compensated updates to per-target macro sums in deterministic order."""

    def __init__(self) -> None:
        self.value = 0.0
        self.correction = 0.0

    def add(self, value: float) -> None:
        adjusted = value - self.correction
        total = self.value + adjusted
        self.correction = (total - self.value) - adjusted
        self.value = total


def _ratio(numerator: float, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    value = numerator / denominator
    if not -1e-12 <= value <= 1 + 1e-12:
        raise ArithmeticError("Macro metric outside numerical tolerance")
    return max(0.0, min(1.0, value))


def _harmonic(precision: float, recall: float) -> float:
    total = precision + recall
    return 2 * precision * recall / total if total else 0.0


def _best(curve: list[dict], *, covered: bool) -> dict:
    f_key = "f1_covered" if covered else "f1_full"
    r_key = "recall_covered" if covered else "recall_full"
    if not curve:
        return dict.fromkeys(
            ("fmax", "threshold", "precision", "recall", "coverage", "covered_targets")
        )
    point = max(curve, key=lambda row: (row[f_key], row["threshold"]))
    return {
        "fmax": point[f_key],
        "threshold": point["threshold"],
        "precision": point["precision"],
        "recall": point[r_key],
        "coverage": point["coverage"],
        "covered_targets": point["covered_targets"],
    }


def _aspect_metrics(
    *,
    aspect: str,
    truth: Mapping[Pair, Set[str]],
    queries: list[str],
    events: list[tuple[float, str, str]],
    thresholds: tuple[float, ...] | None,
) -> dict:
    population = len(queries)
    truth_size = {query: len(truth[(query, aspect)]) for query in queries}
    truth_terms = sum(truth_size.values())
    events.sort(key=lambda item: (-item[0], item[1], item[2]))
    if thresholds is None:
        thresholds = tuple(
            sorted({0.0, 1.0, *(row[0] for row in events)}, reverse=True)
        )
    curve = []
    n_pred: dict[str, int] = defaultdict(int)
    n_tp: dict[str, int] = defaultdict(int)
    precision_sum = _Sum()
    recall_sum = _Sum()
    covered_targets = total_predictions = total_tp = position = 0
    if population:
        for tau in thresholds:
            changes: dict[str, list[int]] = {}
            while position < len(events) and events[position][0] >= tau:
                _, query, go = events[position]
                delta = changes.setdefault(query, [0, 0])
                delta[0] += 1
                delta[1] += go in truth[(query, aspect)]
                position += 1
            for query in sorted(changes):
                added, hits = changes[query]
                old_n, old_tp = n_pred[query], n_tp[query]
                old_precision = old_tp / old_n if old_n else 0.0
                n_pred[query] += added
                n_tp[query] += hits
                if old_n == 0:
                    covered_targets += 1
                precision_sum.add(n_tp[query] / n_pred[query] - old_precision)
                recall_sum.add(hits / truth_size[query])
                total_predictions += added
                total_tp += hits
            precision = _ratio(precision_sum.value, covered_targets)
            recall_full = _ratio(recall_sum.value, population)
            recall_covered = _ratio(recall_sum.value, covered_targets)
            curve.append(
                {
                    "threshold": tau,
                    "covered_targets": covered_targets,
                    "coverage": covered_targets / population,
                    "tp": total_tp,
                    "operational_fp": total_predictions - total_tp,
                    "fn": truth_terms - total_tp,
                    "precision": precision,
                    "recall_full": recall_full,
                    "f1_full": _harmonic(precision, recall_full),
                    "recall_covered": recall_covered,
                    "f1_covered": _harmonic(precision, recall_covered),
                }
            )
    any_covered = len({query for _, query, _ in events})
    return {
        "aspect": aspect,
        "status": (
            "NO_ELIGIBLE_TARGETS"
            if not population
            else "NO_SCORABLE_PREDICTIONS"
            if not events
            else "EVALUATED"
        ),
        "eligible_targets": population,
        "truth_terms": truth_terms,
        "scorable_pairs": len(events),
        "covered_targets_any_score": any_covered,
        "coverage_any_score": any_covered / population if population else None,
        "thresholds_examined": len(curve),
        "full": _best(curve, covered=False),
        "covered_normalization_secondary": _best(curve, covered=True),
        "curve": curve,
    }


def evaluate_scores(
    *,
    eligible: Set[Pair],
    truth: Mapping[Pair, Set[str]],
    scores: Mapping[TermKey, float],
    species: Mapping[str, str],
    aspects: Sequence[str] = ASPECT_ORDER,
    taxids: Set[str] | None = None,
    thresholds: Sequence[float] | None = None,
) -> dict:
    """Evaluate one method, with full recall as the primary normalization.

    Callers supply the complete eligible population and M1-prepared scores.
    TaxID selection is an OR filter on original target species; both truth
    denominators and prepared predictions are filtered inside this function.
    """
    if not aspects or len(set(aspects)) != len(aspects) or not set(aspects) <= ASPECTS:
        raise ValueError("Aspects must be distinct F, P or C values")
    if not isinstance(eligible, Set):
        raise ValueError("Eligible population must be a set of target-aspect pairs")
    if set(truth) != set(eligible):
        raise ValueError("Truth must cover exactly the full eligible population")
    if taxids is not None and (
        not isinstance(taxids, Set) or not taxids or any(not _taxid(t) for t in taxids)
    ):
        raise ValueError("TaxID filters must be nonempty positive decimal strings")
    for key in eligible:
        if (
            not isinstance(key, tuple)
            or len(key) != 2
            or not isinstance(key[0], str)
            or not key[0]
            or key[1] not in ASPECTS
        ):
            raise ValueError("Invalid eligible target-aspect key")
        if not _taxid(species.get(key[0])):
            raise ValueError("Missing or invalid original target species TaxID")
        values = truth[key]
        if not isinstance(values, Set) or not values:
            raise ValueError("Every eligible pair requires nonempty EVAL truth")
        if any(
            not isinstance(go, str) or not GO_ID.fullmatch(go) or go in ROOTS
            for go in values
        ):
            raise ValueError("Invalid truth GO or root term")
    explicit = None
    if thresholds is not None:
        if not thresholds or any(
            not isinstance(tau, Real)
            or isinstance(tau, bool)
            or not math.isfinite(tau)
            or not 0 <= tau <= 1
            for tau in thresholds
        ):
            raise ValueError("Thresholds must be finite numbers in [0, 1]")
        explicit = tuple(sorted({float(tau) for tau in thresholds}, reverse=True))
    selected_aspects = tuple(value for value in ASPECT_ORDER if value in aspects)
    selected = frozenset(
        (query, aspect)
        for query, aspect in eligible
        if aspect in selected_aspects and (taxids is None or species[query] in taxids)
    )
    by_aspect: dict[str, list] = {value: [] for value in selected_aspects}
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
            raise ValueError("Expected valid scorable M1-prepared prediction pairs")
        if key[:2] in selected:
            by_aspect[key[1]].append((float(score), key[0], key[2]))
    reports = {
        value: _aspect_metrics(
            aspect=value,
            truth=truth,
            queries=sorted(query for query, aspect in selected if aspect == value),
            events=by_aspect[value],
            thresholds=explicit,
        )
        for value in selected_aspects
    }
    represented = {species[query] for query, _ in eligible}
    return {
        "schema": SCHEMA,
        "status": "EVALUATED" if selected else "NO_ELIGIBLE_TARGETS",
        "normalization": "precision_covered_recall_full_macro",
        "threshold_policy": {
            "mode": "exact_score_sweep" if explicit is None else "explicit_thresholds",
            "explicit_thresholds": list(explicit) if explicit is not None else None,
            "exact_includes_endpoints": explicit is None,
            "comparison": "present_score_greater_than_or_equal_to_threshold",
            "tie_break": "greatest_threshold_among_equal_computed_maxima",
        },
        "filters": {
            "aspects": list(selected_aspects),
            "species_taxids": sorted(taxids) if taxids is not None else None,
            "taxids_not_in_evaluable_fasta": sorted(set(taxids or ()) - represented),
        },
        "population_before_filters": {
            "evaluable_targets": len({query for query, _ in eligible}),
            "target_aspects": len(eligible),
        },
        "population_after_filters": {
            "evaluable_targets": len({query for query, _ in selected}),
            "target_aspects": len(selected),
        },
        "smin_status": "NOT_COMPUTED_PENDING_CERTIFIED_INFORMATION_ACCRETION",
        "aspects": reports,
    }
