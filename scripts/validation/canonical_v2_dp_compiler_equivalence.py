"""Run frozen native DP differential tests on externally built toolchains.

No C++ compilation, scientific changes, or production artifacts are involved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import time
import unittest
from pathlib import Path

SELECTED = (
    "test_exhaustive_short_ties",
    "test_seeded_iupac_gaps_and_asymmetry",
    "test_literal_bijection_and_thread_determinism",
    "test_tiny_quantum_resumes_inside_rows_and_both_directions",
    "test_completed_first_direction_is_reused",
    "test_corrupt_checkpoint_is_rejected",
    "test_changed_sequence_or_identity_is_rejected",
    "test_memory_limit_refuses_before_execution",
)
EXECUTABLES = {
    "bounded": "progeny-directional-glocal-bounded-dp-v2",
    "linear": "progeny-directional-glocal-linear-dp-v1",
    "full": "progeny-directional-glocal-full-dp-v1",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(binary: Path, flags: list[str]) -> dict[str, object]:
    start = time.perf_counter()
    completed = subprocess.run(
        [str(binary), *flags], capture_output=True, text=True, check=False
    )
    return {
        "exit": completed.returncode,
        "elapsed_seconds": round(time.perf_counter() - start, 5),
        "stderr_tail": completed.stderr[-500:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--build", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()

    tests = args.repo / "tests"
    if not tests.is_dir() or not args.output.is_dir():
        raise ValueError("Missing test directory or pre-created output directory")
    sys.path.insert(0, str(tests))
    from test_canonical_v2_linear_dp import (
        NativeLinearDPTests,
        _inputs,
    )

    binaries = {key: args.build / name for key, name in EXECUTABLES.items()}
    if any(not value.is_file() for value in binaries.values()):
        raise ValueError("One or more native executables are missing")

    def external_setup(cls: type) -> None:
        cls.root = args.output / "cases"
        cls.root.mkdir()
        cls.binaries = binaries
        cls.measurements = {}

    NativeLinearDPTests.setUpClass = classmethod(external_setup)
    NativeLinearDPTests.tearDownClass = classmethod(lambda cls: None)
    suite = unittest.TestSuite(NativeLinearDPTests(name) for name in SELECTED)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1

    comparisons = {}
    for path in sorted((args.output / "cases").rglob("*.tsv")):
        if any(
            path.name.endswith(suffix)
            for suffix in (
                "-bounded.tsv",
                "-linear.tsv",
                "-bounded.metrics.tsv",
                "-linear.metrics.tsv",
            )
        ):
            rel = path.relative_to(args.output / "cases").as_posix()
            comparisons[rel] = digest(path)

    # A moderate, deterministic standalone benchmark, never a speed claim.
    rng = random.Random(20261022)
    alphabet = "ACDEFGHIKLMNPQRSTVWYBJXZ"
    target = "".join(rng.choices(alphabet, k=1600))
    candidate = "".join(rng.choices(alphabet, k=1700))
    work = args.output / "benchmark"
    flags = _inputs(work, [(target, candidate)])
    performance = {}
    output_hashes = []
    for backend in ("bounded", "linear"):
        output = work / f"{backend}.tsv"
        summary = work / f"{backend}.metrics.tsv"
        run_flags = [
            *flags,
            "--output",
            str(output),
            "--summary",
            str(summary),
            "--threads",
            "4",
        ]
        measurement = measure(binaries[backend], run_flags)
        if measurement["exit"] != 0:
            raise RuntimeError(f"Benchmark failed: {backend}: {measurement}")
        output_hashes.append((digest(output), digest(summary)))
        performance[backend] = measurement
    if output_hashes[0] != output_hashes[1]:
        raise RuntimeError("Bounded/rolling mismatch on moderate IUPAC pair")

    report = {
        "schema": "progeny-dp-external-compiler-equivalence-v1",
        "profile": args.profile,
        "tests_passed": result.testsRun,
        "binary_sha256": {key: digest(val) for key, val in binaries.items()},
        "comparisons": comparisons,
        "benchmark": performance,
        "benchmark_sha256": output_hashes[0],
        "status": "PASS",
    }
    (args.output / "verification.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"DP_EXTERNAL_EQUIVALENCE={args.profile}:PASS")
    print(f"DP_EXTERNAL_TEST_COUNT={result.testsRun}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
