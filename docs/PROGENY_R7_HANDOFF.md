# PROGENY R7 consolidation handoff (23 October 2026)

## Frozen production must remain untouched

- Production repository: `[HISTORICAL_MACHINE_PATH_REMOVED]`.
- Frozen production commit: `e5abd2590c6fb43f105922309977cda61a8445b1`.
- Active full CAFA5 root: `[HISTORICAL_MACHINE_PATH_REMOVED]`.
- Frozen recipe SHA256: `9bb871187ee2b6edff5d3d6170636bd99d34eaf2e76337e4f906ea1879d418fd`.
- Running CAFA5 job 66 originally showed extremely slow SQLite-intensive
  scanning of the END candidate TSV. Do **not** signal the process, open or
  mutate its SQLite, alter its binaries, or change its recipe. Its current
  completion state must be observed afresh on the server, not inferred here.

## Separate uncommitted consolidation worktree

`[HISTORICAL_MACHINE_PATH_REMOVED]`, branch
`chatgpt/progeny-v2-autonomy-consolidation`, same base commit.
No automatic commit or push. Prior stages:

- R2: `(role,rid)` SQLite indexes on 06A candidate/full-store paths, synthetic
  output parity, microbenchmark and effective-function benchmark passed.
- GCC 14.4: standalone native-release CMake profile, thirteen targets compiled,
  bounded O3, rolling O2; original production binaries not replaced.
- R4: M8 independent START/END worker processes, 2-worker benchmark ~1.69x,
  tests and parity passed; installed in audit only.
- R5: M10C RAM reducer, targeted 5.53x for medium synthetic case,
  tests and parity passed; installed in audit only.
- R6: Temporal V2 **actual** CLI projection processes 1-128, 8 workers
  measured 3.73x on projection; seven published outputs scientifically
  equivalent on test fixtures; installed in audit only.
- R3 was experimental and should not replace R2 without new large-scale proof.
- R7 (this package) wires M8 and Temporal via actual Snakemake allocation.
  Stage 06A and M10C do not become multicore merely by raising resources.

## R7 scope and priority

R7 edits only `workflow/canonical_v2_fresh.smk`,
`src/progeny/canonical_v2/fresh_publication.py`,
`src/progeny/canonical_v2/dag_execution.py`; adds
`src/progeny/canonical_v2/runtime_resources.py`, focused tests,
`config/progeny.performance.example.json`, and documentation.

Precedence: the optional performance profile requests workers; Snakemake
`--cores` limits **effective threads**; the effective number alone is forwarded
as CLI `--workers`; external fresh execution intents pin effective workers,
mem reservation, and the performance file SHA256. `mem_mb` is only a Snakemake
reservation, not a kernel RSS cap. DP still uses frozen recipe `limits.threads`.
No scientific GO, TaxID, EXACT, NONEXACT, NOT, temporal mask or DP logic
may be changed. Output scientific fingerprints and schemas remain immutable.

Ruff requirement on new/modified Python: `ruff check --fix` then
`ruff format` then `ruff check` then `ruff format --check`; E501 <=88 columns.
Use staging and AST comparison before installing. Stage R7 install only on
PASS of guards, Ruff, tests and Snakemake syntax parsing. The complete
cold-install fresh E2E **is not certified** by the R7 wiring test alone.

## Remaining release-blocking items

1. Verify R7 report (`INSTALL_EXIT=0`, provenance, actual worker CLI test and
   Snakemake parse). If failed, diagnose the single precise cause; no false PASS.
2. Run complete cold-install genuine fresh E2E and safe resume on a fresh
   isolated test dataset, including actual M8=2 and Temporal=8 in the DAG;
   compare 16 receipt/bundle integrity and temporal seven artifacts to the
   serial scientific baseline (path-independent byte parity).
3. Profile full 06A and end-to-end Stage07/M8/M10C/Temporal on larger,
   representative inputs; improve remaining serial hotspot only after parity.
4. Finish standalone installation, packaging, CLI, documentation, pinned
   raw-data contracts, manifest/test audit and Git review. Do not claim
   `REPOSITORY_AUTONOMY=CERTIFIED` until all cold-run gates pass.
5. Only after explicit user approval: commit/push changes to development
   branch; never touch the frozen CAFA5 production worktree.

## New chat transfer

Give the next chat **this handoff and the latest R7 `UPLOAD` report**; ask
it to continue from the exact verified R7 gate, not to recreate earlier
validated R2/R4/R5/R6 work. Keep one packaged operation and one report per
increment; perform rigorous read-only source preflight first.
