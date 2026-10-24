# Canonical V2 run control: verify and conservative resume

Status: consolidation C, not a replacement for frozen scientific contracts.
This entrypoint is **NOT_YET_CERTIFIED** on a clean server or full-size dataset.

The existing raw-input workflow and scientific implementations remain unchanged.
`fresh_control.py` delegates to the frozen `read_recipe`,
`validate_existing_upstreams`, `validate_node_receipt`, and
`validate_completed_workflow` implementations. This wrapper never repairs or
removes a damaged immutable publication, and never imports historical bundles.

## Prerequisites

* Prepare a new run with `prepare_canonical_v2_fresh.py` (consolidation B).
* Run from the **same checkout** recorded in the prepared `fresh_recipe.json`.
* Install the checked-out Pixi environment and all native tools separately.
* Configure explicit persistent large-DP scratch on the same filesystem as
  the new run. Preserve it through interruptions.
* Before resuming, confirm that **all** earlier Snakemake producers, native
  children, and external workflow launchers for this run have stopped. The
  wrapper cannot reliably detect unrelated external processes. Do not start
  two workflows against the same run root.

## Commands

Use the checkout's Python and set `PYTHONPATH=$REPO/src` and
`TMPDIR=/path/to/safe/tmp` before calling this CLI. `RECIPE` is an absolute path.

```bash
python scripts/pipeline/control_canonical_v2_fresh.py \
  --recipe "$RECIPE" inspect

python scripts/pipeline/control_canonical_v2_fresh.py \
  --recipe "$RECIPE" inspect --deep

python scripts/pipeline/control_canonical_v2_fresh.py \
  --recipe "$RECIPE" first --cores 8 --memory-mb 32768 --dry-run

python scripts/pipeline/control_canonical_v2_fresh.py \
  --recipe "$RECIPE" first --cores 8 --memory-mb 32768

python scripts/pipeline/control_canonical_v2_fresh.py \
  --recipe "$RECIPE" resume --cores 8 --memory-mb 32768 \
  --confirmed-stopped

python scripts/pipeline/control_canonical_v2_fresh.py \
  --recipe "$RECIPE" verify
```

The deep preflight and final verification read full biological publication
payloads and can be expensive. `inspect` defaults to structural checks only:
its success **does not imply** payload-level integrity.

`first` rejects prior scientific state. `resume` requires an explicit stopped
confirmation, deep-validates existing raw publications and any completed
canonical receipt, then invokes Snakemake normally **without** `--forceall`,
`--forcerun`, `--rerun-incomplete`, or forced cleanup. Snakemake's own lock
remains enabled. If Snakemake rejects incomplete files, investigate; do not
blindly use `--rerun-incomplete` against immutable publications.

The wrapper keeps an advisory lock for other cooperative wrapper instances.
This lock alone cannot exclude Snakemake started through a different program.
After Snakemake returns status 0 the wrapper publishes a run-local immutable
success marker and invokes the frozen final completion verifier. A reported
execution success therefore requires **both** Snakemake and the final verifier
to pass. `verify` requires that exact marker; it does not accept an arbitrary
historical process exit log as proof of this wrapper's execution.

The final verifier writes a canonical verification receipt below the run's
`verification/` tree. This is a planned scientific attestation write, not a
read-only command. Never run this C CLI against the currently active CAFA5
run; that run uses the frozen production checkout and its original launcher.
Its post-production verification is a separate controlled gate.

## Remaining gates

This wrapper's synthetic unit tests mock the Snakemake subprocess and the
final scientific verifier; they prove routing and failure behavior, not full
scientific reproducibility. Before certifying run control, validate a real
small complete fresh execution, interruption/resume, and damaged-publication
rejection on an isolated test run. Build provenance and clean-installation
certification remain pending.
