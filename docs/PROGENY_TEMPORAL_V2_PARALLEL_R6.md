# PROGENY R6: deterministic multiprocessing of canonical Temporal V2

Status: experimental optimization until the thanos gate passes. Audit-worktree
installation is not a certification of the full fresh end-to-end release.

## Scientific invariants

- No change to `_import_terms`, `decide`, GO propagation, NOT interpretation,
  evidence classes, target alias mapping, or temporal policy.
- Inputs and upstream file checksums retain the V2 verification contract.
- Each worker owns a disjoint range of *canonical* target IDs **after** all
  aliases have been resolved in the original serial SQLite import.
- The partition uses the binary order of the existing `terms` composite key.
- Every worker opens its own read-only `immutable=1` connection to the
  disposable committed SQLite state. No concurrent SQLite writers.
- Workers write five TSV files in separate temporary directories. The parent
  concatenates these files in canonical target order, removing repeated
  headers. All counters are added without losing individual reason counts.
- The two other published artifacts (`duplicate_targets.tsv` and
  `audit_reasons.json`) and manifest construction are unchanged.
- Errors in any worker abort publication; temporary partitions are removed
  when the outer staging directory is removed.

## Real concurrency

- `scripts/pipeline/08_build_benchmark_v2.py --workers 8` enables 8
  multiprocessing workers **only** for the final projection of the temporal
  state. `--workers 1` is the original serial algorithm.
- Supported values: 1 through 128. This is not OpenMP; Python worker
  processes are used to bypass the GIL for independent target groups.
- The worker pool uses `forkserver` on Linux to avoid forking after SQLite
  connections or auxiliary threads are active. This requires a standard
  importable Python package, as supplied by the PROGENY installation.
- Memory use grows with process count and per-worker mapping copies. A
  reasonable initial setting is 4-8 workers; higher values should only be
  chosen after profiling and with sufficient available RAM and CPU cores.
- The optimization can become slower on very small workloads, owing to
  process startup, partitioning and deterministic file merging.

## Certification boundary

The gate compares against the frozen V2 serial implementation: seven published
artifacts and manifests' output SHA256 dictionaries (including START/END NOT,
source-target aliases and duplicate ledger). It also compares five TSVs and
full event counters on a larger projection-focused dataset. Speedup must
clear a specified threshold *on thanos* before the audit-only files install.
This measurement does not imply an equivalent speedup in the complete V2
stage, whose SQLite import remains serial. That import is a candidate for a
separate proven optimization if profiling warrants it.

The canonical fresh DAG and the production CAFA5 recipe remain unchanged in R6.
The `--workers` parameter is available to the standalone Temporal V2 CLI;
parallel configuration of the complete fresh DAG awaits a separately validated
resource-schema change. Running multiple subprocesses does not by itself change
or circumvent Snakemake's allocated `threads` resource.

No git commit or push is performed by R6.
