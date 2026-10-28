from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from progeny.evaluation_artifacts import (
    ia_artifact_dir,
    ia_fingerprint,
    run_cohort_dir,
    shared_artifacts_root,
    start_identity,
)


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
