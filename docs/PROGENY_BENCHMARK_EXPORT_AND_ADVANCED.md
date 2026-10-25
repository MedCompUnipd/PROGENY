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
wizard requires this token to be ASCII and parseable. Conflicting
repeated IDs are rejected; identical repeated records are deduplicated
with a recorded reason, without inventing new names.

For already-taxid-tagged input use `>SOURCE_ID<TAB>NCBI_TAXID`; the TAB
must be literal. Stage 00 excludes exact repeated records (same ID,
TaxID and sequence) and proteins shorter than 10 amino acids, and
records both reasons in `targets.rejected.tsv`. Different IDs with an
identical sequence remain separate biological target records. Unknown
TaxIDs remain a hard setup failure. If the IDs are genuinely UniProt
accessions, answer Yes to the explicit wizard question; otherwise leave
the optional accession metadata blank. This declaration validates
syntax but does not prove UniProt record existence.

For historical GOA exports named `*.gaf.N` (for example `.gaf.213`),
the wizard accepts the original uncompressed file directly after
checking its `!gaf-version: 2` header, without duplicating its contents.

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

The generated `START_PROGENY.sh` runs Snakemake first. **Only after** a
successful scientific run does it invoke the post-run collector:

```bash
pixi run python scripts/installation/publish_progeny_scientific_results.py \
  --dataset /absolute/path/to/study-dataset \
  --run /absolute/path/to/study-run
```

For a run executed using the canonical controller directly (rather than the
generated launcher), invoke this same command **after** canonical verification
has returned `PASS`. Do not introduce a second Snakemake rule or run the
collector before the 16-receipt certificate is available. For a failed
collector, repair the separate publisher and rerun this command only; never
rerun or change the completed scientific DAG just to obtain the report.

The collector checks the scientific completion certificate, canonical temporal
manifest, original FASTA identity ledger and the required inputs. It creates
`RUN_ROOT/results/benchmark/` atomically. Existing output is checked against
its recorded input/output SHA-256 checksums and reused only when unchanged.
It does not alter `RUN_ROOT/canonical/` or the study dataset.

### User-facing files

| File | Meaning |
| --- | --- |
| `ground_truth_targets.fasta` | Evaluable proteins only, restored full original headers and verified sequences |
| `benchmark_terms.tsv` | `(query_id, aspect, go_id, status)` including propagated `EVAL`, `SKIP`, `NEUTRAL` for eligible aspects |
| `skip_terms.tsv`, `neutral_terms.tsv` | Filtered convenience copies of the two metric masks |
| `target_aspects.tsv` | Every eligible target/aspect and its status counts |
| `target_identity_map.tsv` | All accepted user IDs, canonical `T000...` IDs, original headers, target TaxIDs and SHA-256 |
| `non_evaluable_targets.tsv` | Input proteins without EVAL in any GO aspect |
| `target_cohorts.tsv` | Eligible target/aspect, target species, START flags, event counts, classification status |
| `aspect_statistics.tsv` | MF, BP and CC status, direct event and NOVEL/CONFIRMATION counts |
| `species_statistics.tsv` | All represented target species TaxIDs and three aspects |
| `go_frequency.tsv` | Protein--GO association counts by GO term, aspect and status |
| `evidence_by_release.tsv` | **Aggregate M8** START/END evidence-code, polarity and source/link inventory; not a target-specific attribution table |
| `term_audit.tsv` | Scientific per-term reasons, including NOVEL and CONFIRMATION |
| `temporal_events.tsv` | Directly recorded temporal events; not all propagated EVAL |
| `negative_terms.tsv` | Negative/NOT provenance; not biological true negatives |
| `statistics.json`, `report.html` | Reconciled machine-readable results and offline summary |
| `README.md`, `EVALUATION_LEGEND.md` | Instructions and metric-mask semantics distributed with each benchmark |
| `manifest.json` | Publication identity and input/output checksum ledger |

