#!/usr/bin/env python3
"""Build the pinned CRoaring executable used by standalone IA preparation."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--cc", type=Path)
    parser.add_argument("--cxx", type=Path)
    parser.add_argument("--allow-development-toolchain", action="store_true")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    experiment = repository / "experiments/ia_roaring"
    locked_bin = repository / ".pixi/envs/default/bin"
    cc = (args.cc or locked_bin / "x86_64-conda-linux-gnu-gcc").resolve(strict=True)
    cxx = (args.cxx or locked_bin / "x86_64-conda-linux-gnu-g++").resolve(strict=True)
    versions = [
        subprocess.check_output([str(p), "-dumpfullversion"], text=True).strip()
        for p in (cc, cxx)
    ]
    if not args.allow_development_toolchain and versions != ["14.4.0", "14.4.0"]:
        raise ValueError("Locked C and C++ compilers must both be GCC 14.4.0")
    if not 1 <= args.jobs <= 16:
        raise ValueError("Build jobs must be between 1 and 16")
    cmake = shutil.which("cmake")
    ninja = shutil.which("ninja")
    if cmake is None or ninja is None:
        raise ValueError("Run this builder inside the locked Pixi environment")
    pixi_bin = (repository / ".pixi/envs/default/bin").resolve(strict=True)
    cmake_path = Path(cmake).resolve(strict=True)
    ninja_path = Path(ninja).resolve(strict=True)
    if not cmake_path.is_relative_to(pixi_bin) or not ninja_path.is_relative_to(
        pixi_bin
    ):
        raise ValueError("CMake and Ninja must come from the locked Pixi environment")
    build = args.build_dir.absolute()
    if build.exists() or build.is_symlink():
        raise ValueError("Build directory must be new")
    if build.parent.resolve(strict=True) != build.parent:
        raise ValueError("Build parent must be an existing non-symlink directory")
    if build.is_relative_to(repository):
        raise ValueError("Experimental build must be outside the source checkout")
    lock_path = experiment / "vendor/CRoaring.lock.json"
    lock = json.loads(lock_path.read_text())
    if lock["commit"] != "20495fec4d1622b93284033a160f67d21a5aa8bb":
        raise ValueError("Unsupported CRoaring dependency commit")
    vendor = experiment / "vendor/CRoaring"
    if any(p.is_symlink() for p in vendor.rglob("*")):
        raise ValueError("CRoaring vendor paths must not contain symlinks")
    actual = {str(p.relative_to(vendor)) for p in vendor.rglob("*") if p.is_file()}
    if actual != set(lock["files"]):
        raise ValueError("CRoaring vendor file inventory differs from its lock")
    for name, expected in lock["files"].items():
        path = vendor / name
        if path.is_symlink() or sha(path) != expected:
            raise ValueError(f"CRoaring dependency digest mismatch: {name}")
    subprocess.run(
        [
            cmake,
            "-S",
            str(experiment),
            "-B",
            str(build),
            "-G",
            "Ninja",
            "-DCMAKE_BUILD_TYPE=Release",
            f"-DCMAKE_C_COMPILER={cc}",
            f"-DCMAKE_CXX_COMPILER={cxx}",
            f"-DCMAKE_MAKE_PROGRAM={ninja}",
        ],
        check=True,
    )
    subprocess.run(
        [cmake, "--build", str(build), "--parallel", str(args.jobs)], check=True
    )
    binary = build / "progeny-ia-roaring-v1"
    provenance = {
        "schema": "progeny-ia-roaring-build-v1",
        "profile": "development" if args.allow_development_toolchain else "locked",
        "compiler_versions": versions,
        "c_compiler": str(cc),
        "cxx_compiler": str(cxx),
        "c_compiler_sha256": sha(cc),
        "cxx_compiler_sha256": sha(cxx),
        "cmake_sha256": sha(cmake_path),
        "ninja_sha256": sha(ninja_path),
        "croaring_lock_sha256": sha(lock_path),
        "builder_sha256": sha(Path(__file__)),
        "pixi_lock_sha256": sha(repository / "pixi.lock"),
        "source_sha256": {
            str(p.relative_to(repository)): sha(p)
            for p in [experiment / "CMakeLists.txt", experiment / "src/main.cpp"]
        },
        "binary_sha256": sha(binary),
    }
    (build / "build_provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    )
    print(f"IA_ROARING_BUILD=PASS BINARY={binary}")


if __name__ == "__main__":
    main()
