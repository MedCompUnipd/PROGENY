"""Scientific regression of R6 target-partitioned Temporal V2 projection."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from progeny.stage08_temporal_v2 import (
    P0S,
    P1N,
    P1S,
    _write_outputs,
    _write_outputs_parallel,
)

NAMES = (
    "benchmark_terms.tsv",
    "target_aspects.tsv",
    "term_audit.tsv",
    "negative_terms.tsv",
    "temporal_events.tsv",
)


def make_state(path: Path) -> dict[str, str]:
    mapping = {f"T{i:05d}": f"Q{i:05d}" for i in range(64)}
    mapping["\U0010ffff"] = "Q-LAST"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE terms (
            target_id TEXT NOT NULL, aspect TEXT NOT NULL,
            go_id TEXT NOT NULL, flags INTEGER NOT NULL,
            PRIMARY KEY(target_id,aspect,go_id)
        ) WITHOUT ROWID""")
        for target in mapping:
            db.executemany(
                "INSERT INTO terms VALUES(?,?,?,?)",
                (
                    (target, "F", f"GO:{i:07d}", flags)
                    for i, flags in enumerate((P1S, P0S, P1S | P1N), 1)
                ),
            )
    return mapping


def hashes(folder: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in NAMES
    }


@pytest.mark.parametrize("workers", (1, 2, 4, 8))
def test_partitioned_projection_exact(tmp_path: Path, workers: int) -> None:
    path = tmp_path / "state.sqlite3"
    mapping = make_state(path)
    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    original.mkdir()
    candidate.mkdir()
    (candidate / "state.sqlite3").symlink_to(path)
    with sqlite3.connect(path) as db:
        baseline = _write_outputs(db, original, mapping)
        parallel = _write_outputs_parallel(db, candidate, mapping, workers)
    assert baseline == parallel
    assert hashes(original) == hashes(candidate)
    assert not (candidate / ".temporal_partitions").exists()


@pytest.mark.parametrize("workers", (0, -1, 129))
def test_invalid_workers_fail_closed(workers: int, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="workers"):
        _write_outputs_parallel(None, tmp_path, {}, workers)
