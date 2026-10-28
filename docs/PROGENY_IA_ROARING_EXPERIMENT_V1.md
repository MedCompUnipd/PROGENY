# Native Roaring IA backend

This is the default standalone IA backend. It runs after benchmark publication
and does not change the canonical workflow or its thirteen native tools. The
supported user entry point is `pixi run prepare-evaluation`; that command
builds or reuses the pinned executable and publishes IA outside the benchmark
DAG. Synthetic differential tests establish implementation regression
coverage, not full-corpus scientific equivalence.

## Scientific identity

The scientific publication remains `progeny-information-accretion-v3`. The
manifest records a separate `progeny-ia-roaring-backend-v1` implementation
identity. Source-GAF row audits, accepted evidence, NOT exclusion, aliases,
replacement ambiguity, cross-aspect exclusion, graph projection, unique
protein/GO pairs, parent conjunctions, roots, orphans and add-one smoothing
are checked against fixtures by the test suite. IA is calculated in Python
from integer native counts, using the specified `math.log2` expression. The
long-running SQLite CAFA5 attempt is not a validation oracle and no production
claim depends on its completion.

Python resolves each ontology identifier and alternate identifier once and
exports a pinned graph and resolution table. It reads the GAF in 4 MiB chunks,
updates SHA-256, and forwards those bytes to the native child. C++ parses the
17-field GAF, preserves the v3 audit rules and assigns integer IDs to accepted
UniProtKB object IDs. The IDs are opaque: protein ordering is not assumed.
The engine fails before exhausting its 32-bit identifier space.

Each GO has a CRoaring bitmap of its directly annotated proteins. Bitmaps
propagate once per DAG edge, children before parents. Duplicate rows and paths
cannot double-count a protein. An aspect's population is the union over all
its GO bitmaps, including disconnected orphans; it is not assumed equal to a
root's bitmap. Parent conjunction counts are exact bitmap intersections.
Only the final intersections are parallelized; propagation and parsing are
currently single-threaded. No protein-by-protein transitive closure or SQLite
membership table is constructed.

## Dependencies and build

Unmodified CRoaring 5.4.0 sources and its dual Apache/MIT license are vendored
under `experiments/ia_roaring/vendor/CRoaring`. The upstream commit is
`20495fec4d1622b93284033a160f67d21a5aa8bb`; every included file has a SHA-256
entry in `CRoaring.lock.json`. The builder verifies exact inventory and hashes.
No network download or dependency solve is performed during compilation.

Use `pixi install --locked`, then run:

```bash
pixi run python scripts/evaluation/build_information_accretion_roaring.py \
  --build-dir /absolute/new/external/build --jobs 2
```

The separate CMake project uses the existing locked C/C++ GCC 14.4.0, CMake,
Ninja and OpenMP. It does not enter the canonical CMake graph. AVX-512 is
disabled for this initial profile; no `-march=native` or fast-math is used.
`build_provenance.json` records compilers, source/lock digests and binary hash.
A development-toolchain override exists only for local development and is
explicitly recorded; it does not establish a locked server build.

## Verification and bounded performance comparison

`pixi run test` builds all thirteen canonical native tools, builds CRoaring in
isolated temporary space, sets `PROGENY_IA_ROARING_BINARY`, and runs the full
suite. Missing native tools fail this task rather than being silently skipped.
The Roaring tests cover result equivalence on synthetic graphs, seeded input,
more than 65,536 proteins, malformed input, wrong input hashes, graph cycles
and overwrite refusal. They do not establish a full corpus comparison with a
second independent implementation.

`benchmark_information_accretion_roaring.py` is a historical bounded-prefix
differential/performance tool. Any SQLite comparison is informative only for
the selected prefix; it is neither a full-corpus correctness certificate nor a
required runtime dependency. The full source GAF hash is marked
`NOT_REVERIFIED` in that prefix experiment.

## Full calculation and resource limits

`prepare-evaluation` derives GAF, START role, release, ontology and expected
digests from setup metadata. The lower-level
`compute_information_accretion_roaring.py` accepts those identities explicitly,
plus
`--native-binary`, `--threads` and `--max-address-space-gib`. Scratch and output
must be outside the source checkout and input directories. Output must be
virgin. The prepare command accepts the publication only after native
computation, input checksum verification, manifest validation and table
checksum verification succeed. Failures do not select an alternate backend.

The default 128 GiB limit is Linux RLIMIT_AS on the native child, encompassing
its protein dictionary, bitmaps and concurrent intersection temporaries. It
is an address-space limit, not an RSS limit on the whole process tree. The
Python parent separately holds the ontology, precomputed policy and a small
streaming buffer. The native effective limit and peak RSS are recorded.
Core dumps are disabled for the native child. A native allocation failure
fails the calculation, and no valid IA publication is produced.

The manifest includes binary, graph, policy and Python implementation hashes.
The CLI rechecks ontology and implementation digests before writing output.
The scientific comparison reader already accepts v3 with additional backend
provenance; old scientific IA schemas are not silently migrated.
