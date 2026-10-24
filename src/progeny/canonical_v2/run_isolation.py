"""Run-owned transient and checkpoint directories for fresh PROGENY runs.

Only the transient subtree is eligible for cleanup. Checkpoints remain durable.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

POLICY = "progeny-run-local-scratch-v1"
OWNER = ".progeny-run-scratch.json"


def scratch_paths(run: Path) -> tuple[Path, Path, Path]:
    root = run / "tmp"
    return root, root / "transient", root / "checkpoints"


def _physical(path: Path, *, device: int) -> None:
    if (
        path.is_symlink()
        or not path.is_dir()
        or path.resolve(strict=True) != path
        or path.stat().st_dev != device
    ):
        raise ValueError(f"Unsafe run-owned scratch directory: {path}")


def _owner_payload(run: Path, identity: str) -> dict:
    return {
        "schema": POLICY,
        "run_root": str(run),
        "identity_sha256": identity,
        "owner_digest": hashlib.sha256(
            (str(run) + "\0" + identity).encode("utf-8")
        ).hexdigest(),
    }


def create_scratch(run: Path, identity: str) -> None:
    """Called only inside preparation of a newly created virgin run."""
    root, transient, checkpoints = scratch_paths(run)
    root.mkdir(mode=0o700)
    transient.mkdir(mode=0o700)
    checkpoints.mkdir(mode=0o700)
    marker = root / OWNER
    marker.write_text(
        json.dumps(_owner_payload(run, identity), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    marker.chmod(0o600)


def validate_scratch(run: Path, identity: str) -> tuple[Path, Path]:
    """Refuse symlinked, foreign-filesystem, relocated or unowned scratch."""
    if not run.is_absolute() or run.is_symlink():
        raise ValueError("Unsafe run root for scratch")
    device = run.stat().st_dev
    root, transient, checkpoints = scratch_paths(run)
    for path in (root, transient, checkpoints):
        _physical(path, device=device)
    marker = root / OWNER
    if not marker.is_file() or marker.is_symlink():
        raise ValueError("Missing run-owned scratch marker")
    if json.loads(marker.read_text(encoding="utf-8")) != _owner_payload(run, identity):
        raise ValueError("Scratch ownership does not match this run")
    return root, transient


def clean_transient(run: Path, identity: str) -> int:
    """Clean only run-owned transient contents after independent deep verification.

    The caller MUST hold the run control lock and deep-verify publications.
    Never remove root/tmp, checkpoint data, or the ownership marker.
    """
    _, transient = validate_scratch(run, identity)
    if not shutil.rmtree.avoids_symlink_attacks:
        raise RuntimeError("Platform lacks symlink-safe recursive removal")
    entries = list(transient.iterdir())
    for entry in entries:
        if entry.is_symlink():
            raise ValueError(f"Symlink in transient scratch: {entry}")
        for parent, directories, filenames in os.walk(entry, followlinks=False):
            for name in (*directories, *filenames):
                child = Path(parent) / name
                if child.is_symlink():
                    raise ValueError(f"Symlink inside transient scratch: {child}")
                if child.stat().st_dev != run.stat().st_dev:
                    raise ValueError(f"Cross-device transient scratch: {child}")
    for entry in entries:
        if entry.is_dir():
            shutil.rmtree(entry)
        elif entry.is_file():
            entry.unlink()
        else:
            raise ValueError(f"Unsupported scratch entry: {entry}")
    return len(entries)
