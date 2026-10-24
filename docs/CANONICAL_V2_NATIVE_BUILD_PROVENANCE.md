# Canonical V2 native tools: source and build provenance

Status: **consolidation D / NOT_YET_CERTIFIED**.

This procedure does not modify the frozen scientific contracts, Snakemake
workflow, source files, result formats, or existing CAFA5 production. It
separates three different identities:

1. **Frozen source identity:** commit, CMake source, individual C++ translation
   units, Pixi configuration and lockfile SHA-256.
2. **Installed binary identity:** hashes, build flags, compiler, build directory,
   and library environment. These must be measured for each installation.
3. **Scientific equivalence:** bounded/rolling DP differential tests and a
   fresh end-to-end test. Hashes and successful compilation alone cannot prove it.

## Scope

The fresh canonical V2 execution currently requires **11 native tools**:
release FASTA, GOA normalize, GO-positive filter, raw OX extraction, primary
candidate scan V1/V2, direct accession anchors, one-hop lineage scan, FULL
EXACT cross-strain, bounded DP V2, and rolling DP V1. CMake defines two
additional legacy targets, but they are not in this 11-tool inventory.

The versioned Pixi tasks compile into per-tool build trees. The active CAFA5
recipe instead references its two DP binaries under the existing production
`progeny-exact-large-dp` directory. Those installations must **not** be silently
assumed byte-identical. The older file `PROGENY_CANONICAL_V2_DP_BUILD_PROVENANCE.txt`
describes a different compiler invocation and different compiled binary.

## Inspect mode — safe while CAFA5 runs

```bash
bash scripts/validation/canonical_v2_native_build.sh inspect \
  "$REPO" "$SAFE_TMP/native-inspection.txt"
```

This mode reads only the selected repository's source/configuration files and
writes a new manifest in the specified output directory. It does not import
Python, run CMake, build tools, install Pixi or read biological input payloads.
All output reports must use previously unused absolute filenames.

## Isolated build mode — do NOT run while CAFA5 is active

The build operation requires a successful CAFA5 exit receipt when running on
this server, explicit opt-in flags and an isolated, previously unused directory
under the **audit** checkout's `.pixi/build`. It is *not* executed by the
consolidation D installer.

After the production is finished, separately install the Pixi environment in
the audit checkout from the frozen `pixi.lock`. Only then consider:

```bash
mkdir -p "$REPO/.pixi/build"
bash scripts/validation/canonical_v2_native_build.sh build \
  "$REPO" "$SAFE_TMP/native-built.txt" \
  "$REPO/.pixi/build/canonical-v2-autonomy-11" \
  --production-finished --allow-isolated-build
```

The build uses the checkout-local CMake and Ninja executables, CMake's Release
configuration and a two-job limit. It writes a new build directory and a report;
it never updates production build artifacts. This is a *controlled technical
build*, not a declaration that a locked environment has been reconstructed or
that the produced binary behavior is scientifically equivalent.

The CMake compiler, flags, version and effective linked libraries must be
reviewed from its cache and binary inspection. Capture the exact environment
activation/toolchain variables used in a future fully reproducible installer;
selecting CMake from Pixi without explicitly activating the compiler toolchain
is not by itself proof of toolchain reproducibility.

## Still required for certification

- Complete source/build correspondence and effective compiler/library manifest.
- Reproducible Pixi installation from a *clean clone* on Linux x86-64.
- Differential real-pair bounded/rolling DP validation on newly built binaries.
- Other native CLI contract tests and end-to-end small fresh pipeline.
- Recovery test and final manifest/GO/temporal verification.

No existing canonical fingerprint is changed by this consolidation step.
