#!/usr/bin/env bash
# Portable, isolated native-toolchain matrix for frozen Canonical V2 DP.
set -Eeuo pipefail
umask 077

[[ $# -eq 3 ]] || { echo 'Usage: toolchain_matrix.sh REPO BUILD_ROOT REPORT_ROOT' >&2; exit 2; }
REPO=$1
BUILD_ROOT=$2
OUT=$3
fail() { printf 'DP_MATRIX_STOP=%s\n' "$*" >&2; exit 1; }

[[ "$REPO" = /* && -d "$REPO" && ! -L "$REPO" ]] || fail 'Physical repo required'
REPO=$(realpath -e -- "$REPO")
[[ "$BUILD_ROOT" = "$REPO"/.pixi/build/* ]] || fail 'Unexpected build location'
[[ ! -e "$BUILD_ROOT" && ! -L "$BUILD_ROOT" ]] || fail 'Build root already exists'
[[ "$OUT" = /* && -d "$OUT" && ! -L "$OUT" ]] || fail 'Existing output directory needed'
[[ "$(realpath -e -- "$OUT")" = "$OUT" ]] || fail 'Output parent must be physical'
[[ "$OUT" != "$REPO"/* ]] || fail 'Report must live outside repository'
[[ -d "$REPO/.pixi/build" && ! -L "$REPO/.pixi/build" ]] || fail 'Build parent missing'
[[ "$(realpath -e -- "$REPO/.pixi/build")" = "$REPO/.pixi/build" ]] || fail 'Unsafe build parent'
[[ -f "$REPO/cpp/CMakeLists.txt" ]] || fail 'Missing CMake contract'

# Scientific source identity: no edits to the 11 canonical native sources.
NAMES=(
  progeny-release-fasta-v2 progeny-goa-normalize-v1
  progeny-go-positive-filter-v1 progeny-raw-ox-extract-v1
  progeny-primary-candidate-scan-v1 progeny-primary-candidate-scan-v2
  progeny-direct-accession-anchors-v1 progeny-onehop-lineage-scan-v1
  progeny-full-exact-cross-strain-v1
  progeny-directional-glocal-bounded-dp-v2
  progeny-directional-glocal-linear-dp-v1
)
SOURCES=(
  ffa7384caf0dd72f4673b377af8472b9f0f6ec090d102091a8a9e6fb13b049eb
  1780e23655ee54a784f39f27bf7990918c2c100b7cbc010233fba608be323a64
  2482410588b3ca30006b6e85b102dd8eaa9c329b97647679b3dee138ba9dd491
  47f42c143115bdb7f9c1140c6a58bde8a6bfdb8513c38db0ba0ef8b09887cb07
  1c4961667300501341106c65c1e505c0355649a49d94fa68db0f8e29362cbc47
  312a79dcf789d318de11f75ba5147c5a1d1b25512477c14910bb028712e0d3c3
  9457040e020431caff8b9b943cf73c32729d89a98e435cb514fbeb056754f34f
  20479cbd18cf5a5011db746f72e3f222255c09e8efdbe6d2f34e360b35041446
  28ac2fab8bf95813f1983c27215eaadf67ad38ebb349a153409aaa32337aac5b
  b9389eece639e5f4828731ef675ee3939a2871e224a263d8d00c5ba777d3b160
  7c56663561eeb3344da8e0d926ee31c1f506d18b96ffe414c2dd012f47e90829
)
[[ "$(sha256sum "$REPO/cpp/CMakeLists.txt" | cut -d ' ' -f 1)" = \
  '4e2fa1451ff0fbed2f264ca9ba172b4f9519ed1ed649c7768edae16511d72d10' ]] || fail 'CMake contract differs'
for i in "${!NAMES[@]}"; do
  source_name=${NAMES[$i]//-/_}
  file="$REPO/cpp/src/${source_name}.cpp"
  [[ -f "$file" && ! -L "$file" ]] || fail "Missing source: $source_name"
  [[ "$(sha256sum "$file" | cut -d ' ' -f 1)" = "${SOURCES[$i]}" ]] || \
    fail "Changed scientific source: $source_name"
done
[[ -f "$REPO/cpp/src/progeny_directional_glocal_full_dp_v1.cpp" ]] || \
  fail 'Full DP reference source missing'
[[ -x "$REPO/.pixi/envs/default/bin/cmake" ]] || fail 'Pixi CMake missing'
[[ -x "$REPO/.pixi/envs/default/bin/ninja" ]] || fail 'Pixi Ninja missing'

PREFIX="$REPO/.pixi/envs/default"
CMAKE="$PREFIX/bin/cmake"
NINJA="$PREFIX/bin/ninja"
PIXI_CXX="$PREFIX/bin/x86_64-conda-linux-gnu-g++"
[[ -x "$PIXI_CXX" ]] || fail 'Pixi g++ missing'

[[ "$("$PIXI_CXX" -dumpfullversion)" = 14.* ]] || \
  fail 'Expected Pixi GCC 14 toolchain; inspect actual lock if changed'
HAS_REFERENCE=0
if [[ -x /usr/bin/g++ && "$(/usr/bin/g++ -dumpfullversion)" = 12.* ]]; then
  HAS_REFERENCE=1
fi
printf 'SYSTEM_GCC12_REFERENCE=%s\n' "$HAS_REFERENCE"
export TMPDIR="$OUT"
export TMP="$OUT" TEMP="$OUT"
export OMP_DYNAMIC=FALSE

mkdir -- "$BUILD_ROOT"
mapfile -t ALL_TARGETS < <(printf '%s\n' "${NAMES[@]}")
DP_TARGETS=(
  progeny-directional-glocal-bounded-dp-v2
  progeny-directional-glocal-linear-dp-v1
  progeny-directional-glocal-full-dp-v1
)

build_profile() {
  local name=$1 compiler=$2 flags=$3
  local dir="$BUILD_ROOT/$name"
  local check found
  local -a targets=("${DP_TARGETS[@]}")
  if [[ "$name" = gcc14-o3 ]]; then
    targets=("${ALL_TARGETS[@]}" progeny-directional-glocal-full-dp-v1)
  fi
  printf '\n===== CONFIGURE %s =====\n' "$name"
  "$compiler" --version | head -n 1
  "$CMAKE" -S "$REPO/cpp" -B "$dir" -G Ninja \
    "-DCMAKE_MAKE_PROGRAM=$NINJA" \
    "-DCMAKE_CXX_COMPILER=$compiler" \
    '-DCMAKE_BUILD_TYPE=Release' \
    "-DCMAKE_CXX_FLAGS_RELEASE=$flags" \
    '-DCMAKE_INTERPROCEDURAL_OPTIMIZATION=OFF' \
    '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON' \
    "-DCMAKE_PREFIX_PATH=$PREFIX" \
    "-DZLIB_ROOT=$PREFIX"
  # CMake may cache an explicitly selected compiler as STRING or FILEPATH.
  # Never call realpath with an empty cache value or accept a different binary.
  check=$(sed -n -E \
    's/^CMAKE_CXX_COMPILER:(FILEPATH|STRING)=//p' "$dir/CMakeCache.txt")
  [[ -n "$check" && "$check" = /* && "$check" != *$'\n'* ]] || \
    fail "CMake compiler path missing or ambiguous in $name"
  [[ -x "$check" ]] || fail "CMake compiler not executable in $name"
  local actual_compiler expected_compiler
  actual_compiler=$(realpath -e -- "$check") || \
    fail "CMake compiler cannot be resolved in $name"
  expected_compiler=$(realpath -e -- "$compiler") || \
    fail "Requested compiler cannot be resolved in $name"
  [[ "$actual_compiler" = "$expected_compiler" ]] || \
    fail "CMake compiler mismatch in $name: $check != $compiler"
  printf 'CMAKE_COMPILER_IDENTITY=%s:PASS resolved=%s\n' \
    "$name" "$actual_compiler"
  grep -Fq 'OpenMP_CXX_FOUND:INTERNAL=TRUE' "$dir/CMakeCache.txt" || \
    grep -Fq 'OpenMP_CXX_FLAGS:STRING=-fopenmp' "$dir/CMakeCache.txt" || \
    fail "OpenMP detection missing in $name"
  printf 'CMAKE_CXX_COMPILER=%s\nFLAGS=%s\n' "$check" "$flags"
  printf 'OpenMP configuration:\n'
  grep -E '^OpenMP_CXX_(FLAGS|LIB_NAMES|LIBRARY)' "$dir/CMakeCache.txt" || true
  "$CMAKE" --build "$dir" --parallel 4 --target "${targets[@]}"
  for target in "${targets[@]}"; do
    [[ -f "$dir/$target" && -x "$dir/$target" ]] || fail "Missing executable $target"
    printf 'BUILT=%s/%s SHA256=%s\n' "$name" "$target" \
      "$(sha256sum "$dir/$target" | cut -d ' ' -f 1)"
  done
  grep -Fq 'progeny_directional_glocal_linear_dp_v1.cpp' \
    "$dir/compile_commands.json" || fail 'Rolling compile command missing'
  grep -Fq -- '-fopenmp' "$dir/compile_commands.json" || \
    fail 'OpenMP not present in compilation commands'
  for target in "${DP_TARGETS[@]}"; do
    printf 'RUNTIME_DYNAMIC=%s/%s\n' "$name" "$target"
    if [[ "$name" = gcc14-o3 || "$name" = gcc14-o2 ]]; then
      env LD_LIBRARY_PATH="$PREFIX/lib" ldd "$dir/$target"
      found=$(env LD_LIBRARY_PATH="$PREFIX/lib" ldd "$dir/$target" | \
        grep 'libgomp.so.1 =>' || true)
      [[ "$found" = *"$PREFIX/lib/libgomp.so.1"* ]] || \
        fail 'Conda GCC14 libgomp not selected'
    else
      env -u LD_LIBRARY_PATH ldd "$dir/$target"
      found=$(env -u LD_LIBRARY_PATH ldd "$dir/$target" | \
        grep 'libgomp.so.1 =>' || true)
      [[ -n "$found" && "$found" != *'not found'* ]] || \
        fail 'GCC12 libgomp missing'
    fi
  done
}

if [[ $HAS_REFERENCE = 1 ]]; then
  build_profile gcc12-o2 /usr/bin/g++ '-O2 -DNDEBUG'
fi
build_profile gcc14-o2 "$PIXI_CXX" '-O2 -DNDEBUG'
build_profile gcc14-o3 "$PIXI_CXX" '-O3 -DNDEBUG'

PYTHON="$PREFIX/bin/python"
[[ -x "$PYTHON" ]] || fail 'Pixi Python absent'
VERIFY="$REPO/scripts/validation/canonical_v2_dp_compiler_equivalence.py"
[[ -f "$VERIFY" ]] || fail 'DP verification script missing'
PROFILES=(gcc14-o2 gcc14-o3)
if [[ $HAS_REFERENCE = 1 ]]; then
  PROFILES=(gcc12-o2 gcc14-o2 gcc14-o3)
fi
for name in "${PROFILES[@]}"; do
  printf '\n===== SCIENTIFIC DIFFERENTIAL %s =====\n' "$name"
  test_out="$OUT/$name"
  mkdir -- "$test_out"
  if [[ "$name" = gcc14-o3 || "$name" = gcc14-o2 ]]; then
    export LD_LIBRARY_PATH="$PREFIX/lib"
  else
    unset LD_LIBRARY_PATH || true
  fi
  "$PYTHON" "$VERIFY" --repo "$REPO" \
    --build "$BUILD_ROOT/$name" --output "$test_out" --profile "$name"
done

printf '\n===== CROSS-PROFILE RESULTS =====\n'
"$PYTHON" - "$OUT" "$HAS_REFERENCE" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
profiles = ["gcc14-o2", "gcc14-o3"]
if sys.argv[2] == "1":
    profiles.insert(0, "gcc12-o2")
results = {
    profile: json.loads((root / profile / "verification.json").read_text())
    for profile in profiles
}
for field in ("comparisons", "benchmark_sha256"):
    reference = results[profiles[0]][field]
    for profile in profiles[1:]:
        if reference != results[profile][field]:
            raise SystemExit(f"DP_CROSS_PROFILE_MISMATCH={profile}:{field}")
print(f"CROSS_PROFILE_CASE_HASHES={len(results[profiles[0]]['comparisons'])}")
print("DP_CROSS_PROFILE_EQUIVALENCE=PASS")
print("MEASURED_PROFILES=" + ",".join(profiles))
PY
printf 'DP_BUILD_AND_DIFFERENTIAL=PASS\n'
