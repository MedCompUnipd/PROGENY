#!/usr/bin/env python3
"""Publish audited NK/LK/PK cohorts from certified M10C START evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from progeny.alpha_identity import _sha
from progeny.alpha_scientific_publish import _read_certificate
from progeny.knowledge_cohorts import SCORE_EVIDENCE_CODES, assign_knowledge_classes
from progeny.ontology import TermStatus
from progeny.prediction_inputs import _read_json, _tsv, load_benchmark_inputs

SCHEMA = "progeny-start-knowledge-cohorts-v2"
COHORT_FIELDS = (
    "original_id",
    "internal_target_id",
    "species_taxid",
    "aspect",
    "knowledge_class",
    "direct_start_score_aspects",
)
AUDIT_FIELDS = (
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
)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_tsv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _m10c_paths(run: Path) -> tuple[Path, Path, str]:
    certificate_path = _read_certificate(run)
    certificate = _read_json(certificate_path)
    try:
        receipt = Path(certificate["receipts"]["m10c:COMMON"]["path"])
        release = certificate["releases"]["START"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Certificate lacks M10C or START release identity") from exc
    if not isinstance(release, str) or not release:
        raise ValueError("Invalid certified START release ID")
    manifest = receipt.parent / "m10c/manifest.json"
    database = manifest.parent / "direct_provenance.sqlite3"
    return manifest, database, release


def _checked_m10c(database: Path, manifest_path: Path, expected_manifest: str) -> dict:
    if _sha(manifest_path) != expected_manifest:
        raise ValueError("M10C manifest differs from the certified benchmark input")
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != "stage08-m10c-compact-interpretation-v1":
        raise ValueError("Unsupported M10C schema")
    if manifest.get("evaluation_policy") != "not_computed":
        raise ValueError("M10C policy is not the certified pre-evaluation policy")
    output = manifest.get("outputs", {}).get("direct_provenance.sqlite3", {})
    if output.get("bytes") != database.stat().st_size or output.get(
        "sha256"
    ) != _digest(database):
        raise ValueError("M10C direct provenance database checksum mismatch")
    return manifest


def _query_target_score_evidence(
    connection: sqlite3.Connection,
    *,
    release: str,
    target_identity: dict[str, str],
    target_ids: set[str],
) -> list[dict[str, str]]:
    """Read positive START SCORE assertions linked to each internal target.

    M10C contains assertions from accepted donors attributed to the target by
    the certified M8 lineage. Donor accession therefore need not equal the
    target's external FASTA identifier.
    """
    rows = []
    placeholders = ",".join("?" for _ in SCORE_EVIDENCE_CODES)
    query = (
        "SELECT aspect, source_go, evidence_code, rid, assertion_id, "
        "normalized_gaf_line, gaf_relation, gaf_qualifier, donor_accession "
        "FROM direct_support WHERE release=? AND target_id=? "
        "AND polarity='POSITIVE' "
        f"AND evidence_code IN ({placeholders}) "
        "ORDER BY aspect, source_go, evidence_code, rid, assertion_id"
    )
    score_codes = tuple(sorted(SCORE_EVIDENCE_CODES))
    for original_id in sorted(target_ids):
        internal = target_identity[original_id]
        parameters = (release, internal, *score_codes)
        for row in connection.execute(query, parameters):
            rows.append(
                {
                    "original_id": original_id,
                    "aspect": row["aspect"],
                    "go_id": row["source_go"],
                    "evidence_code": row["evidence_code"],
                    "rid": str(row["rid"]),
                    "assertion_id": row["assertion_id"],
                    "release_id": release,
                    "internal_target_id": internal,
                    "donor_accession": row["donor_accession"],
                    "polarity": "POSITIVE",
                    "normalized_gaf_line": str(row["normalized_gaf_line"]),
                    "gaf_relation": row["gaf_relation"],
                    "gaf_qualifier": row["gaf_qualifier"],
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--benchmark-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    benchmark = load_benchmark_inputs(
        dataset=args.dataset,
        run=args.run,
        ontology_path=args.ontology,
        benchmark_sha256=args.benchmark_sha256,
    )
    manifest_path, database, release = _m10c_paths(args.run)
    if (
        manifest_path.is_symlink()
        or not manifest_path.is_file()
        or database.is_symlink()
        or not database.is_file()
    ):
        raise ValueError("M10C direct provenance must be a regular file")
    m10c_manifest = _checked_m10c(
        database,
        manifest_path,
        benchmark.provenance["m10c_manifest_sha256"],
    )
    ontology_sha = benchmark.provenance["ontology_sha256"]
    if m10c_manifest.get("ontology_sha256") != ontology_sha:
        raise ValueError("M10C and benchmark ontology identities disagree")
    start_payload = m10c_manifest.get("source_payloads", {}).get("START", {})
    start_gaf_sha = start_payload.get("gaf_source_sha256")
    if not isinstance(start_gaf_sha, str) or not re.fullmatch(
        r"[a-f0-9]{64}", start_gaf_sha
    ):
        raise ValueError("M10C manifest lacks a START GAF fingerprint")

    target_identity = {}
    for row in _tsv(
        args.run / "results/benchmark/target_identity_map.tsv",
        {"original_id", "internal_target_id", "benchmark_status"},
    ):
        if row["benchmark_status"] == "EVALUABLE":
            target_identity[row["original_id"]] = row["internal_target_id"]
    if set(target_identity) != benchmark.target_ids:
        raise ValueError("Identity map does not cover the evaluator targets")

    database_uri = f"file:{quote(str(database), safe='/')}?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if not connection.execute(
            "SELECT 1 FROM direct_support WHERE release=? LIMIT 1", (release,)
        ).fetchone():
            raise ValueError("Configured START release is absent from M10C")
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(direct_support)")
        }
        required = {
            "release",
            "target_id",
            "aspect",
            "source_go",
            "polarity",
            "evidence_code",
            "rid",
            "assertion_id",
            "donor_accession",
            "normalized_gaf_line",
            "gaf_relation",
            "gaf_qualifier",
        }
        if not required <= columns:
            raise ValueError("Unexpected M10C direct_support schema")
        evidence_rows = _query_target_score_evidence(
            connection,
            release=release,
            target_identity=target_identity,
            target_ids=benchmark.target_ids,
        )
    finally:
        connection.close()

    def resolve(go_id: str) -> tuple[str | None, str]:
        result = benchmark.ontology.resolve(go_id)
        if result.status == TermStatus.ACTIVE and result.canonical_id == go_id:
            return result.canonical_id, result.status.value
        if result.canonical_id is not None:
            return result.canonical_id, result.status.value
        return None, result.status.value

    cohorts, audit, counts = assign_knowledge_classes(
        eligible=benchmark.eligible,
        species=benchmark.species,
        internal_ids=target_identity,
        direct_evidence=evidence_rows,
        resolve_go=resolve,
        go_aspect=benchmark.aspect,
    )
    excluded_cross_aspect = sum(
        row["action"] == "EXCLUDE_CROSS_ASPECT_REPLACEMENT" for row in audit
    )
    excluded_unresolved = sum(row["action"] == "EXCLUDE_UNRESOLVED" for row in audit)
    excluded_unsupported = sum(
        row["action"] == "EXCLUDE_UNSUPPORTED_TERM" for row in audit
    )
    kept_rows = sum(row["action"] == "KEEP_DIRECT_EVIDENCE" for row in audit)

    output = args.output_dir.absolute()
    if output.resolve(strict=False) != output or output.exists():
        raise ValueError("Output directory must be new and without symlink parents")
    if output.parent.resolve(strict=True) != output.parent:
        raise ValueError("Output parent must not contain symlink components")
    repository = Path(__file__).resolve().parents[2]
    try:
        output.relative_to(repository)
    except ValueError:
        pass
    else:
        raise ValueError("Cohort output must be outside the source checkout")
    for protected in (args.dataset, args.run):
        try:
            output.relative_to(protected.resolve(strict=True))
        except ValueError:
            continue
        raise ValueError("Cohort output must be outside benchmark data roots")

    staging = Path(tempfile.mkdtemp(prefix=".progeny-cohorts-", dir=output.parent))
    try:
        cohort_path = staging / "knowledge_cohorts.tsv"
        audit_path = staging / "direct_start_go_resolution_audit.tsv"
        _write_tsv(cohort_path, COHORT_FIELDS, cohorts)
        _write_tsv(audit_path, AUDIT_FIELDS, audit)
        observed_class_counts = Counter(
            f"{row['aspect']}_{row['knowledge_class']}" for row in cohorts
        )
        counts_by_class = {
            f"{aspect}_{knowledge}": observed_class_counts[f"{aspect}_{knowledge}"]
            for aspect in ("F", "P", "C")
            for knowledge in ("NK", "LK", "PK")
        }
        manifest = {
            "schema": SCHEMA,
            "status": "PUBLISHED",
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
            "benchmark_sha256": args.benchmark_sha256,
            "ontology_sha256": ontology_sha,
            "temporal_manifest_sha256": benchmark.provenance[
                "temporal_manifest_sha256"
            ],
            "m10c_manifest_sha256": benchmark.provenance["m10c_manifest_sha256"],
            "m10c_database_sha256": m10c_manifest["outputs"][
                "direct_provenance.sqlite3"
            ]["sha256"],
            "start_release": release,
            "start_gaf_sha256": start_gaf_sha,
            "eligible_targets": len(benchmark.target_ids),
            "eligible_target_aspects": len(benchmark.eligible),
            "direct_evidence_rows_audited": len(audit),
            "direct_evidence_rows_kept": kept_rows,
            "class_counts_by_aspect": dict(sorted(counts_by_class.items())),
            "evidence_counts_by_code": {
                key.removeprefix("evidence_"): value
                for key, value in counts.items()
                if key.startswith("evidence_")
            },
            "cross_aspect_replacements_excluded": excluded_cross_aspect,
            "unresolved_go_rows_excluded": excluded_unresolved,
            "unsupported_go_rows_excluded": excluded_unsupported,
            "artifacts": {
                cohort_path.name: {
                    "bytes": cohort_path.stat().st_size,
                    "sha256": _sha(cohort_path),
                },
                audit_path.name: {
                    "bytes": audit_path.stat().st_size,
                    "sha256": _sha(audit_path),
                },
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if output.exists():
            raise FileExistsError("Cohort output directory appeared during publication")
        os.rename(staging, output)
    except BaseException:
        if staging.exists():
            for path in staging.iterdir():
                path.unlink()
            staging.rmdir()
        raise
    print(json.dumps({"status": "PUBLISHED", "output_dir": str(output)}))


if __name__ == "__main__":
    main()
