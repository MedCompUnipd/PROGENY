from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from progeny.evaluation_artifacts import (
    LEGACY_IA_IMPLEMENTATION,
    ia_artifact_dir,
    ia_fingerprint,
    ia_policy,
    resolve_ia_artifact,
    run_cohort_dir,
    shared_artifacts_root,
    start_identity,
)


def test_evidence_profiles_have_distinct_complete_identities():
    from progeny.knowledge_cohorts import SCORE_EVIDENCE_CODES

    identity = {
        "release_id": "start-a",
        "gaf_sha256": "a" * 64,
        "ontology_sha256": "b" * 64,
    }
    profiles = ("all-positive", "score-experimental", "cafa4-experimental")
    assert len({ia_fingerprint(identity, profile) for profile in profiles}) == 3
    experimental = set(ia_policy("score-experimental")["evidence_codes"])
    assert experimental == SCORE_EVIDENCE_CODES
    assert len(experimental) == 11
    assert not experimental & {"TAS", "IC"}
    assert set(ia_policy("cafa4-experimental")["evidence_codes"]) == (
        experimental | {"TAS", "IC"}
    )
    with pytest.raises(ValueError):
        ia_policy("unknown")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dataset(path: Path, *, release: str = "start-a", gaf_body: bytes = b"gaf"):
    (path / "config").mkdir(parents=True)
    gaf = path / "prepared/START/goa.gaf"
    gaf.parent.mkdir(parents=True)
    gaf.write_bytes(gaf_body)
    ontology = path / "ontology.owl"
    ontology.write_bytes(b"pinned ontology")
    spec = {
        "pipeline": {
            "releases": {"START": {"release_id": release, "goa": str(gaf)}},
            "ontology": {"path": str(ontology), "expected_sha256": _sha(ontology)},
        }
    }
    (path / "config/fresh-spec.json").write_text(json.dumps(spec))
    summary = {
        "shared_artifacts_root": str(path.parent / "PROGENY_SHARED"),
        "start_gaf_sha256": _sha(gaf),
    }
    (path / "config/setup-summary.json").write_text(json.dumps(summary))
    return path


def test_legacy_ia_resolution_checks_identity_and_table(tmp_path):
    dataset = _dataset(tmp_path / "dataset")
    identity = start_identity(dataset)
    directory = ia_artifact_dir(dataset, identity, legacy=True)
    directory.mkdir(parents=True)
    table = directory / "information_accretion.tsv"
    table.write_text("legacy IA\n", encoding="utf-8")
    manifest = {
        **ia_policy(),
        "status": "COMPUTED",
        "source_release_id": identity["release_id"],
        "gaf_sha256": identity["gaf_sha256"],
        "ontology_sha256": identity["ontology_sha256"],
        "artifact_fingerprint": directory.name,
        "ia_table_sha256": _sha(table),
        "implementation_sha256": {
            name: digest
            for name, digest in LEGACY_IA_IMPLEMENTATION.items()
            if name.startswith(("src/", "scripts/"))
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert resolve_ia_artifact(dataset, identity) == (
        directory,
        table,
        directory / "manifest.json",
    )
    with pytest.raises(ValueError, match="unavailable"):
        resolve_ia_artifact(dataset, identity, "score-experimental")
    table.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        resolve_ia_artifact(dataset, identity)


def test_start_ia_store_is_shared_by_sibling_runs(tmp_path):
    dataset_a = _dataset(tmp_path / "study-a-dataset")
    dataset_b = _dataset(tmp_path / "study-b-dataset")
    identity_a = start_identity(dataset_a)
    identity_b = start_identity(dataset_b)

    assert ia_fingerprint(identity_a) == ia_fingerprint(identity_b)
    assert ia_artifact_dir(dataset_a, identity_a) == ia_artifact_dir(
        dataset_b, identity_b
    )
    assert ia_artifact_dir(dataset_a, identity_a).is_relative_to(
        tmp_path / "PROGENY_SHARED/START/start-a/information_accretion"
    )


def test_ia_fingerprint_changes_with_start_source_identity(tmp_path):
    dataset = _dataset(tmp_path / "study-dataset")
    identity_a = start_identity(dataset)
    dataset_b = _dataset(
        tmp_path / "other-dataset", release="start-b", gaf_body=b"other GAF"
    )
    assert ia_fingerprint(identity_a) != ia_fingerprint(start_identity(dataset_b))


def test_cohort_path_is_scoped_to_run_and_benchmark(tmp_path):
    dataset = _dataset(tmp_path / "study-dataset")
    run_a = tmp_path / "study-run-a"
    run_b = tmp_path / "study-run-b"
    first = run_cohort_dir(dataset, run_a, "a" * 64)
    assert first != run_cohort_dir(dataset, run_b, "a" * 64)
    assert first != run_cohort_dir(dataset, run_a, "b" * 64)


def test_shared_root_mismatch_is_rejected(tmp_path):
    dataset = _dataset(tmp_path / "study-dataset")
    summary = json.loads(
        (dataset / "config/setup-summary.json").read_text(encoding="utf-8")
    )
    summary["shared_artifacts_root"] = str(tmp_path / "wrong-root")
    (dataset / "config/setup-summary.json").write_text(json.dumps(summary))

    with pytest.raises(ValueError, match="disagrees"):
        shared_artifacts_root(dataset)


def test_start_ontology_checksum_mismatch_is_rejected(tmp_path):
    dataset = _dataset(tmp_path / "study-dataset")
    ontology = dataset / "ontology.owl"
    ontology.write_bytes(b"changed ontology")

    with pytest.raises(ValueError, match="ontology changed"):
        start_identity(dataset)
