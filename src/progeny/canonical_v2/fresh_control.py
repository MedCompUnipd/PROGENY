"""Operational gates for canonical V2 fresh runs; no scientific transformations.

A conservative wrapper around the existing upstream validators, immutable
canonical receipts, Snakemake orchestration, and final completion verifier.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from progeny.canonical_v2.dag_contract import destination, read_dag_spec
from progeny.canonical_v2.fresh_dag import (
    COMMON_NODES,
    ROLE_NODES,
    ROLES,
    FreshRecipe,
    publish_json,
    read_recipe,
    validate_completed_workflow,
    validate_existing_upstreams,
)
from progeny.canonical_v2.fresh_publication import (
    receipt_path,
    validate_node_receipt,
)
from progeny.canonical_v2.run_isolation import (
    POLICY,
    clean_transient,
    validate_scratch,
)
from progeny.canonical_v2.runtime_resources import read_runtime_profile
from progeny.workflow.artifacts import sha256_file

SCHEMA = "progeny-canonical-v2-fresh-control-v1"


def _regular(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or unsafe control file: {path}")
    return path


def _physical(directory: Path) -> Path:
    if (
        not directory.is_absolute()
        or ".." in directory.parts
        or directory.is_symlink()
        or not directory.is_dir()
        or directory.resolve(strict=True) != directory
    ):
        raise ValueError(f"Expected a physical directory: {directory}")
    return directory


def load(recipe_path: Path, repo: Path) -> FreshRecipe:
    """Require recipe ownership by the checkout supplying this implementation."""
    return read_recipe(recipe_path, expected_repo=_physical(repo))


def _spec_and_receipts(recipe: FreshRecipe, *, deep: bool) -> dict:
    spec_path = recipe.plan_path("canonical_spec")
    provenance_path = recipe.run / "plans/canonical_spec.provenance.json"
    if not spec_path.exists() and not spec_path.is_symlink():
        if provenance_path.exists() or provenance_path.is_symlink():
            raise ValueError("Orphaned canonical provenance without specification")
        canonical = recipe.run / "canonical"
        if canonical.is_symlink() or (canonical.exists() and any(canonical.iterdir())):
            raise ValueError("Canonical outputs exist without a specification")
        return {"spec": "NOT_YET_PUBLISHED", "receipt_count": 0}

    _regular(spec_path)
    _regular(provenance_path)
    spec = read_dag_spec(spec_path)
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if (
        provenance.get("recipe_sha256") != recipe.sha256
        or provenance.get("identity_sha256") != recipe.data["identity_sha256"]
        or provenance.get("spec_sha256") != sha256_file(spec_path)
        or provenance.get("releases") != spec["releases"]
        or spec.get("content_identity_sha256") is None
    ):
        raise ValueError("Published canonical specification identity differs")

    count = 0
    for stage, role in [
        *((node, role) for node in ROLE_NODES for role in ROLES),
        *((node, None) for node in COMMON_NODES),
    ]:
        bundle = destination(spec, stage, role)
        receipt = receipt_path(bundle)
        intent = Path(f"{bundle}.fresh.intent.json")
        if receipt.exists() or receipt.is_symlink():
            _regular(receipt)
            _regular(intent)
            if not bundle.is_dir() or bundle.is_symlink():
                raise ValueError(f"Receipt has missing or unsafe bundle: {bundle}")
            if deep:
                validate_node_receipt(
                    spec=spec,
                    stage=stage,
                    role=role,
                    recipe_sha256=recipe.sha256,
                )
            count += 1
        elif bundle.exists() or bundle.is_symlink():
            # The existing executor can recover a completed orphan only when
            # its original execution intent is present and intact.
            _regular(intent)
            if bundle.is_symlink() or not bundle.is_dir():
                raise ValueError(f"Unsafe incomplete canonical bundle: {bundle}")
        elif intent.exists() or intent.is_symlink():
            _regular(intent)
    return {"spec": "PUBLISHED", "receipt_count": count}


def preflight(recipe: FreshRecipe, *, deep: bool = False) -> dict:
    """Fail closed on damaged immutable publications before Snakemake starts."""
    checked = validate_existing_upstreams(recipe, deep=deep)
    canonical = _spec_and_receipts(recipe, deep=deep)
    return {
        "schema": SCHEMA,
        "run_root": str(recipe.run),
        "recipe_sha256": recipe.sha256,
        "validation": "DEEP" if deep else "STRUCTURAL_ONLY",
        "upstream_checked": len(checked["complete_verified"])
        if deep
        else len(checked["present_checked"]),
        **canonical,
    }


@contextmanager
def _exclusive_run_lock(recipe: FreshRecipe) -> Iterator[None]:
    """Serialize cooperating run-control commands; Snakemake owns its lock."""
    run = _physical(recipe.run)
    lock = run / ".canonical_v2_control.lock"
    if lock.is_symlink():
        raise ValueError("Symlinked control lock")
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(
                "A controlled canonical operation is already active"
            ) from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _attestation(recipe: FreshRecipe) -> None:
    path = _regular(recipe.run / "preparation.attestation.json")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        value.get("schema") != "progeny-fresh-preparation-attestation-v1"
        or value.get("identity_sha256") != recipe.data["identity_sha256"]
    ):
        raise ValueError("Run lacks a matching preparation attestation")


def _snakemake(recipe: FreshRecipe) -> Path:
    path = recipe.repo / ".pixi/envs/default/bin/snakemake"
    _regular(path)
    if not os.access(path, os.X_OK):
        raise ValueError(f"Snakemake is not executable: {path}")
    return path


def _scratch_policy(recipe: FreshRecipe) -> str | None:
    marker = _regular(recipe.run / "preparation.attestation.json")
    data = json.loads(marker.read_text(encoding="utf-8"))
    return data.get("scratch_policy")


def _scratch(recipe: FreshRecipe) -> tuple[Path, Path]:
    policy = _scratch_policy(recipe)
    if policy == POLICY:
        root, transient = validate_scratch(recipe.run, recipe.data["identity_sha256"])
        if (
            "large_dp" in recipe.data
            and Path(recipe.data["large_dp"]["scratch_root"]) != root
        ):
            raise ValueError("Prepared DP root is not the run-owned scratch")
        return root, transient
    if policy is not None:
        raise ValueError("Unsupported scratch policy")
    # Existing prepared runs keep their frozen recipe and external scratch.
    if "large_dp" not in recipe.data:
        raise ValueError("Legacy controlled run requires explicit DP scratch")
    path = _physical(Path(recipe.data["large_dp"]["scratch_root"]))
    if path.stat().st_dev != recipe.run.stat().st_dev:
        raise ValueError("DP scratch and run must share a filesystem")
    return path, path


def _success_path(recipe: FreshRecipe) -> Path:
    return recipe.run / "control" / f"snakemake-success-{recipe.sha256}.json"


def _success(recipe: FreshRecipe) -> dict:
    path = _regular(_success_path(recipe))
    value = json.loads(path.read_text(encoding="utf-8"))
    if value != {
        "schema": SCHEMA + "-snakemake-success",
        "recipe_sha256": recipe.sha256,
        "exit_code": 0,
    }:
        raise ValueError("Snakemake success marker does not match this recipe")
    return value


def _verify_locked(recipe: FreshRecipe) -> dict:
    _success(recipe)
    spec_path = _regular(recipe.plan_path("canonical_spec"))
    spec = read_dag_spec(spec_path)
    return validate_completed_workflow(recipe, spec)


def verify(recipe: FreshRecipe) -> dict:
    """Call the existing, deep, publication-level canonical completion gate."""
    with _exclusive_run_lock(recipe):
        return _verify_locked(recipe)


def cleanup(recipe: FreshRecipe) -> dict:
    """Explicit final cleanup; checkpoint folders are deliberately retained."""
    with _exclusive_run_lock(recipe):
        _attestation(recipe)
        if _scratch_policy(recipe) != POLICY:
            raise ValueError("Cleanup requires a new run-local scratch contract")
        _scratch(recipe)
        verified = _verify_locked(recipe)
        if verified.get("status") != "PASS":
            raise ValueError("Cleanup requires a verified completed run")
        count = clean_transient(recipe.run, recipe.data["identity_sha256"])
        return {"status": "TRANSIENT_CLEANED", "entries_removed": count}


def execute(
    recipe: FreshRecipe,
    *,
    mode: str,
    cores: int,
    memory_mb: int,
    confirmed_stopped: bool = False,
    dry_run: bool = False,
    performance_profile: Path | None = None,
) -> dict:
    """Run a fresh or conservative resume without destructive Snakemake flags."""
    if mode not in {"first", "resume"}:
        raise ValueError("Mode must be first or resume")
    if type(cores) is not int or cores < 1:
        raise ValueError("cores must be a positive integer")
    if type(memory_mb) is not int or memory_mb < 1:
        raise ValueError("memory_mb must be a positive integer")
    if mode == "resume" and not confirmed_stopped:
        raise ValueError("Resume requires explicit confirmation of stopped jobs")
    if performance_profile is not None:
        read_runtime_profile(str(performance_profile))
    _attestation(recipe)
    _snakemake(recipe)
    _, transient = _scratch(recipe)
    # Legacy prepared runs retain their original Snakemake work directory.
    workdir = recipe.run if _scratch_policy(recipe) == POLICY else recipe.repo

    with _exclusive_run_lock(recipe):
        if mode == "first":
            for name in ("work", "plans", "canonical", "results"):
                path = recipe.run / name
                if path.exists() or path.is_symlink():
                    raise ValueError(f"First run already has scientific state: {name}")
        state = preflight(recipe, deep=not dry_run)
        command = [
            str(_snakemake(recipe)),
            "--snakefile",
            str(recipe.repo / "workflow/canonical_v2_fresh.smk"),
            "--directory",
            str(workdir),
            "--cores",
            str(cores),
            "--resources",
            "dataset_io=1",
            f"mem_mb={memory_mb}",
            "--default-resources",
            f"tmpdir={str(transient)!r}",
            "--latency-wait",
            "120",
            "--config",
            f"fresh_recipe={recipe.path}",
        ]
        if performance_profile is not None:
            command.append(f"performance_profile={performance_profile}")
        if dry_run:
            command.append("--dry-run")
        environment = os.environ.copy()
        environment.update(
            {
                "TMPDIR": str(transient),
                "TMP": str(transient),
                "TEMP": str(transient),
                "PYTHONPATH": str(recipe.repo / "src"),
            }
        )
        result = subprocess.run(
            command,
            cwd=workdir,
            env=environment,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Snakemake exited with code {result.returncode}")
        if dry_run:
            return {"status": "DRY_RUN_PASS", "preflight": state}
        publish_json(
            _success_path(recipe),
            {
                "schema": SCHEMA + "-snakemake-success",
                "recipe_sha256": recipe.sha256,
                "exit_code": 0,
            },
        )
        spec = read_dag_spec(_regular(recipe.plan_path("canonical_spec")))
        return validate_completed_workflow(recipe, spec)
