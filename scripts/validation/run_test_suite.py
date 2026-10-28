#!/usr/bin/env python3
"""Build the optional IA engine and run the complete suite with it enabled."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    repository = Path(__file__).resolve().parents[2]
    builder = repository / "scripts/evaluation/build_information_accretion_roaring.py"
    native_targets = (
        "progeny-release-fasta-v2",
        "progeny-goa-normalize-v1",
        "progeny-go-positive-filter-v1",
        "progeny-raw-ox-extract-v1",
        "progeny-primary-candidate-scan-v1",
        "progeny-primary-candidate-scan-v2",
        "progeny-direct-accession-anchors-v1",
        "progeny-onehop-lineage-scan-v1",
        "progeny-candidate-sequence-extract-v1",
        "progeny-directional-glocal-full-dp-v1",
        "progeny-full-exact-cross-strain-v1",
        "progeny-directional-glocal-bounded-dp-v2",
        "progeny-directional-glocal-linear-dp-v1",
    )
    ensure_native = repository / "scripts/installation/ensure_progeny_native_release.sh"
    for target in native_targets:
        subprocess.run(["bash", str(ensure_native), target], cwd=repository, check=True)
    with tempfile.TemporaryDirectory(prefix="progeny-ia-test-build-") as temporary:
        build_dir = Path(temporary) / "roaring-build"
        subprocess.run(
            [
                sys.executable,
                str(builder),
                "--build-dir",
                str(build_dir),
                "--jobs",
                "2",
            ],
            cwd=repository,
            check=True,
        )
        environment = os.environ.copy()
        environment["PROGENY_SOURCE_REPO"] = str(repository)
        environment["PROGENY_DP_BINARY"] = str(
            repository / ".pixi/build/progeny-native-release-gcc14.4/"
            "progeny-directional-glocal-full-dp-v1"
        )
        environment["PROGENY_IA_ROARING_BINARY"] = str(
            build_dir / "progeny-ia-roaring-v1"
        )
        completed = subprocess.run(
            [sys.executable, "-m", "pytest"],
            cwd=repository,
            env=environment,
            check=False,
        )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
