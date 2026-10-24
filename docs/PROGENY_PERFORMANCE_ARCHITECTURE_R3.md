# PROGENY performance architecture — R3 investigation and roadmap

**Scope:** the future installable release, NOT running CAFA5. All science,
release provenance, GO NOT semantics, DP gate decisions, and byte-level
publication contracts are frozen. No source is altered in the production
worktree. R3 is an experimental benchmark and code-review archive only.

## Proven facts

- The canonical fresh DAG schedules `workload`, `m8`, `m10c`, `temporal`
  at **one Snakemake thread each**. Only `alignment` uses `limits.threads`.
  Increasing `threads` in the Snakemake resources declaration without changing
  the worker implementations will not create parallel execution.
- 06A boundary and merged FULL-store queries originally used role/rid predicates
  against (role,target,rid) PKs; R2 installed `(role,rid)` indexes. R3 reduces
  the two per-store UPDATEs to one and streams extra reference counts in RID
  order. Exact Python-function parity and full synthetic-science test parity
  are required before any promotion.
- M8 scans two completely separate START/END GAF releases serially.
- M10C groups source assertions, propagates through the pinned ontology and
  performs repeated UPSERTs into `term_code_support`. It already has an index
  `direct_by_source`. Do not add indexes without examining EXPLAIN plans and
  insert overhead. The GO graph's descendants used for NOT are not optional.
- Temporal uses `(target_id,aspect,go_id)` as its state-table primary key and
  commits batches of 8192 updates with FULL-synchronous disk journaling,
  despite this DB being private staging discarded before publication. R3
  separately experiments with MEMORY journal + synchronous OFF, matching
  M10C's existing scratch policy. Requires full Temporal output-parity before
  adoption. It is NEVER applied automatically by this package.

## Proposed runtime config for new, identity-pinned fresh recipes

Scientific identity remains independent of thread scheduling, but each run
**must pin and record** the runtime resource profile in its execution receipts.
Suggested future performance controls, not yet wired into current code:

```yaml
performance:
  threads_total: 32
  workers_workload: 16
  workers_m8: 2
  workers_m10c: 16
  workers_temporal: 16
  ram_budget_gib: 64
  sqlite_cache_mib_per_worker: 1024
  scratch_root: /path/on/local/ssd
  profile_phases: true
  deterministic_merge: true
```

The scheduler must prevent oversubscription (`workers * cache + input/state
buffers <= ram_budget`), and honor CPU availability and cgroup limits.
`ram_budget_gib` is a requested *budget*, not a hard RSS limit; users must
provision extra headroom for the OS page cache, open files, DB sorts, and DP.
Example supported configurations in the future release should include
small (8 threads / 16 GiB), balanced (16-32 / 64 GiB), and high-throughput
(64-128 / 128+ GiB), after realistic memory profiling. DO NOT enable 128
workers merely because 128 CPU cores exist, especially on a shared host.

## Engineering sequence and core correctness contract

1. **06A:** benchmark R3 vs R2 on the real frozen functions, then build
   a sorted sparse RID-to-candidate join to remove per-RID SQL roundtrips.
   Compare resulting candidate/overlap attestations including all negative
   tests, empty/orphan groups, conflicting hashes, fragmented sequences,
   canonical RID ordering, and target/RID fan-out. On large data, shard
   independent target groups into immutable worker outputs, one SQLite writer
   per shard, then merge using the existing scientific canonical order.
2. **Stage 07:** first profile resolver hotspots and RAM use. Partition only
   independent target/release work after preserving per-target policy context.
   Do not parallelize shared mutable resolver state.
3. **M8:** execute START/END GOA collection in separate bounded worker
   processes; certificate SHA, input stamps, and output order exactly as in
   the current sequential implementation. Recombine only after both pass.
4. **M10C:** index direct links once, pre-compute GO ancestors/descendants as
   read-only per-worker data; group by `(release,target_id)` into independent
   shards, batch/reduce inherited supports with exact integer arithmetic;
   one SQLite writer per shard, merge `term_code_support` by canonical key.
   Preserve every `NOT`, every evidence code, `direct_count`, donor
   provenance, and direct/propagated conflict.
5. **Temporal:** make evaluation partitions independent by canonical target
   group, then deterministic merge of five published TSVs in target/aspect/GO
   order. Preserve START/END flags, NOT precedence, GO direct/refinement,
   duplicate aliases, benchmark EVAL/SKIP/NEUTRAL and existing summary counts.
6. **End-to-end:** run baseline vs optimized on representative data (including
   large target and GOA sets). Require exact row/column ordering, byte-SHA
   parity of scientific TSVs/JSON where path-independent; logical row-level
   parity for private/published SQLite content where file packing varies.
   Verify complete DAG fresh install and resume, peak RSS, disk, CPU, wall,
   thread saturation, determinism at 1/2/8/32/64 workers, and failure
   recovery. No publication before all checks pass.

**Execution model:** OpenMP/C++20 is useful for CPU-intensive per-target or GO
closure computation. SQLite's single-writer transaction and Python's GIL
must not be mistaken for OpenMP-parallel stages. For DB stages, partition into
separate processes/shard DBs and merge deterministically; compare against a
single-thread scientific oracle. Resource knobs take effect only when a
parallel implementation has actually been wired, tested and scheduled.

**Status:** R2 indexes installed and tested; R3 06A fast path tested locally;
Temporal journal change EXPERIMENT ONLY; full parallel execution NOT BUILT.
