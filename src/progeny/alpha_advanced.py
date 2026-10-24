"""Validated opt-in configuration layer for the guided study preparator."""

from __future__ import annotations

from pathlib import Path

from progeny.canonical_v2.runtime_resources import read_runtime_profile
from progeny.stage08_evidence_registry import read_json_object
from progeny.stage08_temporal_v2 import load_classes

SCHEMA = "progeny-guided-advanced-v1"
NUMERIC = (
    "threads",
    "max_pair_cells",
    "max_total_cells",
    "max_chunk_cells",
    "max_dp_memory_bytes",
    "checkpoint_rows",
)


def validate_advanced(
    path: Path, *, registry: Path, base_cores: int
) -> tuple[dict, Path | None, Path | None]:
    """Reject unknown keys, invalid budgets, and ineffective worker settings."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("Advanced config must be a regular, non-symlinked file")
    data = read_json_object(path)
    if data.get("schema") != SCHEMA or set(data) - {
        "schema",
        *NUMERIC,
        "temporal_policy",
        "performance_profile",
    }:
        raise ValueError("Invalid PROGENY advanced configuration schema")
    overrides = {}
    for key in NUMERIC:
        if key in data:
            value = data[key]
            if type(value) is not int or value < 1:
                raise ValueError(f"Advanced {key} must be a positive integer")
            overrides[key] = value
    if overrides.get("max_dp_memory_bytes", 1) > 1024**4:
        raise ValueError("Advanced DP memory exceeds supported maximum")
    cores = overrides.get("threads", base_cores)
    profile = None
    if data.get("performance_profile") is not None:
        value = data["performance_profile"]
        if not isinstance(value, str):
            raise ValueError("Performance profile must be an absolute file path")
        profile = Path(value)
        if not profile.is_absolute() or ".." in profile.parts:
            raise ValueError("Performance profile must be an absolute file path")
        runtime = read_runtime_profile(str(profile))
        if max(runtime.m8_workers, runtime.temporal_workers) > cores:
            raise ValueError("Requested workers exceed guided Snakemake cores")
    policy = None
    if data.get("temporal_policy") is not None:
        value = data["temporal_policy"]
        if not isinstance(value, str):
            raise ValueError("Evidence policy must be an absolute file path")
        policy = Path(value)
        if (
            not policy.is_absolute()
            or ".." in policy.parts
            or policy.is_symlink()
            or not policy.is_file()
        ):
            raise ValueError("Evidence policy must be a regular absolute file")
        load_classes(registry, policy)
    return overrides, policy, profile
