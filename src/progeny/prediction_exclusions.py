"""Exact GO-ID evaluation exclusions applied after prediction propagation."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Set
from pathlib import Path

from progeny.prediction_contract import GO_ID, Pair, TermKey


def verify_exclusions(exclusion: dict) -> None:
    if exclusion["path"] is not None:
        observed = hashlib.sha256(Path(exclusion["path"]).read_bytes()).hexdigest()
        if observed != exclusion["sha256"]:
            raise ValueError("GO exclusion file changed during evaluation")


def read_exclusions(path: Path | None, graph) -> dict:
    if path is None:
        return {"path": None, "sha256": None, "go_ids": []}
    if path.absolute() != path.resolve(strict=True) or not path.is_file():
        raise ValueError("GO exclusion file must be regular and without symlinks")
    content = path.read_bytes()
    ids = []
    for line in content.decode("ascii").splitlines():
        if not GO_ID.fullmatch(line):
            raise ValueError("GO exclusion file requires one exact GO ID per line")
        try:
            graph.aspect(line)
        except KeyError as exc:
            raise ValueError(f"GO exclusion ID is not active: {line}") from exc
        ids.append(line)
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate GO exclusion ID")
    return {
        "path": str(path.absolute()),
        "sha256": hashlib.sha256(content).hexdigest(),
        "go_ids": sorted(ids),
    }


def apply_exclusions(
    eligible: Set[Pair],
    truth: Mapping[Pair, Set[str]],
    scores: Mapping[TermKey, float],
    exclusion: dict,
) -> tuple[set[Pair], dict[Pair, set[str]], dict[TermKey, float], dict]:
    ids = set(exclusion["go_ids"])
    before_truth = sum(len(truth[pair]) for pair in eligible)
    filtered_truth = {pair: set(truth[pair]) - ids for pair in eligible}
    emptied = sorted(pair for pair in eligible if not filtered_truth[pair])
    kept = set(eligible) - set(emptied)
    filtered_scores = {
        key: value
        for key, value in scores.items()
        if key[:2] in kept and key[2] not in ids
    }
    audit = {
        **exclusion,
        "policy": "exact_go_ids_after_propagation_symmetric_no_descendants",
        "target_aspects_before": len(eligible),
        "target_aspects_after": len(kept),
        "truth_pairs_before": before_truth,
        "truth_pairs_after": sum(len(filtered_truth[pair]) for pair in kept),
        "prediction_pairs_before": len(scores),
        "prediction_pairs_after": len(filtered_scores),
        "empty_truth_target_aspects": [
            {"query_id": query, "aspect": aspect} for query, aspect in emptied
        ],
    }
    return kept, {pair: filtered_truth[pair] for pair in kept}, filtered_scores, audit
