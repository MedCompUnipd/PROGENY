# PROGENY Alpha: user-facing ground truth and Power User configuration

## Two configuration levels

**Guided (default):** run `bash SETUP_PROGENY.sh`. Provide the FASTA, TaxID
context, START/END UniProt, GOA and taxonomy snapshots, and the pinned GO
ontology. The wizard uses the reviewed evidence-code classes and current DP
and worker defaults. It asks for the ordinary core count and optionally
creates a single-node SLURM launcher. It prepares the run but does **not**
execute the scientific pipeline.

**Power User (opt-in):** copy `config/progeny.advanced.example.json` outside
the code checkout and edit it. During the wizard select the advanced JSON
path. For non-interactive setup pass `--advanced-config /absolute/file.json`
(or use `advanced_config` inside `--answers`; never both). Do not modify a
prepared or running study's config: create a **new dataset and run**. The
validator rejects unknown fields, invalid budgets, wrong evidence-code sets,
and workers exceeding the CPU allocation.

Advanced JSON options:

| Field | Meaning |
| --- | --- |
| `threads` | Snakemake cores and the maximum total CPU allocation |
| `max_pair_cells` | Pairwise DP cell guardrail |
| `max_total_cells` | Overall DP cell guardrail |
| `max_chunk_cells` | Per-chunk DP cell guardrail |
| `max_dp_memory_bytes` | Linear DP backend memory budget (bytes) |
| `checkpoint_rows` | Linear DP checkpoint row interval |
| `temporal_policy` | Absolute path to a copy of the temporal evidence classes JSON, or `null` |
| `performance_profile` | Absolute path to an execution-only worker/memory profile JSON, or `null` |

The worker profile follows `config/progeny.performance.example.json` and
contains `m8_workers` (1..2), `temporal_workers` (1..128), and memory
reservations `m8_mem_mb`, `m10c_mem_mb`, `temporal_mem_mb`. Workers are
bounded by `threads` and Snakemake may schedule them under shared resource
limits. `m10c` has no parallel-worker setting; adding one would be fictitious.
SLURM partition, account, walltime and memory are provided by the regular
wizard. The existing SLURM launcher is single-allocation / single-node,
not an automatically distributed multi-node scheduler.

### Evidence-code default

Default `SCORE` (all eleven experimental): `EXP, IDA, IPI, IMP, IGI,
IEP, HTP, HDA, HMP, HGI, HEP`.

Default `NON_SCORE`: `IBA, IBD, IKR, IRD, IC, TAS, ISS, ISO, ISA,
ISM, IGC, RCA, IEA`.

Default `EXCLUDED`: `NAS, ND`.

These are **PROGENY operational evidence tiers**, not an official universal
ranking of GO evidence. To change them, copy
`config/stage08_evidence_classes_v2.example.json` outside the checkout and
set `temporal_policy` in the advanced JSON to that copy. The valid class
selection has `include_groups`, `include_codes`, `exclude_codes`. All
registered codes must belong to exactly one class; `SCORE` must be nonempty.
The validator uses the real Stage08 parser (`load_classes`) before setup.
The chosen file is copied to the dataset, included in policy provenance and
used by the immutable temporal benchmark, not by the GOA normalizer.

## Original FASTA identifiers

The original input header is preserved **literally**, including any
user-supplied description or, for already-taxid-tagged FASTA, the TaxID tab.
For the ordinary FASTA modes, `query_id` in the user-facing TSV is the
**first whitespace-delimited identifier** from the header. The existing
wizard requires this token to be unique, ASCII and parseable. It rejects
ambiguous or duplicate source IDs, rather than inventing new names.

The original header provenance is snapshotted at Guided Setup in
`dataset/identity/original_headers.tsv`, checksum-locked by its manifest,
and independently reconciled against Stage 00 mapping and sequence hashes.
Internal `T000000...` target identifiers continue to be the sole keys in
the canonical scientific publications and remain visible to developers in
`target_identity_map.tsv`.

**Do not substitute a discovered UniProt accession for the user's input ID.**
The original protein identifier is not necessarily a UniProt accession.
The optional original UniProt accession, candidate accession and biological
identity remain separate concepts.

## After the successful scientific run

Use the generated `START_PROGENY.sh` (direct, tmux, nohup, or its SLURM
wrapper). After Snakemake successfully publishes the temporal benchmark,
it calls the read-only adapter:

```bash
pixi run python scripts/installation/export_progeny_benchmark.py \
  --dataset /absolute/path/to/study-dataset \
  --run /absolute/path/to/study-run
```

**Nothing is exported at setup time.** The adapter requires the temporal
completion receipt and validates every source payload checksum against the
canonical publication. The new directory is created atomically under
`run/results/benchmark/`; no file under `run/canonical/` or `dataset/targets/`
is overwritten. On a rerun it verifies the existing bundle and reuses it,
never silently overwriting a publication.

| File | Use |
| --- | --- |
| `ground_truth_targets.fasta` | Evaluable targets only, with original complete FASTA headers and exact sequences |
| `benchmark_terms.tsv` | User `query_id`, aspect, GO and `EVAL`/`SKIP` status |
| `skip_terms.tsv` | User query IDs and GO terms intentionally excluded from evaluation |
| `target_aspects.tsv` | Which target/aspects were eligible and their counts |
| `temporal_events.tsv` | NOVEL, CONFIRMATION and other dated events by original ID |
| `term_audit.tsv` | Per-target decision and evidence flags by original ID |
| `negative_terms.tsv` | Documented negative/NOT audits, **not** assumed biological negatives |
| `target_identity_map.tsv` | Every Stage 00 accepted input ID, complete header, internal ID, original TaxID, length hash and evaluability |
| `non_evaluable_targets.tsv` | Target IDs with no EVAL in any aspect; absence of EVAL is not a biological negative |
| `statistics.json` | Machine-readable target, aspect, species and release statistics |
| `report.html` | Standalone offline human-readable report |
| `manifest.json` | Output and source checksum ledger |

Proteins with no EVAL in **any** ontology aspect are omitted from the
user-facing FASTA but retained in `target_identity_map.tsv` with `NO_EVAL`.
A target can be evaluable for MF while not evaluable for BP or CC; always
read the `aspect` column. The number of GO pairs with repetitions is the
number of distinct `(user ID, aspect, GO)` records, whereas *unique GO* is a
term count independent of how many proteins share that term.

Biologically identical original targets assigned a common original UniProt
accession can be coalesced by the canonical benchmark. The adapter uses the
verified duplicate-target ledger to project that canonical result back to
**each** original FASTA ID and reports the expanded user-ID counts separately
from canonical counts. It never collapses missing-accession targets.

The report lists the producer-reported UniProt FULL and GOA normalization
counters separately for START and END (with their original counter names),
target-survival statistics, GO EVAL/SKIP counts per aspect, species-TaxID
representation, documentary evidence class, and source provenance. Taxonomy
names may not be available, so the report uses unambiguous resolved species
NCBI TaxIDs. No metric/ROC tool is run and no unknown GO pair is labeled as
a biological true negative.

## Before real CAFA5 production

Do not assume a fresh clone solves an inefficient DP workload. Verify
available scratch, memory, runtime profile, worker bottlenecks, and expected
CAFA5 workload on representative subsets. Keep the legacy CAFA5 process and
its checkpoints intact until a separately reviewed, targeted stop procedure
is authorized. Commit/push only after the release test gates pass.
