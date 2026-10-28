"""Direct START evidence cohorts for target/aspect evaluation populations."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Set
from pathlib import Path

from progeny.prediction_contract import ASPECTS, GO_ID, Pair

KNOWLEDGE_CLASSES = frozenset({"NK", "LK", "PK"})
SCORE_EVIDENCE_CODES = frozenset(
    {"EXP", "HDA", "HEP", "HGI", "HMP", "HTP", "IDA", "IEP", "IGI", "IMP", "IPI"}
)


def assign_knowledge_classes(
    *,
    eligible: Set[Pair],
    species: Mapping[str, str],
    internal_ids: Mapping[str, str],
    direct_evidence: Iterable[Mapping[str, str]],
    resolve_go: Callable[[str], tuple[str | None, str]],
    go_aspect: Callable[[str], str],
) -> tuple[list[dict[str, str | int]], list[dict[str, str]], dict[str, int]]:
    """Classify eligible pairs from target-attributed START SCORE evidence.

    Input evidence rows must already be restricted to the START release,
    M8-accepted assertions attributed to the target's internal ID, positive
    polarity and SCORE evidence codes. A donor accession can differ from the
    target's external FASTA identifier. GO closure rows are not classification
    evidence. Replaced GO terms are accepted only when their active replacement
    stays in the source aspect.
    """
    if not eligible or not isinstance(eligible, Set):
        raise ValueError("Eligible target-aspect population must be a nonempty set")
    target_ids = {query for query, _ in eligible}
    if any(
        not isinstance(query, str) or not query or aspect not in ASPECTS
        for query, aspect in eligible
    ):
        raise ValueError("Invalid eligible target-aspect pair")
    if not target_ids <= set(species) or not target_ids <= set(internal_ids):
        raise ValueError("Missing target species or internal identity")
    if any(
        not isinstance(species[query], str)
        or not species[query].isascii()
        or not species[query].isdecimal()
        or species[query].startswith("0")
        for query in target_ids
    ):
        raise ValueError("Invalid target species TaxID")
    if any(not internal_ids[query] for query in target_ids):
        raise ValueError("Invalid internal target ID")

    supported: dict[str, set[str]] = {query: set() for query in target_ids}
    evidence_counts: Counter[str] = Counter()
    resolution_audit: list[dict[str, str]] = []
    for row in direct_evidence:
        query = row.get("original_id", "")
        source_aspect = row.get("aspect", "")
        go_id = row.get("go_id", "")
        evidence_code = row.get("evidence_code", "")
        if query not in target_ids:
            raise ValueError("Direct evidence references a non-benchmark target")
        if source_aspect not in ASPECTS or evidence_code not in SCORE_EVIDENCE_CODES:
            raise ValueError("Direct evidence is outside the SCORE policy")
        canonical, disposition = resolve_go(go_id)
        try:
            canonical_aspect = go_aspect(canonical) if canonical is not None else ""
        except KeyError:
            canonical_aspect = ""
        if canonical is None:
            action = "EXCLUDE_UNRESOLVED"
        elif not canonical_aspect:
            action = "EXCLUDE_UNSUPPORTED_TERM"
        elif canonical_aspect != source_aspect:
            action = "EXCLUDE_CROSS_ASPECT_REPLACEMENT"
        else:
            action = "KEEP_DIRECT_EVIDENCE"
            supported[query].add(source_aspect)
            evidence_counts[evidence_code] += 1
        resolution_audit.append(
            {
                "original_id": query,
                "source_go_id": go_id,
                "source_aspect": source_aspect,
                "canonical_go_id": canonical or "",
                "canonical_aspect": canonical_aspect,
                "resolution": disposition,
                "action": action,
                "evidence_code": evidence_code,
                "rid": row.get("rid", ""),
                "assertion_id": row.get("assertion_id", ""),
                "release_id": row.get("release_id", ""),
                "internal_target_id": row.get("internal_target_id", ""),
                "donor_accession": row.get("donor_accession", ""),
                "polarity": row.get("polarity", "POSITIVE"),
                "normalized_gaf_line": row.get("normalized_gaf_line", ""),
                "gaf_relation": row.get("gaf_relation", ""),
                "gaf_qualifier": row.get("gaf_qualifier", ""),
            }
        )

    cohorts = []
    counts: Counter[str] = Counter()
    for query, aspect in sorted(eligible):
        known_aspects = supported[query]
        if not known_aspects:
            knowledge = "NK"
        elif aspect in known_aspects:
            knowledge = "PK"
        else:
            knowledge = "LK"
        counts[f"{aspect}_{knowledge}"] += 1
        cohorts.append(
            {
                "original_id": query,
                "internal_target_id": internal_ids[query],
                "species_taxid": species[query],
                "aspect": aspect,
                "knowledge_class": knowledge,
                "direct_start_score_aspects": ",".join(sorted(known_aspects)),
            }
        )
    all_counts = {
        **counts,
        **{f"evidence_{key}": value for key, value in evidence_counts.items()},
    }
    return cohorts, resolution_audit, dict(sorted(all_counts.items()))


def select_eligible_pairs(
    *,
    eligible: Set[Pair],
    cohorts: Iterable[Mapping[str, str]],
    knowledge: Set[str] | None,
    aspects: Set[str],
    species: Mapping[str, str],
    taxids: Set[str] | None,
) -> tuple[frozenset[Pair], dict[Pair, str]]:
    """Return the complete filtered denominator and each pair's class label."""
    if not aspects or not aspects <= ASPECTS:
        raise ValueError("Aspect selection must be a nonempty F/P/C set")
    if knowledge is not None and (not knowledge or not knowledge <= KNOWLEDGE_CLASSES):
        raise ValueError("Knowledge selection must contain NK, LK and/or PK")
    if taxids is not None and (not taxids or any(not t.isdecimal() for t in taxids)):
        raise ValueError("TaxID selection must contain positive decimal IDs")
    labels: dict[Pair, str] = {}
    for row in cohorts:
        key = row.get("original_id", ""), row.get("aspect", "")
        label = row.get("knowledge_class", "")
        if key not in eligible or key in labels or label not in KNOWLEDGE_CLASSES:
            raise ValueError("Invalid, duplicate or foreign cohort row")
        if row.get("species_taxid") != species[key[0]]:
            raise ValueError("Cohort TaxID disagrees with certified benchmark")
        labels[key] = label
    if set(labels) != set(eligible):
        raise ValueError("Cohort table must cover every eligible target-aspect")
    selected = frozenset(
        key
        for key in eligible
        if key[1] in aspects
        and (knowledge is None or labels[key] in knowledge)
        and (taxids is None or species[key[0]] in taxids)
    )
    return selected, labels


