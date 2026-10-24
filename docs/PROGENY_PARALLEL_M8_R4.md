# PROGENY R4 — bounded START/END multiprocessing for M8

## What is implemented

The raw M8 GAF collector may use one serial process (`--workers 1`, default)
or two independent Python worker processes (`--workers 2`). The new mode uses
`multiprocessing` with `spawn` and reconstructs a private, read-only donor
index in each child. Each worker scans one immutable, release-local GAF and
writes exclusively in its private START or END staging subdirectory. The
parent assembles outputs in canonical START-then-END order, verifies the same
SHA256, EOF, coverage, donor count, file inventory and input-stamp conditions,
and only then allows the existing atomic publication transaction to finish.

`spawn` is used instead of `fork` because the runtime may already have native
threads. This avoids fork-after-thread hazards and the GIL for the expensive
per-line Python scan. It comes at the cost of serializing/reconstructing donor
associations twice: high-throughput deployments need to measure RAM and startup
costs. It is not OpenMP; using OpenMP for the Python scanner would not be
useful. `workers` is limited to 1 or 2 because M8 has exactly two independent
release files in the current contract. Higher parallelism requires certified
sharding within each individual GAF, including exact physical-line IDs and
stable output ordering, and is NOT implemented here.

## Guarantees and caveats

- NO changes to release identity, START/END GOA filtering, donor eligibility,
  GAF line numbers, assertion IDs, NOT handling, or GO annotations.
- NO interleaved writes, shared SQLite database, shared output file, reordered
  scientific TSV, or silent publication on failed worker.
- A failure in either child is reported to the parent and prevents publication;
  outstanding child processes are terminated and joined.
- Optional `--workers=2` is exposed on the direct M8 CLI. The existing fresh
  DAG still launches that CLI without the switch and therefore remains serial
  until an independently certified, recipe-pinned runtime profile is wired.
- Source hash changes are expected in the *new* audit release's provenance.
  Do not use this installation to resume a frozen CAFA5 recipe.
- No speedup promise: gains depend on START/END scan balance, input filesystem,
  spawn overhead and donor-index memory. The R4 validation gate checks output
  equivalence on synthetic GAFs; representative full M8 speedup is not yet
  certified.

## Remaining performance waves

1. **06A:** R2 `(role,rid)` indexes are validated. R3 has only modest
   incremental gains; a sparse RID merge-join needs independent stress and
   full-workload output-parity before promotion. Keep CAFA5 job 66 untouched.
2. **Stage07:** profile target-level CPU, memory and dictionary size, then
   partition only independent target/release contexts.
3. **M10C:** profile GO closure recomputation and `term_code_support` UPSERTs.
   Consider independent `(release,target)` shards and deterministic integer
   aggregation. Preserve NOT descendants, all evidence codes, direct counts
   and conflicts; never parallelize writers against one SQLite database.
4. **Temporal:** benchmark private staging journal settings and target-level
   classification partitions against all published TSVs/JSON and logical
   SQLite contents. No unverified scratch pragma is installed by R4.
5. **Recipe/performance:** add an explicit pinned worker/RAM/CPU profile,
   Snakemake resource accounting, deterministic merge/failure/resume tests,
   clean fresh install and end-to-end science parity. A 128-core host should
   use available cores only where the algorithm is genuinely parallel.

## State

R4 introduces genuine two-process M8 parallel execution as a controlled
opt-in. It is NOT a multicore optimization of M10C, Temporal or the full 06A,
and it is NOT a certification of autonomous fresh end-to-end PROGENY.
