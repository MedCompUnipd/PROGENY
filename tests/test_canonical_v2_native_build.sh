#!/usr/bin/env bash
# Synthetic, no-compiler contract tests of the D provenance CLI.
set -Eeuo pipefail
umask 077
[[ $# -eq 2 ]] || exit 2
SCRIPT=$(realpath -e "$1")
ROOT=$2
mkdir -p "$ROOT/repo/cpp/src" "$ROOT/reports"
REPO=$ROOT/repo
printf 'cmake minimum, synthetic\n' > "$REPO/cpp/CMakeLists.txt"
printf 'synthetic lock\n' > "$REPO/pixi.lock"
printf 'synthetic pixi\n' > "$REPO/pixi.toml"
printf 'synthetic project\n' > "$REPO/pyproject.toml"
for unit in \
  release_fasta_v2 goa_normalize_v1 go_positive_filter_v1 raw_ox_extract_v1 \
  primary_candidate_scan_v1 primary_candidate_scan_v2 \
  direct_accession_anchors_v1 onehop_lineage_scan_v1 \
  full_exact_cross_strain_v1 directional_glocal_bounded_dp_v2 \
  directional_glocal_linear_dp_v1; do
  printf 'source\n' > "$REPO/cpp/src/progeny_${unit}.cpp"
  printf 'progeny-%s\n' "${unit//_/-}" >> "$REPO/cpp/CMakeLists.txt"
done
# Replace only the frozen HEAD constant for this disposable fixture.
git -C "$REPO" init -q
git -C "$REPO" -c user.email=test@example.invalid \
  -c user.name=Fixture add cpp pixi.lock pixi.toml pyproject.toml
git -C "$REPO" -c user.email=test@example.invalid \
  -c user.name=Fixture commit -qm 'Synthetic inventory fixture'
HEAD=$(git -C "$REPO" rev-parse HEAD)
sed "s/^FROZEN=e5abd2590c6fb43f105922309977cda61a8445b1$/FROZEN=$HEAD/" \
  "$SCRIPT" > "$ROOT/testing.sh"
bash -n "$ROOT/testing.sh"
bash "$ROOT/testing.sh" inspect "$REPO" "$ROOT/reports/ok.txt"
grep -q 'REQUIRED_NATIVE_TARGET_COUNT=11' "$ROOT/reports/ok.txt"
grep -q 'NATIVE_BUILD=NOT_YET_CERTIFIED' "$ROOT/reports/ok.txt"
[[ $(grep -c '^NATIVE_TARGET=' "$ROOT/reports/ok.txt") -eq 11 ]]
if bash "$ROOT/testing.sh" inspect "$REPO" "$ROOT/reports/ok.txt" \
    >"$ROOT/duplicate.log" 2>&1; then
  echo 'FAILED: allowed report overwrite' >&2
  exit 1
fi
if bash "$ROOT/testing.sh" build "$REPO" "$ROOT/reports/new.txt" \
    "$ROOT/new-build" --production-finished --allow-isolated-build \
    >"$ROOT/build.log" 2>&1; then
  echo 'FAILED: allowed build outside .pixi/build' >&2
  exit 1
fi
printf 'NATIVE_BUILD_SYNTHETIC_TESTS=PASS\n'
