#!/usr/bin/env python3
"""Prepare/reuse shared START IA and run-specific knowledge cohorts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from progeny.alpha_identity import _sha
from progeny.evaluation_artifacts import (
    ia_artifact_dir,
    shared_artifacts_root,
    start_identity,
    validate_ia_artifact,
)
from progeny.knowledge_cohorts import load_published_cohorts
from progeny.prediction_inputs import load_benchmark_inputs


def _build_identity(repository: Path) -> tuple[str, dict]:
    experiment = repository / "experiments/ia_roaring"
    lock = experiment / "vendor/CRoaring.lock.json"
    source_paths = {
        "experiments/ia_roaring/CMakeLists.txt": experiment / "CMakeLists.txt",
        "experiments/ia_roaring/src/main.cpp": experiment / "src/main.cpp",
    }
    sources = {name: _sha(path) for name, path in source_paths.items()}
    lock_sha = _sha(lock)
    builder_sha = _sha(
        repository / "scripts/evaluation/build_information_accretion_roaring.py"
    )
    pixi_lock_sha = _sha(repository / "pixi.lock")
    compiler_dir = repository / ".pixi/envs/default/bin"
    tools = {
        "c": compiler_dir / "x86_64-conda-linux-gnu-gcc",
        "cxx": compiler_dir / "x86_64-conda-linux-gnu-g++",
        "cmake": compiler_dir / "cmake",
        "ninja": compiler_dir / "ninja",
    }
    tool_hashes = {name: _sha(path) for name, path in tools.items()}
    payload = {
        "schema": "progeny-ia-roaring-locked-build-v1",
        "compiler_versions": ["14.4.0", "14.4.0"],
        "tool_sha256": tool_hashes,
        "croaring_lock_sha256": lock_sha,
        "builder_sha256": builder_sha,
        "pixi_lock_sha256": pixi_lock_sha,
        "source_sha256": sources,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return digest, payload


def _valid_build(build_dir: Path, identity: dict) -> Path | None:
    binary = build_dir / "progeny-ia-roaring-v1"
    provenance_path = build_dir / "build_provenance.json"
    if not build_dir.exists():
        return None
    if (
        build_dir.is_symlink()
        or build_dir.absolute().resolve(strict=False) != build_dir.absolute()
        or not build_dir.is_dir()
    ):
        raise ValueError("Roaring build cache is not a regular directory")
    if binary.is_symlink() or provenance_path.is_symlink():
        raise ValueError("Roaring build cache contains a symlink")
    if not binary.is_file() or not provenance_path.is_file():
        raise ValueError("Existing Roaring build cache is incomplete")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if (
        provenance.get("schema") != "progeny-ia-roaring-build-v1"
        or provenance.get("profile") != "locked"
        or provenance.get("compiler_versions") != ["14.4.0", "14.4.0"]
        or provenance.get("croaring_lock_sha256") != identity["croaring_lock_sha256"]
        or provenance.get("builder_sha256") != identity["builder_sha256"]
        or provenance.get("pixi_lock_sha256") != identity["pixi_lock_sha256"]
        or provenance.get("source_sha256") != identity["source_sha256"]
        or provenance.get("c_compiler_sha256") != identity["tool_sha256"]["c"]
        or provenance.get("cxx_compiler_sha256") != identity["tool_sha256"]["cxx"]
        or provenance.get("cmake_sha256") != identity["tool_sha256"]["cmake"]
        or provenance.get("ninja_sha256") != identity["tool_sha256"]["ninja"]
        or provenance.get("binary_sha256") != _sha(binary)
    ):
        raise ValueError("Existing Roaring build cache identity is invalid")
    return binary


def _ensure_native(repository: Path, store: Path, jobs: int) -> Path:
    build_fingerprint, identity = _build_identity(repository)
    build_dir = store / "native/ia-roaring" / build_fingerprint
    binary = _valid_build(build_dir, identity)
    if binary is not None:
        print(f"IA_ROARING_BUILD=REUSED BINARY={binary}", flush=True)
        return binary
    build_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(repository / "scripts/evaluation/build_information_accretion_roaring.py"),
        "--build-dir",
        str(build_dir),
        "--jobs",
        str(jobs),
    ]
    subprocess.run(command, cwd=repository, check=True)
    binary = _valid_build(build_dir, identity)
    if binary is None:
        raise ValueError("Roaring builder returned without a valid binary")
    return binary


def _prepare_cohorts(
    *,
    repository: Path,
    dataset: Path,
    run: Path,
    ontology: Path,
    benchmark_sha: str,
    store: Path,
    benchmark,
) -> Path:
    destination = store / "RUNS" / run.name / benchmark_sha / "knowledge_cohorts"
    if destination.absolute().resolve(strict=False) != destination.absolute():
        raise ValueError("Knowledge cohort path must not contain symlinks")
    if destination.exists():
        load_published_cohorts(
            destination,
            eligible=benchmark.eligible,
            species=benchmark.species,
            provenance=benchmark.provenance,
        )
        print(f"KNOWLEDGE_COHORTS=REUSED PATH={destination}", flush=True)
        return destination
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(repository / "scripts/evaluation/publish_start_knowledge_cohorts.py"),
        "--dataset",
        str(dataset),
        "--run",
        str(run),
        "--ontology",
        str(ontology),
        "--benchmark-sha256",
        benchmark_sha,
        "--output-dir",
        str(destination),
    ]
    subprocess.run(command, cwd=repository, check=True)
    load_published_cohorts(
        destination,
        eligible=benchmark.eligible,
        species=benchmark.species,
        provenance=benchmark.provenance,
    )
    print(f"KNOWLEDGE_COHORTS=PUBLISHED PATH={destination}", flush=True)
    return destination


def prepare(
    *,
    dataset: Path,
    run: Path,
    jobs: int = 2,
    threads: int = 8,
    max_address_space_gib: int = 128,
) -> dict:
    repository = Path(__file__).resolve().parents[2]
    resolved_dataset = dataset.resolve(strict=True)
    resolved_run = run.resolve(strict=True)
    if dataset.absolute() != resolved_dataset or run.absolute() != resolved_run:
        raise ValueError("Dataset and run paths must not contain symlinks")
    dataset = resolved_dataset
    run = resolved_run
    store = shared_artifacts_root(dataset)
    try:
        store.relative_to(repository)
    except ValueError:
        pass
    else:
        raise ValueError("Shared evaluation artifacts must be outside the checkout")
    try:
        repository.relative_to(store)
    except ValueError:
        pass
    else:
        raise ValueError("Shared evaluation artifacts overlap the source checkout")
    identity = start_identity(dataset)
    protected_roots = (
        dataset,
        run,
        identity["gaf_path"].parent,
        identity["ontology_path"].parent,
    )
    if any(
        store.is_relative_to(root) or root.is_relative_to(store)
        for root in protected_roots
    ):
        raise ValueError("Shared-artifact store overlaps a protected input root")
    benchmark_manifest = run / "results/benchmark/manifest.json"
    if benchmark_manifest.is_symlink() or not benchmark_manifest.is_file():
        raise ValueError("Certified benchmark publication is not available")
    benchmark_sha = _sha(benchmark_manifest)
    benchmark = load_benchmark_inputs(
        dataset=dataset,
        run=run,
        ontology_path=identity["ontology_path"],
        benchmark_sha256=benchmark_sha,
    )
    cohorts = _prepare_cohorts(
        repository=repository,
        dataset=dataset,
        run=run,
        ontology=identity["ontology_path"],
        benchmark_sha=benchmark_sha,
        store=store,
        benchmark=benchmark,
    )
    cohort_manifest = json.loads(
        (cohorts / "manifest.json").read_text(encoding="utf-8")
    )
    if (
        cohort_manifest.get("start_release") != identity["release_id"]
        or cohort_manifest.get("start_gaf_sha256") != identity["gaf_sha256"]
    ):
        raise ValueError("Knowledge cohorts do not match this dataset's START")
    ia_dir = ia_artifact_dir(dataset, identity)
    if ia_dir.absolute().resolve(strict=False) != ia_dir.absolute():
        raise ValueError("IA publication path must not contain symlinks")
    if ia_dir.exists():
        table, manifest = validate_ia_artifact(ia_dir, identity)
        print(f"INFORMATION_ACCRETION=REUSED TABLE={table} MANIFEST={manifest}")
    else:
        binary = _ensure_native(repository, store, jobs)
        scratch_root = store / "scratch/ia-roaring"
        if scratch_root.absolute().resolve(strict=False) != scratch_root.absolute():
            raise ValueError("IA scratch path must not contain symlinks")
        scratch_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        ia_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        command = [
            sys.executable,
            str(
                repository
                / "scripts/evaluation/compute_information_accretion_roaring.py"
            ),
            "--gaf",
            str(identity["gaf_path"]),
            "--gaf-sha256",
            identity["gaf_sha256"],
            "--source-role",
            "START",
            "--release-id",
            identity["release_id"],
            "--ontology",
            str(identity["ontology_path"]),
            "--ontology-sha256",
            identity["ontology_sha256"],
            "--native-binary",
            str(binary),
            "--scratch-root",
            str(scratch_root),
            "--output-dir",
            str(ia_dir),
            "--threads",
            str(threads),
            "--max-address-space-gib",
            str(max_address_space_gib),
        ]
        subprocess.run(command, cwd=repository, check=True)
        table, manifest = validate_ia_artifact(ia_dir, identity)
        print(f"INFORMATION_ACCRETION=COMPUTED TABLE={table} MANIFEST={manifest}")
    return {
        "status": "READY",
        "benchmark_sha256": benchmark_sha,
        "ia_table": str(table),
        "ia_manifest": str(manifest),
        "ia_fingerprint": ia_dir.name,
        "knowledge_cohorts": str(cohorts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--max-address-space-gib", type=int, default=128)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 16:
        parser.error("--jobs must be between 1 and 16")
    if not 1 <= args.threads <= 64:
        parser.error("--threads must be between 1 and 64")
    if args.max_address_space_gib < 1:
        parser.error("--max-address-space-gib must be positive")
    result = prepare(
        dataset=args.dataset,
        run=args.run,
        jobs=args.jobs,
        threads=args.threads,
        max_address_space_gib=args.max_address_space_gib,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
