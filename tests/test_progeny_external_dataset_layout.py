"""Regression checks for the standalone external-input layout utility."""

from __future__ import annotations

import gzip
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / (
    "scripts/installation/init_progeny_dataset.py"
)


def _call(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(str(arg) for arg in args)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def fixture(tmp_path: Path) -> dict:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "config").mkdir()
    template = {
        "targets": {"mode": "canonical", "fasta": "X", "metadata": "X"},
        "releases": {
            role: {
                "release_id": role,
                "uniprot_sources": ["X"],
                "goa": "X",
                "taxonomy": {
                    "snapshot_id": "X",
                    "nodes": "X",
                    "names": "X",
                    "merged": "X",
                    "deleted": "X",
                },
            }
            for role in ("START", "END")
        },
        "ontology": {"path": "X", "expected_sha256": None},
        "locations": {"work": "X", "output": "X", "logs": "X"},
        "scientific": {"policy": "unchanged"},
    }
    (repo / "config/pipeline.yaml").write_text(yaml.safe_dump(template))
    root = tmp_path / "datasets" / "study"
    run = tmp_path / "runs" / "study-run"
    root.parent.mkdir()
    run.parent.mkdir()
    return {"repo": repo, "root": root, "run": run}


def _init(fixture: dict, *options: str) -> subprocess.CompletedProcess[str]:
    return _call(
        "init",
        "--repo",
        fixture["repo"],
        "--dataset-root",
        fixture["root"],
        "--run-root",
        fixture["run"],
        "--start-release",
        "2023_01",
        "--end-release",
        "2026_03",
        "--start-taxonomy",
        "tax_2023",
        "--end-taxonomy",
        "tax_2026",
        *options,
    )


def _fill(root: Path, *, compressed_goa: bool = False) -> None:
    layout = json.loads((root / "config/dataset-layout.json").read_text())
    paths = layout["paths"]
    for label in ("source_fasta", "targets_fasta", "targets_metadata"):
        target = Path(paths[label])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(">t\nACDEFGHIKLMN\n")
    Path(paths["targets_manifest"]).write_text("{}\n")
    Path(paths["ontology"]).write_text("<owl/>\n")
    Path(paths["evidence_registry"]).write_text("{}\n")
    Path(paths["temporal_policy"]).write_text("{}\n")
    for role in ("START", "END"):
        for short in ("sprot", "trembl"):
            file = Path(paths[f"{role}.uniprot_{short}"])
            if layout["formats"][role][short] == "gzip":
                with gzip.open(file, "wb") as handle:
                    handle.write(b"ID   SYNTHETIC\n//\n")
            else:
                file.write_bytes(b"ID   SYNTHETIC\n//\n")
        goa = Path(paths[f"{role}.goa_raw"])
        if compressed_goa:
            with gzip.open(goa, "wb") as handle:
                handle.write(b"!gaf-version: 2.2\n")
        else:
            goa.write_text("!gaf-version: 2.2\n")
        for filename in ("nodes.dmp", "names.dmp", "merged.dmp", "delnodes.dmp"):
            Path(paths[f"{role}.taxonomy.{filename}"]).write_text("1\t|\t1\n")


def test_layout_separates_repo_dataset_and_virgin_run(fixture: dict) -> None:
    result = _init(fixture)
    assert result.returncode == 0, result.stderr
    root = fixture["root"]
    assert not (root / "input/START/taxonomy/nodes.dmp").is_file()
    assert (root / "input/END/uniprot").is_dir()
    assert not (root / "input/targets").exists()
    assert not fixture["run"].exists()
    content = yaml.safe_load((root / "config/pipeline.yaml").read_text())
    assert content["targets"]["fasta"] == str(root / "input/targets/targets.fasta")
    assert content["releases"]["END"]["release_id"] == "2026_03"
    assert content["scientific"] == {"policy": "unchanged"}


def test_cannot_initialize_twice(fixture: dict) -> None:
    assert _init(fixture).returncode == 0
    assert _init(fixture).returncode != 0


def test_reject_repository_overlap(fixture: dict) -> None:
    fixture["root"] = fixture["repo"] / "data"
    assert _init(fixture).returncode != 0
    assert not fixture["root"].exists()


def test_reject_run_overlap(fixture: dict) -> None:
    fixture["run"] = fixture["root"] / "run"
    assert _init(fixture).returncode != 0
    assert not fixture["root"].exists()


def test_reject_existing_run(fixture: dict) -> None:
    fixture["run"].mkdir()
    assert _init(fixture).returncode != 0
    assert not fixture["root"].exists()


def test_preflight_rejects_missing_files(fixture: dict) -> None:
    assert _init(fixture).returncode == 0
    result = _call("check", "--dataset-root", fixture["root"])
    assert result.returncode != 0


