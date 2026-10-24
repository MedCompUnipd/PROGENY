#!/usr/bin/env bash
# Serialized, incremental build for the one PROGENY native release directory.
# This command is used by Pixi build tasks; no scientific files are changed.
set -Eeuo pipefail
umask 077
[[ $# -eq 1 ]] || { echo 'Expected exactly one native target' >&2; exit 2; }
TARGET=$1
case "$TARGET" in
    progeny-release-fasta-v2|progeny-goa-normalize-v1|\
    progeny-go-positive-filter-v1|progeny-raw-ox-extract-v1|\
    progeny-primary-candidate-scan-v1|progeny-primary-candidate-scan-v2|\
    progeny-direct-accession-anchors-v1|progeny-onehop-lineage-scan-v1|\
    progeny-candidate-sequence-extract-v1|progeny-directional-glocal-full-dp-v1|\
    progeny-full-exact-cross-strain-v1|\
    progeny-directional-glocal-bounded-dp-v2|\
    progeny-directional-glocal-linear-dp-v1) ;;
    *) echo "Unsupported native target: $TARGET" >&2; exit 2 ;;
esac
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
[[ -f "$REPO/pixi.toml" && -f "$REPO/cpp/CMakeLists.txt" ]] || {
    echo 'Not a complete PROGENY source checkout' >&2
    exit 1
}
ENV_DIR="$REPO/.pixi/envs/default"
CXX="$ENV_DIR/bin/x86_64-conda-linux-gnu-g++"
CMAKE="$ENV_DIR/bin/cmake"
NINJA="$ENV_DIR/bin/ninja"
for tool in "$CXX" "$CMAKE" "$NINJA"; do
    [[ -x "$tool" ]] || { echo "Missing Pixi tool $tool" >&2; exit 1; }
done
[[ "$("$CXX" -dumpfullversion)" = 14.4.0 ]] || {
    echo 'Native compiler must be GCC 14.4.0' >&2; exit 1;
}
BASE="$REPO/.pixi/build"
BUILD="$BASE/progeny-native-release-gcc14.4"
[[ ! -L "$BASE" && ! -L "$BUILD" ]] || {
    echo 'Symlinked native build directory rejected' >&2; exit 1;
}
mkdir -p -- "$BASE"
command -v flock >/dev/null || { echo 'flock required' >&2; exit 1; }
exec 9>"$BASE/.progeny-native-release.lock"
flock -x 9
if [[ -e "$BUILD" && ! -d "$BUILD" ]]; then
    echo 'Existing native build path is not a directory' >&2
    exit 1
fi
CACHE="$BUILD/CMakeCache.txt"
if [[ -d "$BUILD" && ! -f "$CACHE" ]]; then
    echo 'Refusing to reuse incomplete build directory' >&2; exit 1
fi
if [[ ! -f "$CACHE" ]]; then
    "$CMAKE" -S "$REPO/cpp" -B "$BUILD" -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_CXX_COMPILER="$CXX" \
        -DCMAKE_MAKE_PROGRAM="$NINJA" \
        -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
        -DPROGENY_NATIVE_RELEASE=ON
fi
for expected in \
    "CMAKE_BUILD_TYPE:STRING=Release" \
    "PROGENY_NATIVE_RELEASE:BOOL=ON"; do
    grep -Fxq "$expected" "$CACHE" || {
        echo "Native CMake cache mismatch: $expected" >&2; exit 1;
    }
done
if ! grep -Fxq "CMAKE_CXX_COMPILER:FILEPATH=$CXX" "$CACHE" && \
    ! grep -Fxq "CMAKE_CXX_COMPILER:STRING=$CXX" "$CACHE"; then
    echo 'Native CMake compiler differs from locked GCC 14.4' >&2
    exit 1
fi
"$CMAKE" --build "$BUILD" --target "$TARGET" --parallel 4
[[ -f "$BUILD/$TARGET" && -x "$BUILD/$TARGET" && \
    ! -L "$BUILD/$TARGET" ]] || {
    echo "Build did not produce the expected physical binary: $TARGET" >&2
    exit 1
}
printf 'PROGENY_NATIVE_TARGET=PASS target=%s directory=%s\n' \
    "$TARGET" "$BUILD"
