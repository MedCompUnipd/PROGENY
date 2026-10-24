"""Fail-closed execution-only resources for the fresh canonical V2 DAG.

This configuration does not participate in scientific identity or GO policy.
It must still be pinned in individual fresh execution intents at publication.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "progeny-fresh-runtime-resources-v1"
_DEFAULTS = {
    "m8_workers": 1,
    "temporal_workers": 1,
    "m8_mem_mb": 0,
    "m10c_mem_mb": 0,
    "temporal_mem_mb": 0,
}


@dataclass(frozen=True)
class RuntimeProfile:
    m8_workers: int = 1
    temporal_workers: int = 1
    m8_mem_mb: int = 0
    m10c_mem_mb: int = 0
    temporal_mem_mb: int = 0
    sha256: str = "DEFAULT_SERIAL"

    def requested_threads(self, stage: str, alignment_threads: int) -> int:
        if stage == "alignment":
            return alignment_threads
        if stage == "m8":
            return self.m8_workers
        if stage == "temporal":
            return self.temporal_workers
        return 1

    def reserved_memory(self, stage: str, alignment_mem_mb: int) -> int:
        if stage == "alignment":
            return alignment_mem_mb
        return {
            "m8": self.m8_mem_mb,
            "m10c": self.m10c_mem_mb,
            "temporal": self.temporal_mem_mb,
        }.get(stage, 0)


def read_runtime_profile(name: str | None) -> RuntimeProfile:
    """Validate an optional absolute, regular JSON resource contract."""
    if name is None:
        return RuntimeProfile()
    if type(name) is not str or not name:
        raise ValueError("Runtime profile path must be a nonempty string")
    path = Path(name)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Runtime profile path must be absolute and normalized")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Runtime profile must be a regular non-symlink file")
    content = path.read_bytes()
    data = json.loads(content)
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("Unknown PROGENY runtime profile schema")
    if set(data) != {"schema", *_DEFAULTS}:
        raise ValueError("Runtime profile keys must be complete and exact")
    for key in _DEFAULTS:
        number = data[key]
        upper = (
            2
            if key == "m8_workers"
            else 128
            if key == ("temporal_workers")
            else 1_048_576
        )
        minimum = 1 if key.endswith("workers") else 0
        if type(number) is not int or not minimum <= number <= upper:
            raise ValueError(f"Invalid runtime resource: {key}")
    return RuntimeProfile(
        **{key: data[key] for key in _DEFAULTS},
        sha256=hashlib.sha256(content).hexdigest(),
    )


def validate_execution_resources(stage: str, resources: object) -> dict:
    """Accept pinned workers and reservation only for actual multicore kernels."""
    if stage not in {"m8", "temporal"}:
        raise ValueError("Execution workers are not supported for this stage")
    if not isinstance(resources, dict) or set(resources) != {
        "workers",
        "mem_mb",
        "profile_sha256",
    }:
        raise ValueError("Invalid execution resource keys")
    workers = resources["workers"]
    memory = resources["mem_mb"]
    cap = 2 if stage == "m8" else 128
    if type(workers) is not int or not 1 <= workers <= cap:
        raise ValueError("Invalid effective worker count")
    if type(memory) is not int or not 0 <= memory <= 1_048_576:
        raise ValueError("Invalid memory reservation")
    digest = resources["profile_sha256"]
    if digest != "DEFAULT_SERIAL" and (
        type(digest) is not str
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("Invalid performance profile identity")
    return dict(resources)
