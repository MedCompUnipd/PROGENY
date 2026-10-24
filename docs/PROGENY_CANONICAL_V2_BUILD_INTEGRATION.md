# Canonical V2 certified bounded DP: integrated build

Source: `cpp/src/progeny_directional_glocal_bounded_dp_v2.cpp`.
CMake target: `progeny-directional-glocal-bounded-dp-v2`.
Pixi tasks: `build-certified-bounded-dp-v2`, `certified-bounded-dp-v2`.
The CMake target links `OpenMP::OpenMP_CXX`.

The existing independently verified manual GCC 12.2.0 build is preserved
at `.pixi/build/progeny-certified-bounded-dp-v2/certified-bounded-dp`, with
source and binary hashes in `docs/PROGENY_CANONICAL_V2_DP_BUILD_PROVENANCE.txt`.
The CMake Release build can produce a different binary hash due to build
flags and must not be represented as byte-identical without verification.

Historical pre-FIX1 documents are retained under
`docs/archive/canonical_v2_pre_fix1/` but are not authoritative contracts.

Global execution remains BLOCKED until START/END IUPAC26 FULL EXACT,
START/END unified discovery, and upstream input manifests are certified.
Do not substitute the 128-target pilot discovery for full-universe data.
