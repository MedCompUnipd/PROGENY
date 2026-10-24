"""Safety and isolation tests for run-owned PROGENY scratch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from progeny.canonical_v2 import fresh_control, run_isolation


@pytest.fixture
def owned(tmp_path: Path):
    run = tmp_path / "run"
    run.mkdir()
    identity = "a" * 64
    run_isolation.create_scratch(run, identity)
    return run, identity


def test_scratch_owner_and_two_runs_are_distinct(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for run in (first, second):
        run_isolation.create_scratch(run, "a" * 64)
    assert (
        run_isolation.validate_scratch(first, "a" * 64)[0]
        != (run_isolation.validate_scratch(second, "a" * 64)[0])
    )


def test_transient_cleanup_preserves_resume_checkpoints(owned) -> None:
    run, identity = owned
    scratch, transient, checkpoints = run_isolation.scratch_paths(run)
    (transient / "job.tmp").write_text("removable", encoding="utf-8")
    nested = transient / "nested"
    nested.mkdir()
    (nested / "another.tmp").write_text("removable", encoding="utf-8")
    (checkpoints / "dp.bin").write_text("resume", encoding="utf-8")
    assert run_isolation.clean_transient(run, identity) == 2
    assert not list(transient.iterdir())
    assert (checkpoints / "dp.bin").read_text() == "resume"
    assert (scratch / run_isolation.OWNER).is_file()
    assert run_isolation.clean_transient(run, identity) == 0


def test_wrong_run_identity_fails_closed(owned) -> None:
    run, _ = owned
    with pytest.raises(ValueError, match="ownership"):
        run_isolation.validate_scratch(run, "b" * 64)


def test_symlinked_transient_is_refused(owned, tmp_path: Path) -> None:
    run, identity = owned
    _, transient, _ = run_isolation.scratch_paths(run)
    transient.rmdir()
    other = tmp_path / "other"
    other.mkdir()
    transient.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="Unsafe"):
        run_isolation.validate_scratch(run, identity)
    assert other.is_dir()


def test_symlink_inside_transient_is_refused_without_removal(owned, tmp_path) -> None:
    run, identity = owned
    _, transient, _ = run_isolation.scratch_paths(run)
    outside = tmp_path / "protected"
    outside.write_text("keep", encoding="utf-8")
    (transient / "bad-link").symlink_to(outside)
    with pytest.raises(ValueError, match="Symlink"):
        run_isolation.clean_transient(run, identity)
    assert outside.read_text() == "keep"


def test_cleanup_requires_success_and_deep_verification(owned) -> None:
    run, identity = owned
    _, transient, _ = run_isolation.scratch_paths(run)
    file = transient / "data.tmp"
    file.write_text("keep", encoding="utf-8")
    recipe = type("RecipeStub", (), {})()
    recipe.run = run
    recipe.sha256 = "b" * 64
    recipe.data = {"identity_sha256": identity}
    (run / "preparation.attestation.json").write_text(
        json.dumps(
            {
                "schema": "progeny-fresh-preparation-attestation-v1",
                "identity_sha256": identity,
                "scratch_policy": run_isolation.POLICY,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="control file"):
        fresh_control.cleanup(recipe)
    assert file.read_text() == "keep"
    with (
        patch.object(
            fresh_control, "_verify_locked", return_value={"status": "PASS"}
        ) as verified,
        patch.object(fresh_control, "_scratch", return_value=(run / "tmp", transient)),
    ):
        result = fresh_control.cleanup(recipe)
    assert verified.call_count == 1
    assert result["status"] == "TRANSIENT_CLEANED"
    assert not file.exists()


def test_snakemake_tmpdir_and_process_environment(owned) -> None:
    run, identity = owned
    root, transient, _ = run_isolation.scratch_paths(run)
    recipe = type("RecipeStub", (), {})()
    recipe.run = run
    recipe.repo = run.parent / "checkout"
    recipe.path = run / "fresh_recipe.json"
    recipe.sha256 = "b" * 64
    recipe.data = {"identity_sha256": identity}
    (run / "preparation.attestation.json").write_text(
        json.dumps(
            {
                "schema": "progeny-fresh-preparation-attestation-v1",
                "identity_sha256": identity,
                "scratch_policy": run_isolation.POLICY,
            }
        ),
        encoding="utf-8",
    )
    with (
        patch.object(fresh_control, "_snakemake", return_value=Path("/fake/snake")),
        patch.object(fresh_control, "preflight", return_value={}),
        patch.object(fresh_control.subprocess, "run") as invoke,
    ):
        invoke.return_value = subprocess.CompletedProcess([], 0)
        result = fresh_control.execute(
            recipe, mode="first", cores=2, memory_mb=4096, dry_run=True
        )
    assert result["status"] == "DRY_RUN_PASS"
    command = invoke.call_args.args[0]
    assert command[command.index("--directory") + 1] == str(run)
    assert invoke.call_args.kwargs["cwd"] == run
    assert command[command.index("--default-resources") + 1] == (
        f"tmpdir={str(transient)!r}"
    )
    env = invoke.call_args.kwargs["env"]
    assert all(env[key] == str(transient) for key in ("TMPDIR", "TMP", "TEMP"))
    assert root != transient