`report.html` displays the 50 leading species; `species_statistics.tsv`
provides the full per-species inventory. Report a distinct input-protein
count separately from target/aspect and target/aspect/GO counts: they are not
interchangeable. The statistical collector does **not** compute predictor
Fmax, Smin, precision, recall or method rankings.

### Original FASTA header contract

The `query_id` in the annotation TSVs is the **first whitespace-delimited
token** after `>` in the user's original FASTA. The exported FASTA preserves
the **entire original header**, including its description or the TAB-delimited
NCBI TaxID, whereas `DATASET/targets/targets.fasta` is the internal FASTA
with `T000...` identifiers. Thus `>Q9CQV8<TAB>10090` produces user ID
`Q9CQV8`. `>sp P02397 description` instead produces user ID `sp`, not
`P02397`; multiple different targets with this first token conflict.
User-provided identifiers must be unique for distinct records. The
standalone strict Stage 00 importer allows deduplication only for identical
ID, sequence and TaxID, and records its rejected duplicates.

The original ID is *not* automatically interpreted as a UniProt accession.
If it is a real accession, select the explicit accession mode during setup.

### EVAL, SKIP, NEUTRAL and cohort semantics

Evaluate only `(query_id, aspect)` pairs listed in `target_aspects.tsv`.
Within an eligible aspect, an above-threshold EVAL prediction is a TP and a
missing EVAL prediction is an FN. SKIP and NEUTRAL are two distinct masks:
neither contributes to TP/FP/FN and neither establishes biological absence.
A valid, unmasked prediction not found in EVAL is an **operational benchmark
FP** for that eligible aspect, not a proven biological false assertion.
Explicit GO `NOT` evidence is preserved for review, not converted silently
into a biological true-negative population.

Validate scores and IDs, merge duplicate predictions by maximum, propagate
prediction scores upward using the same frozen GO graph and relation policy,
then apply the masks. **Do not stop propagation at a masked ancestor.**
Exclude ontology roots and invalid/unmapped terms under the evaluator's
explicit policy. Report Fmax and coverage separately by aspect and cohort;
full evaluation includes eligible proteins without predictions. Smin requires
an independently pinned and certified information-accretion table.

NK (no experimental knowledge in START), LK (experimental knowledge in another
aspect but none in the assessed aspect) and PK (experimental knowledge already
in the assessed aspect) are **target/aspect categories**, not synonyms for
per-term NOVEL or CONFIRMATION. Current `target_cohorts.tsv` sets
`knowledge_class=UNCLASSIFIED` until an independent, target-attributed START
experimental evidence audit is certified. Transferred donor evidence cannot
by itself establish NK/LK/PK. Do not claim NK/LK/PK-stratified predictor
metrics from this publication yet.

### Scientific interpretation and traceability

The collector counts all EVAL reasons from `term_audit.tsv`; direct END
SCORE EVAL events are counted separately from `temporal_events.tsv`. Terms
may be EVAL by GO propagation without direct source support at that exact
term. `evidence_by_release.tsv` provides M8 *aggregate* evidence inventories,
not per-target direct experimental annotation attribution. The current
collector cannot quantify documentary END-to-START look-ahead from those
aggregates; it reports `NOT_MEASURABLE_FROM_AGGREGATES`. Any retrospective
identification must be evaluated with a dedicated provenance audit.

For a detailed explanation see
[`PROGENY_POSTRUN_PUBLISHER_USER_GUIDE.md`](PROGENY_POSTRUN_PUBLISHER_USER_GUIDE.md)
and the independent publication contract in
[`PROGENY_POSTRUN_PUBLISHER_IMPLEMENTATION.md`](PROGENY_POSTRUN_PUBLISHER_IMPLEMENTATION.md).

## Before real CAFA5 production

Do not assume a fresh clone solves an inefficient DP workload. Verify
available scratch, memory, runtime profile, worker bottlenecks, and expected
CAFA5 workload on representative subsets. Keep the legacy CAFA5 process and
its checkpoints intact until a separately reviewed, targeted stop procedure
is authorized. Commit/push only after the release test gates pass.
