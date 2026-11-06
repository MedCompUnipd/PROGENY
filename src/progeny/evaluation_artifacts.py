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
IA_PROFILES = ("all-positive", "score-experimental", "cafa4-experimental")
SCORE_CODES = (
    "EXP",
    "HDA",
    "HEP",
    "HGI",
    "HMP",
    "HTP",
    "IDA",
    "IEP",
    "IGI",
    "IMP",
    "IPI",
)


def ia_policy(profile: str = "all-positive") -> dict:
    if profile not in IA_PROFILES:
        raise ValueError(f"Unsupported IA profile: {profile}")
    policy = dict(IA_POLICY)
    if profile != "all-positive":
        extra = ("TAS", "IC") if profile == "cafa4-experimental" else ()
        codes = sorted((*SCORE_CODES, *extra))
        policy["evidence_policy"] = profile
        policy["evidence_codes"] = codes
    return policy


# The published v3 all-positive builder identity, pinned before policy support.
LEGACY_IA_IMPLEMENTATION = dict(
    zip(
        (
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
        ),
        (
            "39c8c9a377c970b472ca7b04c22af5aba92a8a0885379bd17c64ee44dbf91811",
            "77b28f224929782d9c7460b9494f54289e78024acd24226eb17a4dd2148bb6b7",
            "0e62fc24741c66361f9fb9e0cc971c88a467f85197b15244da0173157901d848",
            "04eb9409eb17402ac225f19869b10db9ff9ef26f3fcc01f0c7eac180a5ba7ace",
            "0edf51a1cbff2ca0eccda63b863f5836b481bb4cc424dcc9f856037452119393",
            "ea64f84b457ea1b2e1d8e22695072e0f5e7dfb35207a63bc0c2599d81a733265",
            "ff0c2a56b4a75bc361f91dc27bc289aec24f200b4d1c167837e83ebabf7ddb41",
            "daa6a1659a1755bddbbfa6d23e7ad00fcb21e6f2b88ecec70e46e6d73bfa6a87",
            "9b9a16e1352b2f7b3b027c23b4b01dde8b59c0123abc20b87278e222c937b255",
            "f47af9d719a332d87f2a40843e04d48e0de96c8151183ba0ea358414efe62600",
        ),
        strict=True,
    )
)


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


def ia_fingerprint(
    identity: dict, profile: str = "all-positive", *, legacy: bool = False
) -> str:
    if legacy and profile != "all-positive":
        raise ValueError("Only all-positive has a legacy artifact identity")
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
        "policy": ia_policy(profile),
        "implementation_sha256": (
            LEGACY_IA_IMPLEMENTATION
            if legacy
            else {name: sha256_file(repository / name) for name in implementation_paths}
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def ia_artifact_dir(
    dataset: Path,
    identity: dict,
    profile: str = "all-positive",
    *,
    legacy: bool = False,
) -> Path:
    return (
        shared_artifacts_root(dataset)
        / "START"
        / identity["release_id"]
        / "information_accretion"
        / ia_fingerprint(identity, profile, legacy=legacy)
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


def validate_ia_artifact(
    directory: Path,
    identity: dict,
    profile: str = "all-positive",
    *,
    legacy: bool = False,
) -> tuple[Path, Path]:
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
    fingerprint = ia_fingerprint(identity, profile, legacy=legacy)
    if directory.name != fingerprint:
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
        or manifest.get("artifact_fingerprint") != fingerprint
        or manifest.get("ia_table_sha256") != sha256_file(table)
    ):
        raise ValueError("IA publication does not match the configured START identity")
    for key, value in ia_policy(profile).items():
        if key == "schema":
            continue
        if manifest.get(key) != value:
            raise ValueError(f"IA publication policy mismatch: {key}")
    if profile == "all-positive" and "evidence_codes" in manifest:
        raise ValueError("All-positive IA must not carry an evidence-code filter")
    if legacy and any(
        manifest.get("implementation_sha256", {}).get(name) != digest
        for name, digest in LEGACY_IA_IMPLEMENTATION.items()
        if name.startswith("src/") or name.startswith("scripts/")
    ):
        raise ValueError("Legacy IA implementation identity mismatch")
    return table, manifest_path


def resolve_ia_artifact(
    dataset: Path, identity: dict, profile: str = "all-positive"
) -> tuple[Path, Path, Path]:
    directory = ia_artifact_dir(dataset, identity, profile)
    if directory.exists():
        return directory, *validate_ia_artifact(directory, identity, profile)
    if profile == "all-positive":
        legacy = ia_artifact_dir(dataset, identity, profile, legacy=True)
        if legacy.exists():
            return legacy, *validate_ia_artifact(legacy, identity, profile, legacy=True)
    raise ValueError("Matching START IA artifact is unavailable")
