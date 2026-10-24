"""Safety and boundary tests for fresh preparation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from canonical_v2_fresh_raw_fixture import create_raw_fixture

from progeny.canonical_v2 import fresh_dag
from progeny.canonical_v2.fresh_preparation import prepare


def test_existing_run_is_never_overwritten(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src/progeny/canonical_v2").mkdir(parents=True)
    (repo / "src/progeny/canonical_v2/fresh_dag.py").write_text("\n")
    run = tmp_path / "old-run"
    run.mkdir()
    sentinel = run / "keep.txt"
    sentinel.write_text("do not overwrite")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"pipeline": {}, "recipe": {}}))
    with pytest.raises(FileExistsError):
        prepare(repo=repo, run=run, spec_path=spec)
    assert sentinel.read_text() == "do not overwrite"


def test_run_cannot_be_inside_source_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src/progeny/canonical_v2").mkdir(parents=True)
    (repo / "src/progeny/canonical_v2/fresh_dag.py").write_text("\n")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"pipeline": {}, "recipe": {}}))
    with pytest.raises(ValueError, match="overlap"):
        prepare(repo=repo, run=repo / "run", spec_path=spec)
    assert not (repo / "run").exists()


def test_reject_non_absolute_run(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src/progeny/canonical_v2").mkdir(parents=True)
    (repo / "src/progeny/canonical_v2/fresh_dag.py").write_text("\n")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"pipeline": {}, "recipe": {}}))
    with pytest.raises(ValueError, match="absolute"):
        prepare(repo=repo, run=Path("relative-run"), spec_path=spec)


def _synthetic_spec(tmp_path: Path) -> tuple[Path, Path, dict]:
    repo = Path(fresh_dag.__file__).resolve().parents[3]
    placeholder = repo / "cpp/src/progeny_directional_glocal_bounded_dp_v2.cpp"
    old_recipe = create_raw_fixture(
        repo=repo, run=tmp_path / "source", dp_binary=placeholder
    )
    old = json.loads(old_recipe.read_text(encoding="utf-8"))
    pipeline = yaml.safe_load(
        (tmp_path / "source/pipeline.stage08.collection.yaml").read_text(
            encoding="utf-8"
        )
    )
    options = {
        key: value
        for key, value in old.items()
        if key not in {"schema", "repo_root", "run_root", "pipeline_config"}
    }
    spec = tmp_path / "spec.json"
    return repo, spec, {"pipeline": pipeline, "recipe": options}


@pytest.mark.parametrize("name", ("partial_sequence", "documentary_fragment"))
def test_reject_divergent_annotation_policies(tmp_path: Path, name: str) -> None:
    repo, spec, data = _synthetic_spec(tmp_path)
    data["pipeline"]["annotation_donor"][name] = "report_only"
    assert data["recipe"]["limits"][name] == "allow"
    spec.write_text(json.dumps(data), encoding="utf-8")
    run = tmp_path / "prepared"
    with pytest.raises(ValueError, match=f"annotation_donor.{name} differs"):
        prepare(repo=repo, run=run, spec_path=spec)
    assert not run.exists()


def test_reject_wrong_pinned_ontology_hash(tmp_path: Path) -> None:
    repo, spec, data = _synthetic_spec(tmp_path)
    data["pipeline"]["ontology"]["expected_sha256"] = "0" * 64
    spec.write_text(json.dumps(data), encoding="utf-8")
    run = tmp_path / "prepared"
    with pytest.raises(ValueError, match="ontology.expected_sha256 does not match"):
        prepare(repo=repo, run=run, spec_path=spec, hash_biological_inputs=True)
    assert not run.exists()


def test_new_preparation_owns_run_local_transient_and_checkpoint(tmp_path):
    repo, spec, data = _synthetic_spec(tmp_path)
    spec.write_text(json.dumps(data), encoding="utf-8")
    run = tmp_path / "prepared"
    report = prepare(repo=repo, run=run, spec_path=spec)
    assert Path(report["run"]) == run
    from progeny.canonical_v2.run_isolation import validate_scratch

    scratch, transient = validate_scratch(run, data["recipe"]["identity_sha256"])
    assert scratch == run / "tmp"
    assert transient == run / "tmp/transient"
    assert (run / "tmp/checkpoints").is_dir()


def test_new_preparation_normalizes_optional_dp_scratch(tmp_path):
    repo, spec, data = _synthetic_spec(tmp_path)
    data["recipe"]["large_dp"] = {
        "binary": str(repo / "cpp/src/progeny_directional_glocal_bounded_dp_v2.cpp"),
        "max_dp_memory_bytes": 536870912,
        "checkpoint_rows": 256,
    }
    spec.write_text(json.dumps(data), encoding="utf-8")
    run = tmp_path / "prepared"
    prepare(repo=repo, run=run, spec_path=spec)
    recipe = json.loads((run / "fresh_recipe.json").read_text(encoding="utf-8"))
    assert recipe["large_dp"]["scratch_root"] == str(run / "tmp")
    assert fresh_dag.read_recipe(run / "fresh_recipe.json").run == run


def test_new_preparation_rejects_explicit_foreign_scratch(tmp_path):
    repo, spec, data = _synthetic_spec(tmp_path)
    data["recipe"]["large_dp"] = {
        "binary": str(repo / "cpp/src/progeny_directional_glocal_bounded_dp_v2.cpp"),
        "max_dp_memory_bytes": 536870912,
        "checkpoint_rows": 256,
        "scratch_root": str(tmp_path / "outside"),
    }
    spec.write_text(json.dumps(data), encoding="utf-8")
    run = tmp_path / "prepared"
    with pytest.raises(ValueError, match="RUN/tmp"):
        prepare(repo=repo, run=run, spec_path=spec)
    assert not run.exists()
