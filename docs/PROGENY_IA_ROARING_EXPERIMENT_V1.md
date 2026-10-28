# Experimental native Roaring IA backend

This backend is additive and opt-in. The original SQLite IA implementation,
canonical workflow, thirteen native tools, Pixi environment and lock remain
unchanged. Build and execute it in the isolated IA worktree. It is not certified
for full-corpus production merely because fixture equivalence passes.

## Scientific identity

The scientific publication remains `progeny-information-accretion-v3`. The
manifest records a separate `progeny-ia-roaring-backend-v1` implementation
identity. Source-GAF row audits, accepted evidence, NOT exclusion, aliases,
replacement ambiguity, cross-aspect exclusion, graph projection, unique
protein/GO pairs, parent conjunctions, roots, orphans and add-one smoothing
must match the SQLite reference. IA is calculated in Python from integer
native counts, using the same `math.log2` expression; TSV output must be
byte-identical on the same corpus and Python runtime.

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

Set `PROGENY_IA_ROARING_BINARY` to the absolute executable path and run
`tests/test_information_accretion_roaring.py`. These optional tests are skipped
when that variable is absent; a nonexistent explicitly requested binary is an
error. They compare complete scientific result dictionaries and IA TSV bytes
against SQLite, including seeded random DAGs and more than 65,536 proteins.
They also test malformed input, wrong input hash, graph cycles and overwrite
refusal. Run the existing full suite with an isolated existing `TMPDIR` and
build the canonical thirteen tools before accepting server validation.

`benchmark_information_accretion_roaring.py` copies a bounded initial prefix
(default 100,000 data rows, maximum 1,000,000), computes its digest, executes
both implementations sequentially and requires exact scientific equality.
It records elapsed times, speedup and native peak RSS. The full source GAF
hash is explicitly marked NOT_REVERIFIED in this prefix experiment. A prefix
benchmark is not a prediction of full-corpus time or peak memory.

## Full calculation and resource limits

`compute_information_accretion_roaring.py` accepts the same explicit GAF,
START role, release, ontology and expected digests as the SQLite CLI, plus
`--native-binary`, `--threads` and `--max-address-space-gib`. Scratch and output
must be outside the source checkout and input directories. Output must be
virgin. No output publication is started until native computation and input
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
