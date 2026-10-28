"""Resolve immutable evaluation artifacts from a PROGENY study setup."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

IA_SCHEMA = "progeny-information-accretion-v3"
IA_POLICY = {
    "schema": IA_SCHEMA,
    "source_role": "START",
    "evidence_policy": "all_positive_uniprotkb_gaf_rows_including_iea",
    "go_resolution_policy": (
        "audit_source_namespace_then_follow_only_unambiguous_replaced_by_to_active_term"
    ),
    "remapped_go_count_policy": "accepted_rows_only",
    "cross_aspect_replacement_policy": "exclude_and_audit",
    "source_aspect_mismatch_policy": "exclude_and_audit",
    "invalid_gaf_aspect_policy": "exclude_and_audit",
    "identity_policy": "GAF_database_and_object_id",
    "deduplication": "one_protein_canonical_go_pair",
    "propagation": "same_aspect_pinned_transitive_maximal_closure",
    "relations": ["is_a", "part_of"],
    "not_policy": "exclude_rows_with_NOT_qualifier",
    "smoothing": "one_synthetic_protein_annotated_to_every_active_term",
    "formula": "log2((count_all_direct_parents+1)/(count_term+1))",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def shared_artifacts_root(dataset: Path) -> Path:
    """Return the installer-owned store shared by runs under one study base."""
    resolved_dataset = dataset.resolve(strict=True)
    if dataset.absolute() != resolved_dataset:
        raise ValueError("Dataset path must not contain symlinks")
    dataset = resolved_dataset
    summary_path = dataset / "config/setup-summary.json"
    expected = dataset.parent / "PROGENY_SHARED"
    if expected.exists() and not expected.is_dir():
        raise ValueError("Shared-artifact root is not a directory")
    if summary_path.is_file():
        summary = _read_json(summary_path)
        recorded = summary.get("shared_artifacts_root")
        if recorded is not None and Path(recorded) != expected:
            raise ValueError("Setup shared-artifact root disagrees with its layout")
    if expected.is_symlink() or expected.absolute() != expected.resolve(strict=False):
        raise ValueError("Shared-artifact root must not contain symlinks")
    return expected


def start_identity(dataset: Path) -> dict:
    """Read START GOA and ontology identities from installer-owned metadata."""
    resolved_dataset = dataset.resolve(strict=True)
    if dataset.absolute() != resolved_dataset:
        raise ValueError("Dataset path must not contain symlinks")
    dataset = resolved_dataset
    spec = _read_json(dataset / "config/fresh-spec.json")
    try:
        pipeline = spec["pipeline"]
        release = pipeline["releases"]["START"]["release_id"]
        raw_gaf_path = Path(pipeline["releases"]["START"]["goa"])
        ontology = pipeline["ontology"]
        raw_ontology_path = Path(ontology["path"])
        ontology_sha = ontology["expected_sha256"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Fresh spec lacks START GOA or ontology identity") from exc
    if not isinstance(release, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", release
    ):
        raise ValueError("Invalid START release identifier")
    gaf_path = raw_gaf_path.resolve(strict=True)
    ontology_path = raw_ontology_path.resolve(strict=True)
    if (
        raw_gaf_path.absolute() != gaf_path
        or raw_ontology_path.absolute() != ontology_path
    ):
        raise ValueError("START GOA and ontology must not be symlinks")
    if not isinstance(ontology_sha, str) or len(ontology_sha) != 64:
        raise ValueError("Invalid pinned ontology SHA-256")

    summary_path = dataset / "config/setup-summary.json"
    summary = _read_json(summary_path) if summary_path.is_file() else {}
    gaf_sha = summary.get("start_gaf_sha256")
    if gaf_sha is None:
        inventory_path = dataset / "config/scientific-identity-inventory.json"
        inventory = _read_json(inventory_path) if inventory_path.is_file() else {}
        source_hash = inventory.get("input_sha256", {}).get("START.goa")
        if gaf_path.is_relative_to(dataset):
            gaf_sha = sha256_file(gaf_path)
        elif source_hash is not None:
            gaf_sha = source_hash
        else:
            gaf_sha = sha256_file(gaf_path)
    if not isinstance(gaf_sha, str) or len(gaf_sha) != 64:
        raise ValueError("Invalid START GOA SHA-256")
    if sha256_file(gaf_path) != gaf_sha:
        raise ValueError("START GOA differs from the setup identity")
    if sha256_file(ontology_path) != ontology_sha:
        raise ValueError("Pinned ontology changed since setup")
    return {
        "release_id": release,
        "gaf_path": gaf_path,
        "gaf_sha256": gaf_sha,
        "ontology_path": ontology_path,
        "ontology_sha256": ontology_sha,
    }


def ia_fingerprint(identity: dict) -> str:
    repository = Path(__file__).resolve().parents[2]
    implementation_paths = (
        "src/progeny/evaluation_artifacts.py",
        "src/progeny/information_accretion_roaring.py",
        "src/progeny/information_accretion.py",
        "src/progeny/ontology.py",
        "src/progeny/stage08_go_closure.py",
        "scripts/evaluation/compute_information_accretion_roaring.py",
        "experiments/ia_roaring/CMakeLists.txt",
        "experiments/ia_roaring/src/main.cpp",
        "experiments/ia_roaring/vendor/CRoaring.lock.json",
        "pixi.lock",
    )
    payload = {
        "schema": "progeny-start-ia-artifact-identity-v1",
        "release_id": identity["release_id"],
        "gaf_sha256": identity["gaf_sha256"],
        "ontology_sha256": identity["ontology_sha256"],
        "policy": IA_POLICY,
        "implementation_sha256": {
            name: sha256_file(repository / name) for name in implementation_paths
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def ia_artifact_dir(dataset: Path, identity: dict) -> Path:
    return (
        shared_artifacts_root(dataset)
        / "START"
        / identity["release_id"]
        / "information_accretion"
        / ia_fingerprint(identity)
    )


def run_cohort_dir(dataset: Path, run: Path, benchmark_sha256: str) -> Path:
    if len(benchmark_sha256) != 64:
        raise ValueError("Invalid benchmark manifest SHA-256")
    return (
        shared_artifacts_root(dataset)
        / "RUNS"
        / run.name
        / benchmark_sha256
        / "knowledge_cohorts"
    )


def validate_ia_artifact(directory: Path, identity: dict) -> tuple[Path, Path]:
    table = directory / "information_accretion.tsv"
    manifest_path = directory / "manifest.json"
    if (
        directory.is_symlink()
        or not directory.is_dir()
        or directory.absolute().resolve(strict=True) != directory.absolute()
    ):
        raise ValueError("IA artifact directory is missing or invalid")
    if {path.name for path in directory.iterdir()} != {
        "information_accretion.tsv",
        "manifest.json",
    }:
        raise ValueError("IA publication file inventory is unexpected")
    if directory.name != ia_fingerprint(identity):
        raise ValueError("IA artifact directory fingerprint is inconsistent")
    for path in (table, manifest_path):
        if path.is_symlink() or not path.is_file():
            raise ValueError("IA publication is missing a regular artifact")
    manifest = _read_json(manifest_path)
    if (
        manifest.get("schema") != IA_SCHEMA
        or manifest.get("status") != "COMPUTED"
        or manifest.get("source_role") != "START"
        or manifest.get("source_release_id") != identity["release_id"]
        or manifest.get("gaf_sha256") != identity["gaf_sha256"]
        or manifest.get("ontology_sha256") != identity["ontology_sha256"]
        or manifest.get("artifact_fingerprint") != ia_fingerprint(identity)
        or manifest.get("ia_table_sha256") != sha256_file(table)
    ):
        raise ValueError("IA publication does not match the configured START identity")
    for key, value in IA_POLICY.items():
        if key == "schema":
            continue
        if manifest.get(key) != value:
            raise ValueError(f"IA publication policy mismatch: {key}")
    return table, manifest_path