def test_plain_goa_checks_and_seals_ontology(fixture: dict) -> None:
    assert _init(fixture).returncode == 0
    _fill(fixture["root"])
    assert _call("check", "--dataset-root", fixture["root"]).returncode != 0
    result = _call("check", "--dataset-root", fixture["root"], "--seal")
    assert result.returncode == 0, result.stderr
    config = yaml.safe_load((fixture["root"] / "config/pipeline.yaml").read_text())
    assert len(config["ontology"]["expected_sha256"]) == 64
    assert _call("check", "--dataset-root", fixture["root"]).returncode == 0
    assert not fixture["run"].exists()


def test_gzip_goa_requires_materialization(fixture: dict) -> None:
    result = _init(fixture, "--start-goa", "gzip", "--end-goa", "gzip")
    assert result.returncode == 0, result.stderr
    _fill(fixture["root"], compressed_goa=True)
    first = _call("check", "--dataset-root", fixture["root"], "--seal")
    assert first.returncode != 0
    second = _call(
        "check",
        "--dataset-root",
        fixture["root"],
        "--materialize-goa",
        "--seal",
    )
    assert second.returncode == 0, second.stderr
    for role in ("START", "END"):
        assert (fixture["root"] / "prepared" / role / "goa.gaf").read_bytes() == (
            b"!gaf-version: 2.2\n"
        )
    assert _call("check", "--dataset-root", fixture["root"]).returncode == 0
    repeat = _call(
        "check",
        "--dataset-root",
        fixture["root"],
        "--materialize-goa",
        "--seal",
    )
    assert repeat.returncode == 0, repeat.stderr


def test_per_source_plain_and_gzip_compression(fixture: dict) -> None:
    result = _init(fixture, "--start-sprot", "plain", "--end-trembl", "plain")
    assert result.returncode == 0, result.stderr
    _fill(fixture["root"])
    assert _call("check", "--dataset-root", fixture["root"], "--seal").returncode == 0
    assert (fixture["root"] / "input/START/uniprot/uniprot_sprot.dat").is_file()
    assert (fixture["root"] / "input/END/uniprot/uniprot_trembl.dat").is_file()


def test_reject_gzip_mismatch(fixture: dict) -> None:
    assert _init(fixture).returncode == 0
    _fill(fixture["root"])
    path = fixture["root"] / "input/START/uniprot/uniprot_sprot.dat.gz"
    path.write_text("NOT GZIP\n")
    result = _call("check", "--dataset-root", fixture["root"], "--seal")
    assert result.returncode != 0
    assert "Expected gzip header" in result.stderr


def test_reject_ontology_mutation_after_seal(fixture: dict) -> None:
    assert _init(fixture).returncode == 0
    _fill(fixture["root"])
    assert _call("check", "--dataset-root", fixture["root"], "--seal").returncode == 0
    (fixture["root"] / "input/ontology/go.owl").write_text("changed\n")
    assert _call("check", "--dataset-root", fixture["root"]).returncode != 0


def test_bind_rejects_external_tool(fixture: dict) -> None:
    assert _init(fixture).returncode == 0
    template = fixture["root"].parent / "spec.json"
    template.write_text(
        json.dumps(
            {
                "pipeline": {},
                "recipe": {"tools": {"bad": str(template)}},
            }
        )
    )
    result = _call("bind", "--dataset-root", fixture["root"], "--template", template)
    assert result.returncode != 0
    assert not (fixture["root"] / "config/fresh-spec.json").exists()


def test_bind_maps_inputs_and_preserves_other_recipe_fields(fixture: dict) -> None:
    assert _init(fixture).returncode == 0
    _fill(fixture["root"])
    assert _call("check", "--dataset-root", fixture["root"], "--seal").returncode == 0
    tool = fixture["repo"] / "tool.py"
    tool.write_text("pass\n")
    template = fixture["root"].parent / "spec.json"
    template.write_text(
        json.dumps(
            {
                "pipeline": {},
                "recipe": {
                    "tools": {"script": str(tool)},
                    "identity_sha256": "a" * 64,
                    "limits": {"threads": 8},
                },
            }
        )
    )
    result = _call("bind", "--dataset-root", fixture["root"], "--template", template)
    assert result.returncode == 0, result.stderr
    bound = json.loads((fixture["root"] / "config/fresh-spec.json").read_text())
    assert bound["recipe"]["limits"] == {"threads": 8}
    assert bound["recipe"]["targets_input"] == str(
        fixture["root"] / "input/targets/targets.metadata.tsv"
    )
    assert bound["recipe"]["evidence_registry"] == str(
        fixture["root"] / "input/policies/evidence_registry.json"
    )
    assert not fixture["run"].exists()


def test_reject_symlinked_input(fixture: dict) -> None:
    assert _init(fixture).returncode == 0
    _fill(fixture["root"])
    target = fixture["root"] / "input/START/goa/goa.gaf"
    target.unlink()
    target.symlink_to(fixture["root"] / "input/END/goa/goa.gaf")
    result = _call("check", "--dataset-root", fixture["root"], "--seal")
    assert result.returncode != 0