def load_published_cohorts(
    directory: Path,
    *,
    eligible: Set[Pair],
    species: Mapping[str, str],
    provenance: Mapping[str, object],
) -> tuple[list[dict[str, str]], dict]:
    """Verify and load a cohort publication tied to this benchmark identity."""
    absolute = directory.absolute()
    if absolute.resolve(strict=True) != absolute or not absolute.is_dir():
        raise ValueError("Cohort directory must be a real directory without symlinks")
    manifest_path = absolute / "manifest.json"
    cohort_path = absolute / "knowledge_cohorts.tsv"
    for path in (manifest_path, cohort_path):
        if path.is_symlink() or not path.is_file():
            raise ValueError("Cohort publication is missing a regular artifact")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Knowledge cohort manifest must be a JSON object")
    if manifest.get("schema") != "progeny-start-knowledge-cohorts-v2":
        raise ValueError("Unsupported knowledge cohort schema")
    if manifest.get("status") != "PUBLISHED":
        raise ValueError("Knowledge cohort publication is not complete")
    expected_policy = {
        "classification_policy": (
            "accepted_target_positive_START_SCORE_evidence_by_aspect_v2"
        ),
        "score_evidence_codes": sorted(SCORE_EVIDENCE_CODES),
        "not_policy": "NOT_excluded",
        "donor_policy": (
            "M8_accepted_donor_assertions_attributed_by_internal_target_id"
        ),
        "propagation_policy": "direct_source_GO_only_no_closure",
        "replacement_policy": (
            "accept_only_unambiguous_active_replacement_in_same_aspect"
        ),
    }
    if any(manifest.get(key) != value for key, value in expected_policy.items()):
        raise ValueError("Unsupported knowledge cohort classification policy")
    if not isinstance(manifest.get("start_release"), str) or not re.fullmatch(
        r"[a-f0-9]{64}", str(manifest.get("start_gaf_sha256", ""))
    ):
        raise ValueError("Knowledge cohort publication lacks START source identity")
    for field in (
        "benchmark_sha256",
        "ontology_sha256",
        "temporal_manifest_sha256",
        "m10c_manifest_sha256",
    ):
        expected = provenance.get(field)
        if not expected or manifest.get(field) != expected:
            raise ValueError(f"Cohort publication identity mismatch: {field}")
    artifacts = manifest.get("artifacts")
    required_artifacts = {
        "knowledge_cohorts.tsv",
        "direct_start_go_resolution_audit.tsv",
    }
    if not isinstance(artifacts, dict) or set(artifacts) != required_artifacts:
        raise ValueError("Unexpected knowledge cohort artifact inventory")
    for name, record in artifacts.items():
        path = absolute / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing cohort publication artifact: {name}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if (
            not isinstance(record, dict)
            or record.get("bytes") != path.stat().st_size
            or record.get("sha256") != digest.hexdigest()
        ):
            raise ValueError(f"Cohort artifact checksum mismatch: {name}")
    rows = []
    with cohort_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", strict=True)
        required = {
            "original_id",
            "internal_target_id",
            "aspect",
            "knowledge_class",
            "species_taxid",
            "direct_start_score_aspects",
        }
        if (
            reader.fieldnames is None
            or len(reader.fieldnames) != len(set(reader.fieldnames))
            or not required <= set(reader.fieldnames)
        ):
            raise ValueError("Unexpected knowledge cohort TSV header")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed knowledge cohort TSV row")
            if not row["internal_target_id"]:
                raise ValueError("Knowledge cohort row lacks internal target ID")
            direct_aspects = row.get("direct_start_score_aspects", "")
            aspect_set = set(direct_aspects.split(",")) if direct_aspects else set()
            if not aspect_set <= ASPECTS or direct_aspects != ",".join(
                sorted(aspect_set)
            ):
                raise ValueError("Invalid direct-evidence aspects in cohort row")
            expected_class = (
                "NK"
                if not aspect_set
                else "PK"
                if row["aspect"] in aspect_set
                else "LK"
            )
            if row["knowledge_class"] != expected_class:
                raise ValueError("Knowledge class disagrees with direct aspects")
            rows.append(row)
    class_counts = Counter(f"{row['aspect']}_{row['knowledge_class']}" for row in rows)
    expected_class_counts = {
        f"{aspect}_{knowledge}": class_counts[f"{aspect}_{knowledge}"]
        for aspect in ("F", "P", "C")
        for knowledge in sorted(KNOWLEDGE_CLASSES)
    }
    if manifest.get("class_counts_by_aspect") != expected_class_counts:
        raise ValueError("Knowledge cohort manifest class counts are inconsistent")
    if manifest.get("eligible_target_aspects") != len(eligible) or manifest.get(
        "eligible_targets"
    ) != len({query for query, _ in eligible}):
        raise ValueError("Knowledge cohort manifest population is inconsistent")
    audit_path = absolute / "direct_start_go_resolution_audit.tsv"
    cohort_internal_ids = {
        row["original_id"]: row["internal_target_id"] for row in rows
    }
    evidence_codes: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    with audit_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", strict=True)
        expected_fields = {
            "original_id",
            "source_go_id",
            "source_aspect",
            "canonical_go_id",
            "canonical_aspect",
            "resolution",
            "action",
            "evidence_code",
            "rid",
            "assertion_id",
            "release_id",
            "internal_target_id",
            "donor_accession",
            "polarity",
            "normalized_gaf_line",
            "gaf_relation",
            "gaf_qualifier",
        }
        if (
            reader.fieldnames is None
            or len(reader.fieldnames) != len(expected_fields)
            or set(reader.fieldnames) != expected_fields
        ):
            raise ValueError("Unexpected direct START GO audit header")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed direct START GO audit row")
            action = row["action"]
            if action not in {
                "KEEP_DIRECT_EVIDENCE",
                "EXCLUDE_CROSS_ASPECT_REPLACEMENT",
                "EXCLUDE_UNRESOLVED",
                "EXCLUDE_UNSUPPORTED_TERM",
            }:
                raise ValueError("Unknown direct START GO audit disposition")
            if (
                row["release_id"] != manifest.get("start_release")
                or not row["donor_accession"]
                or row["polarity"] != "POSITIVE"
                or not row["normalized_gaf_line"].isdecimal()
                or row["original_id"] not in cohort_internal_ids
                or row["internal_target_id"] != cohort_internal_ids[row["original_id"]]
                or row["source_aspect"] not in ASPECTS
                or row["evidence_code"] not in SCORE_EVIDENCE_CODES
                or not GO_ID.fullmatch(row["source_go_id"])
            ):
                raise ValueError("Audit row violates direct START provenance policy")
            if action == "KEEP_DIRECT_EVIDENCE" and (
                not GO_ID.fullmatch(row["canonical_go_id"])
                or row["canonical_aspect"] != row["source_aspect"]
            ):
                raise ValueError("Kept audit row violates same-aspect GO policy")
            if action == "EXCLUDE_CROSS_ASPECT_REPLACEMENT" and (
                not GO_ID.fullmatch(row["canonical_go_id"])
                or row["canonical_aspect"] not in ASPECTS
                or row["canonical_aspect"] == row["source_aspect"]
            ):
                raise ValueError("Cross-aspect audit disposition is inconsistent")
            if action == "EXCLUDE_UNRESOLVED" and row["canonical_go_id"]:
                raise ValueError("Unresolved audit row has a canonical GO term")
            if action == "EXCLUDE_UNSUPPORTED_TERM" and (
                not GO_ID.fullmatch(row["canonical_go_id"]) or row["canonical_aspect"]
            ):
                raise ValueError("Unsupported GO audit disposition is inconsistent")
            actions[action] += 1
            if action == "KEEP_DIRECT_EVIDENCE":
                if row["evidence_code"] not in SCORE_EVIDENCE_CODES:
                    raise ValueError("Audit contains a non-SCORE evidence row")
                evidence_codes[row["evidence_code"]] += 1
    if (
        manifest.get("direct_evidence_rows_audited") != sum(actions.values())
        or manifest.get("direct_evidence_rows_kept") != actions["KEEP_DIRECT_EVIDENCE"]
        or manifest.get("cross_aspect_replacements_excluded")
        != actions["EXCLUDE_CROSS_ASPECT_REPLACEMENT"]
        or manifest.get("unresolved_go_rows_excluded") != actions["EXCLUDE_UNRESOLVED"]
        or manifest.get("unsupported_go_rows_excluded")
        != actions["EXCLUDE_UNSUPPORTED_TERM"]
        or manifest.get("evidence_counts_by_code")
        != dict(sorted(evidence_codes.items()))
    ):
        raise ValueError("Knowledge cohort evidence audit counts are inconsistent")
    selected_all, _ = select_eligible_pairs(
        eligible=eligible,
        cohorts=rows,
        knowledge=None,
        aspects=set(ASPECTS),
        species=species,
        taxids=None,
    )
    if selected_all != frozenset(eligible):
        raise ValueError("Cohort table does not cover the benchmark population")
    return rows, manifest
