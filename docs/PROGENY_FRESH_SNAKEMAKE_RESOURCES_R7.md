# PROGENY R7 — real Snakemake resources for the fresh canonical DAG

## Implementation and precedence

This patch targets **`workflow/canonical_v2_fresh.smk` only**. It does not
change `workflow/Snakefile`, `workflow/canonical_v2.smk`, policy semantics,
GO inputs or the immutable CAFA5 run. An optional, explicit JSON performance
profile is parsed at DAG planning; without it, both M8 and Temporal remain
serial, just as in the frozen version.

The precedence is: **requested workers in the performance profile → Snakemake
`--cores` allocation (`threads` within the running job) → actual `--workers`
argument** sent through `execute_node` and `dag_execution.dispatch` to the
installed M8 R4 and Temporal V2 R6 CLIs. M8 supports at most two processes;
Temporal V2 supports 1–128. The profile does not create parallelism in M10C
or in 06A; those remain single-process until explicitly optimized and verified.
The existing alignment `limits.threads`, DP backend, limits and policy are
unchanged. No OpenMP is pretended for Python-only stages.

Example for a **new, isolated, freshly prepared** run (replace both absolute
paths and sizes with the user-specific files and hardware limits):

```bash
pixi run snakemake -s workflow/canonical_v2_fresh.smk \
  --cores 16 --resources mem_mb=131072 dataset_io=1 \
  --config fresh_recipe=/absolute/path/to/new/fresh_recipe.json \
           performance_profile=/absolute/path/to/performance.json
```

The profile declares per-stage `mem_mb` **scheduler reservations**, not a hard
RSS cap or an allocation of that memory. Use an aggregate Snakemake resource
limit (`--resources mem_mb=...`), retain headroom for OS page cache, and do not
claim 32/64/128 GiB were actually consumed. Avoid saturating shared servers.

## Identity and restart

The scientific recipe/schema and content identity remain unchanged. Effective
worker count, reserved RAM, and the profile-file SHA256 are written into the
existing external fresh **execution intent** for M8 and Temporal. The independent
completion verifier reads and verifies the pinned execution information.
Rerunning an already-started stage with different resources fails closed; it
**never overwrites** its published scientific bundle. Existing old receipts
without this optional runtime metadata remain readable, though resuming with a
new explicit profile may reject a changed M8/Temporal intent. Do not retrofit
R7 into the ongoing CAFA5 run.

Snakemake may lower `threads` when fewer `--cores` are available; the actual
lower allocation is used to create the worker subprocesses and pinned to the
intent, not the original request. A profile change after execution must be
considered a different execution configuration, not a silent scientific
recalculation. Disallow unknown profile keys, booleans in integer fields and
symlinked/relative profiles.

## Preflight gates and scope

The R7 installation gate must verify real R4/R6 CLI `--workers`, Ruff `check
--fix` → `format` → `check` → `format --check` on staging only, AST stability,
focused tests, and a Snakemake parse/dry-run in an isolated synthetic recipe.
At present the **complete cold-install scientific E2E and full-sized speedup
remain pending**; a successful R7 resources gate does not certify them.
No commit or push occurs in this change. Production `e5abd259...` is frozen.
