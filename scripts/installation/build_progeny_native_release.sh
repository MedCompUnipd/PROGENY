#!/usr/bin/env bash
# Fresh native build; does not read any historical build or CAFA5 state.
set -euo pipefail
umask 077
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
export TMPDIR="${TMPDIR:-$REPO/.pixi/tmp}"
export TMP="$TMPDIR" TEMP="$TMPDIR"
mkdir -p -- "$TMPDIR"
[[ "$REPO" != *$'\n'* ]] || { echo 'Unexpected path' >&2; exit 1; }
command -v pixi >/dev/null || { echo 'Pixi is required' >&2; exit 1; }
cd "$REPO"
pixi install --locked
ENV_DIR="$REPO/.pixi/envs/default"
export PATH="$ENV_DIR/bin:$PATH"
export CONDA_PREFIX="$ENV_DIR"
CXX="$ENV_DIR/bin/x86_64-conda-linux-gnu-g++"
CMAKE="$ENV_DIR/bin/cmake"
NINJA="$ENV_DIR/bin/ninja"
for tool in "$CXX" "$CMAKE" "$NINJA"; do
    [[ -x "$tool" ]] || {
        echo "Missing executable $tool" >&2; exit 1;
    }
done
version=$("$CXX" -dumpfullversion)
[[ "$version" == 14.4.0 ]] || {
    echo "Unsupported compiler: $version (expected GCC 14.4.0)" >&2
    exit 1
}
[[ -f "$REPO/cmake/ProgenyNativeRelease.cmake" ]] || exit 1
[[ -f "$REPO/cpp/CMakeLists.txt" ]] || exit 1
BUILD="$REPO/.pixi/build/progeny-native-release-gcc14.4"
if [[ -e "$BUILD" || -L "$BUILD" ]]; then
    echo "Build destination already exists; refusing reuse: $BUILD" >&2
    exit 1
fi
mkdir -p "$BUILD"
"$CMAKE" -S "$REPO/cpp" -B "$BUILD" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_COMPILER="$CXX" \
    -DCMAKE_MAKE_PROGRAM="$NINJA" \
    -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
    -DPROGENY_NATIVE_RELEASE=ON
"$CMAKE" --build "$BUILD" --parallel 4
python3 -I -S -B - "$BUILD/compile_commands.json" <<'PY_CHECK'
import json
import shlex
import sys
from pathlib import Path

commands = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
profiles = {
    "progeny_directional_glocal_bounded_dp_v2.cpp": "-O3",
    "progeny_directional_glocal_linear_dp_v1.cpp": "-O2",
}
for source, expected in profiles.items():
    matching = [
        item for item in commands if Path(item["file"]).name == source
    ]
    if len(matching) != 1:
        raise SystemExit(f"Expected one compile command for {source}")
    flags = shlex.split(matching[0]["command"])
    optimizations = [
        flag for flag in flags if flag.startswith(("-O0", "-O1", "-O2", "-O3"))
    ]
    if not optimizations or optimizations[-1] != expected:
        raise SystemExit(f"Wrong optimization for {source}: {optimizations}")
    if "-fopenmp" not in flags or "-std=c++20" not in flags:
        raise SystemExit(f"Missing OpenMP or C++20 for {source}")
    if any(
        flag.startswith(("-march=native", "-ffast-math", "-Ofast", "-flto"))
        for flag in flags
    ):
        raise SystemExit(f"Unapproved compiler option for {source}")
    print(f"TARGET_FLAGS=PASS {source} {optimizations[-1]}")
PY_CHECK
"$CXX" --version | head -1
printf 'NATIVE_SOURCE_AND_ENV_HASHES:\n'
sha256sum "$REPO/cpp/CMakeLists.txt" \
    "$REPO/cmake/ProgenyNativeRelease.cmake" \
    "$REPO/pixi.toml" "$REPO/pixi.lock"
for binary in progeny-directional-glocal-bounded-dp-v2 \
    progeny-directional-glocal-linear-dp-v1; do
    echo "NATIVE_DYNAMIC_LINKS=$binary"
    if command -v readelf >/dev/null; then
        readelf -d "$BUILD/$binary" | grep NEEDED || true
    fi
done
"$CMAKE" -LA -N "$BUILD" | grep -E \
    '^(CMAKE_CXX_COMPILER|CMAKE_BUILD_TYPE|PROGENY_NATIVE_RELEASE):'
for name in \
    progeny-release-fasta-v2 progeny-goa-normalize-v1 \
    progeny-go-positive-filter-v1 progeny-raw-ox-extract-v1 \
    progeny-primary-candidate-scan-v1 progeny-primary-candidate-scan-v2 \
    progeny-direct-accession-anchors-v1 progeny-onehop-lineage-scan-v1 \
    progeny-candidate-sequence-extract-v1 \
    progeny-directional-glocal-full-dp-v1 \
    progeny-full-exact-cross-strain-v1 \
    progeny-directional-glocal-bounded-dp-v2 \
    progeny-directional-glocal-linear-dp-v1; do
    [[ -x "$BUILD/$name" ]] || { echo "Missing $name" >&2; exit 1; }
    sha256sum "$BUILD/$name"
done
printf 'NATIVE_BUILD_COMPLETE=PASS\nBUILD_DIR=%s\n' "$BUILD"
printf 'SCIENTIFIC_EQUIVALENCE=NOT_TESTED_BY_THIS_SCRIPT\n'
