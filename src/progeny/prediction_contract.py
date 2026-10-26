"""Strict prediction records and score preparation, independent of GO parsing.

This module computes no predictor metrics. Missing predictions stay absent;
the full eligible population is retained separately by the benchmark reader.
"""

from __future__ import annotations

import csv
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

PREDICTION_FIELDS = ("query_id", "go_id", "score")
GO_ID = re.compile(r"GO:[0-9]{7}\Z")
ASPECTS = frozenset({"F", "P", "C"})
ROOTS = frozenset({"GO:0003674", "GO:0008150", "GO:0005575"})
PREPARATION_SCHEMA = "progeny-prediction-preparation-v1"
Pair = tuple[str, str]
TermKey = tuple[str, str, str]


@dataclass(frozen=True)
class Prediction:
    query_id: str
    go_id: str
    score: float


@dataclass
class PreparedPredictions:
    """Scores after propagation, root removal, eligibility and term masks."""

    scores: dict[TermKey, float]
    counts: dict[str, int]
    go_audit: list[dict]


@dataclass(frozen=True)
class GoResolution:
    """A mapping supported only by the pinned benchmark ontology."""

    canonical_id: str | None
    status: str
    candidates: tuple[str, ...] = ()


def read_predictions(path: Path) -> Iterable[Prediction]:
    """Read exact UTF-8 TSV columns; errors identify physical line numbers.

    Header-only input is a valid method with no predictions. Blank records,
    comments, extra columns and NaN/Infinity are rejected rather than dropped.
    """
    if path.is_symlink() or not path.is_file():
        raise ValueError("Prediction input must be a regular non-symlink file")
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, delimiter="\t", strict=True)
        try:
            fields = next(reader)
        except StopIteration as exc:
            raise ValueError("Missing prediction header") from exc
        if tuple(fields) != PREDICTION_FIELDS:
            raise ValueError(f"Expected TSV header: {PREDICTION_FIELDS}")
        for row in reader:
            line = reader.line_num
            if len(row) != 3:
                raise ValueError(f"Prediction line {line}: expected three fields")
            query, go, raw_score = row
            if not query or any(character.isspace() for character in query):
                raise ValueError(f"Prediction line {line}: invalid query_id")
            if not GO_ID.fullmatch(go):
                raise ValueError(f"Prediction line {line}: invalid GO ID")
            if not raw_score or raw_score != raw_score.strip():
                raise ValueError(f"Prediction line {line}: invalid score")
            try:
                score = float(raw_score)
            except ValueError as exc:
                raise ValueError(f"Prediction line {line}: invalid score") from exc
            if not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError(f"Prediction line {line}: score outside [0, 1]")
            yield Prediction(query, go, score)


def prepare_predictions(
    records: Iterable[Prediction],
    *,
    target_ids: frozenset[str],
    eligible: frozenset[Pair],
    masks: Mapping[TermKey, str],
    resolve: Callable[[str], GoResolution],
    aspect: Callable[[str], str],
    ancestors: Callable[[str], Iterable[str]],
) -> PreparedPredictions:
    """Canonicalize, merge max, propagate max, then mask per target/aspect.

    Zero is an explicitly supplied score; it is never synthesized for absent
    predictions. Neither NOT records nor truth annotations are consulted here.
    Counts distinguish submitted rows from unique propagated target-GO pairs.
    Syntactically valid GO IDs without an active mapping are excluded before
    propagation, with a row audit. They never establish target eligibility.
    """
    if any(
        query not in target_ids or value not in ASPECTS for query, value in eligible
    ):
        raise ValueError("Invalid eligible target-aspect population")
    for (query, value, go), status in masks.items():
        if (
            (query, value) not in eligible
            or status not in {"SKIP", "NEUTRAL"}
            or not GO_ID.fullmatch(go)
        ):
            raise ValueError("Invalid per-target/aspect mask")
    counts: Counter[str] = Counter(
        dict.fromkeys(
            (
                "submitted_rows",
                "active_rows",
                "remapped_rows",
                "unresolved_rows_excluded",
                "unsupported_aspect_rows_excluded",
                "accepted_rows",
                "duplicate_rows_after_resolution",
                "canonical_pairs",
                "propagated_pairs",
                "root_pairs_excluded",
                "ineligible_pairs_excluded",
                "skip_pairs_excluded",
                "neutral_pairs_excluded",
                "scorable_pairs",
            ),
            0,
        )
    )
    direct: dict[tuple[str, str], float] = {}
    go_audit = []
    for record in records:
        counts["submitted_rows"] += 1
        if record.query_id not in target_ids:
            raise ValueError(f"Unknown original target ID: {record.query_id}")
        if (
            not GO_ID.fullmatch(record.go_id)
            or isinstance(record.score, bool)
            or not math.isfinite(record.score)
            or not 0 <= record.score <= 1
        ):
            raise ValueError("Invalid prediction record")
        resolution = resolve(record.go_id)
        canonical = resolution.canonical_id
        audit = {
            "input_row": counts["submitted_rows"],
            "query_id": record.query_id,
            "submitted_go_id": record.go_id,
            "canonical_go_id": canonical,
            "score": record.score,
            "ontology_status": resolution.status,
            "candidate_go_ids": list(resolution.candidates),
        }
        if canonical is None:
            counts["unresolved_rows_excluded"] += 1
            go_audit.append(
                {
                    **audit,
                    "action": "EXCLUDED",
                    "reason": "NO_UNAMBIGUOUS_ACTIVE_MAPPING_IN_PINNED_ONTOLOGY",
                }
            )
            continue
        if aspect(canonical) not in ASPECTS:
            counts["unsupported_aspect_rows_excluded"] += 1
            go_audit.append(
                {**audit, "action": "EXCLUDED", "reason": "UNSUPPORTED_ASPECT"}
            )
            continue
        counts["accepted_rows"] += 1
        counts["remapped_rows"] += canonical != record.go_id
        counts["active_rows"] += canonical == record.go_id
        if canonical != record.go_id:
            go_audit.append(
                {**audit, "action": "REMAPPED", "reason": "PINNED_ONTOLOGY_MAPPING"}
            )
        key = record.query_id, canonical
        if key in direct:
            counts["duplicate_rows_after_resolution"] += 1
            direct[key] = max(direct[key], record.score)
        else:
            direct[key] = record.score
    counts["canonical_pairs"] = len(direct)
    propagated: dict[TermKey, float] = {}
    for (query, go), score in direct.items():
        source_aspect = aspect(go)
        closure = set(ancestors(go)) | {go}
        for parent in closure:
            if aspect(parent) != source_aspect:
                raise ValueError("Cross-aspect term in prediction closure")
            key = query, source_aspect, parent
            propagated[key] = max(propagated.get(key, score), score)
    counts["propagated_pairs"] = len(propagated)
    result = {}
    for key, score in propagated.items():
        query, value, go = key
        if go in ROOTS:
            counts["root_pairs_excluded"] += 1
        elif (query, value) not in eligible:
            counts["ineligible_pairs_excluded"] += 1
        elif key in masks:
            counts[f"{masks[key].lower()}_pairs_excluded"] += 1
        else:
            result[key] = score
    counts["scorable_pairs"] = len(result)
    return PreparedPredictions(result, dict(counts), go_audit)
