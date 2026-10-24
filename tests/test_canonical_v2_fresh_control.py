"""Safety tests for the independent fresh-run control and completion wrapper."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from canonical_v2_fresh_raw_fixture import create_raw_fixture

from progeny.canonical_v2 import fresh_control
from progeny.canonical_v2.fresh_dag import read_recipe


@pytest.fixture
def prepared(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tool = repo / "fake-bounded"
    tool.write_bytes(b"synthetic")
    path = create_raw_fixture(repo=repo, run=tmp_path / "run", dp_binary=tool)
    recipe_data = json.loads(path.read_text(encoding="utf-8"))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    recipe_data["large_dp"] = {
        "binary": str(tool),
        "max_dp_memory_bytes": 536870912,
        "checkpoint_rows": 256,
        "scratch_root": str(scratch),
    }
    path.write_text(json.dumps(recipe_data), encoding="utf-8")
    recipe = read_recipe(path, expected_repo=repo)
    (recipe.run / "preparation.attestation.json").write_text(
        json.dumps(
            {
                "schema": "progeny-fresh-preparation-attestation-v1",
                "identity_sha256": recipe.data["identity_sha256"],
            }
        ),
        encoding="utf-8",
    )
    snake = repo / ".pixi/envs/default/bin/snakemake"
    snake.parent.mkdir(parents=True)
    snake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    snake.chmod(0o700)
    return recipe


def test_unpublished_fresh_preflight_is_non_destructive(prepared):
    result = fresh_control.preflight(prepared)
    assert result["validation"] == "STRUCTURAL_ONLY"
    assert result["receipt_count"] == 0
    assert result["upstream_checked"] == 0
    assert not (prepared.run / "canonical").exists()


def test_refuse_orphaned_canonical_without_spec(prepared):
    orphan = prepared.run / "canonical" / "payload"
    orphan.mkdir(parents=True)
    with pytest.raises(ValueError, match="without a specification"):
        fresh_control.preflight(prepared)


def test_refuse_canonical_provenance_without_spec(prepared):
    provenance = prepared.run / "plans/canonical_spec.provenance.json"
    provenance.parent.mkdir()
    provenance.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Orphaned canonical provenance"):
        fresh_control.preflight(prepared)


def test_resumption_requires_confirmed_shutdown(prepared):
    with pytest.raises(ValueError, match="explicit confirmation"):
        fresh_control.execute(prepared, mode="resume", cores=2, memory_mb=2048)
    assert not (prepared.run / ".canonical_v2_control.lock").exists()


def test_first_run_rejects_existing_scientific_state(prepared):
    (prepared.run / "work").mkdir()
    with pytest.raises(ValueError, match="already has scientific state"):
        fresh_control.execute(prepared, mode="first", cores=1, memory_mb=2048)


def test_verification_requires_owned_success_marker(prepared):
    with pytest.raises(ValueError, match="control file"):
        fresh_control.verify(prepared)


def test_dry_run_cannot_publish_success(prepared):
    with patch.object(fresh_control.subprocess, "run") as invoke:
        invoke.return_value = subprocess.CompletedProcess([], 0)
        result = fresh_control.execute(
            prepared,
            mode="first",
            cores=2,
            memory_mb=4096,
            dry_run=True,
        )
    assert result["status"] == "DRY_RUN_PASS"
    assert "--dry-run" in invoke.call_args.args[0]
    assert invoke.call_args.kwargs["cwd"] == prepared.repo
    assert "--rerun-incomplete" not in invoke.call_args.args[0]
    assert "--forceall" not in invoke.call_args.args[0]
    assert not fresh_control._success_path(prepared).exists()


def test_execution_failure_does_not_publish_success(prepared):
    with patch.object(fresh_control.subprocess, "run") as invoke:
        invoke.return_value = subprocess.CompletedProcess([], 13)
        with pytest.raises(RuntimeError, match="code 13"):
            fresh_control.execute(prepared, mode="first", cores=2, memory_mb=4096)
    assert not fresh_control._success_path(prepared).exists()


def test_completed_workflow_invokes_frozen_verifier(prepared):
    spec = {"schema": "fixture-only"}
    path = prepared.plan_path("canonical_spec")

    def finished(*args, **kwargs):
        path.parent.mkdir()
        path.write_text(json.dumps(spec), encoding="utf-8")
        return subprocess.CompletedProcess([], 0)

    with (
        patch.object(fresh_control.subprocess, "run", side_effect=finished),
        patch.object(fresh_control, "read_dag_spec", return_value=spec),
        patch.object(fresh_control, "validate_completed_workflow") as audit,
    ):
        audit.return_value = {"status": "PASS", "canonical_publications": 16}
        result = fresh_control.execute(prepared, mode="first", cores=2, memory_mb=4096)
        assert audit.call_count == 1
    assert result["canonical_publications"] == 16
    assert fresh_control._success_path(prepared).is_file()


def test_resume_reuses_valid_existing_run(prepared):
    with patch.object(fresh_control.subprocess, "run") as invoke:
        invoke.return_value = subprocess.CompletedProcess([], 0)
        result = fresh_control.execute(
            prepared,
            mode="resume",
            cores=2,
            memory_mb=4096,
            confirmed_stopped=True,
            dry_run=True,
        )
    assert result["status"] == "DRY_RUN_PASS"
    assert invoke.call_count == 1


def test_scratch_shares_filesystem(prepared):
    assert fresh_control._scratch(prepared)[0].is_dir()


def test_load_rejects_foreign_checkout(prepared):
    foreign = prepared.run.parent / "foreign"
    foreign.mkdir()
    with pytest.raises(ValueError, match="different source checkout"):
        fresh_control.load(prepared.path, foreign)


def _r8_profile(path: Path) -> Path:
    profile = {
        "schema": "progeny-fresh-runtime-resources-v1",
        "m8_workers": 2,
        "temporal_workers": 8,
        "m8_mem_mb": 8192,
        "m10c_mem_mb": 16384,
        "temporal_mem_mb": 32768,
    }
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def test_r8_first_dry_run_passes_validated_performance_profile(prepared):
    profile = _r8_profile(prepared.run.parent / "perf.json")
    with patch.object(fresh_control.subprocess, "run") as invoke:
        invoke.return_value = subprocess.CompletedProcess([], 0)
        result = fresh_control.execute(
            prepared,
            mode="first",
            cores=8,
            memory_mb=65536,
            performance_profile=profile,
            dry_run=True,
        )
    assert result["status"] == "DRY_RUN_PASS"
    command = invoke.call_args.args[0]
    assert command[command.index("--config") + 1] == (f"fresh_recipe={prepared.path}")
    assert f"performance_profile={profile}" in command
    assert not fresh_control._success_path(prepared).exists()


def test_r8_resume_dry_run_preserves_profile(prepared):
    profile = _r8_profile(prepared.run.parent / "resume-perf.json")
    with patch.object(fresh_control.subprocess, "run") as invoke:
        invoke.return_value = subprocess.CompletedProcess([], 0)
        fresh_control.execute(
            prepared,
            mode="resume",
            cores=8,
            memory_mb=65536,
            confirmed_stopped=True,
            performance_profile=profile,
            dry_run=True,
        )
    assert f"performance_profile={profile}" in invoke.call_args.args[0]


@pytest.mark.parametrize("name", ("relative", "missing", "symlink", "invalid"))
def test_r8_invalid_profile_is_rejected_before_snakemake(prepared, name):
    root = prepared.run.parent
    if name == "relative":
        profile = Path("resources.json")
    elif name == "missing":
        profile = root / "missing-resources.json"
    elif name == "symlink":
        original = _r8_profile(root / "target.json")
        profile = root / "linked.json"
        profile.symlink_to(original)
    else:
        profile = root / "invalid.json"
        profile.write_text('{"schema":"wrong"}', encoding="utf-8")
    with (
        patch.object(fresh_control.subprocess, "run") as invoke,
        pytest.raises(ValueError),
    ):
        fresh_control.execute(
            prepared,
            mode="first",
            cores=8,
            memory_mb=65536,
            performance_profile=profile,
            dry_run=True,
        )
    invoke.assert_not_called()


def test_r8_no_profile_remains_serial_by_default(prepared):
    with patch.object(fresh_control.subprocess, "run") as invoke:
        invoke.return_value = subprocess.CompletedProcess([], 0)
        fresh_control.execute(
            prepared, mode="first", cores=8, memory_mb=65536, dry_run=True
        )
    command = invoke.call_args.args[0]
    assert all(not value.startswith("performance_profile=") for value in command)


def test_r8_cli_forwards_profile_to_control(prepared, monkeypatch, capsys):
    profile = _r8_profile(prepared.run.parent / "cli-perf.json")
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts/pipeline/control_canonical_v2_fresh.py"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "--recipe",
            str(prepared.path),
            "first",
            "--cores",
            "8",
            "--memory-mb",
            "65536",
            "--performance-profile",
            str(profile),
            "--dry-run",
        ],
    )
    with (
        patch.object(fresh_control, "load", return_value=prepared),
        patch.object(fresh_control, "execute", return_value={"ok": True}) as execute,
    ):
        runpy.run_path(str(script), run_name="__main__")
    assert execute.call_args.kwargs["performance_profile"] == profile
    assert '"ok": true' in capsys.readouterr().out
