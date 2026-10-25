# PROGENY: start your first study (without writing configuration files)

**For biologists and laboratory researchers.** The installer asks ordinary
questions about your study and generates the scientific configuration itself.
No JSON, YAML, Python editing, Git operations, or familiarity with Snakemake
is required. The scientific decisions are shown and must be explicitly approved.

## What you need in advance

1. A computer/server running **Linux** with **Pixi** installed, sufficient
   CPU, memory, and disk space, and a PROGENY checkout.
2. Your protein FASTA file. For proteins from a single species you only need
   the corresponding numerical **NCBI TaxID**. For proteins from multiple
   species, provide a tab-separated text file with exactly two columns,
   `target_id` and `ncbi_taxid`. The IDs must match the *first word* of each
   FASTA header. If every FASTA header already contains a TAB followed by
   an NCBI TaxID, no separate taxonomy mapping is required.
3. A GO ontology in **uncompressed OWL** format, used for both releases.
4. For **each** release (earlier START and later END): Swiss-Prot and TrEMBL
   UniProt files (`.dat` or `.dat.gz`), a GOA GAF annotation file (`.gaf` or
   `.gaf.gz`), and one directory containing all four NCBI taxonomy files
   (`nodes.dmp`, `names.dmp`, `merged.dmp`, `delnodes.dmp`).
5. Meaningful labels for the two releases and their taxonomy snapshots.
   The labels document your choice; PROGENY does not independently verify
   that a downloaded file really belongs to the stated historical release.

**The wizard does not download data.** You must select legitimate datasets
and keep their sources and licenses. It does not duplicate huge UniProt DAT
sources. For compressed GOA it creates a separate decompressed copy in your
study directory (plan disk capacity accordingly).

## Two commands

From inside your cloned PROGENY directory, run:

```bash
bash SETUP_PROGENY.sh
```

Follow the on-screen questions. The wizard explains each required file and
lets you choose the scientifically consequential policies, including:

- EXACT donor policy: conservative strict, or audited same-species EXACT.
- Partial sequences: `report_only` or `allow`.
- Documentarily supported fragments: `report_only` or `allow`.
- Experimental evidence profile: an **explicitly accepted** PROGENY legacy
  classification reference snapshot (not an official ECO categorization).

The reference evidence registry and its SCORE/NON_SCORE/EXCLUDED classifications
are supplied in `config/stage08_evidence_registry.example.json` and
`config/stage08_evidence_classes_v2.example.json`. Users should assess whether
they fit their study. The wizard does **not** silently choose a GO evidence
classification.

When it reports `PROGENY_SETUP=READY`, **the computation has not started**.
Open `your-study-dataset/HOW_TO_RUN_PROGENY.txt`. It contains the exact paths
and ready-to-copy commands for the same prepared study:

```bash
bash /path/to/your-study-dataset/START_PROGENY.sh        # foreground
bash /path/to/your-study-dataset/RUN_PROGENY_TMUX.sh     # SSH / tmux
bash /path/to/your-study-dataset/RUN_PROGENY_NOHUP.sh    # background
```

For `tmux`, use the displayed `tmux attach -t ...` command to reconnect while
running; for `nohup`, use the printed persistent log and PID file. `tmux` and
`nohup` must be installed on the host if you select those options.

For HPC systems, select **SLURM** in the wizard. It asks for **memory (GiB)**,
**maximum runtime**, and optional **partition** and **account**, then generates
`SUBMIT_PROGENY.sbatch` and shows the exact `sbatch --output=...` command.
It does not submit anything. The resulting SLURM job is ONE allocation on ONE
node: the requested CPU cores and RAM are shared by the Snakemake controller
and its local jobs. It does NOT dispatch each Snakemake rule independently
across the cluster. Code, Pixi environment, binaries, data and run folders
must all be visible from the allocated compute node. Check cluster limits and
queue policies before submitting.

**Choose ONE launch method per study.** Never run `tmux`, `nohup` and `sbatch`
for the same run simultaneously. The workflow uses its own new run directory,
not a previous PROGENY/ProBE run. If it fails, inspect the log before resuming.
Scientific policy, fingerprints and input paths are unchanged by the chosen
launch method; the wizard does not require users to write JSON or SBATCH files.

## What PROGENY creates

The wizard generates a **new dataset directory** and a separate **new run
directory** outside the checkout. It refuses to overwrite either one.
It imports and audits Stage 00 targets, validates the existing file paths,
decompresses gzip GOA when needed, pins the ontology SHA-256, validates the
reference evidence classes, resolves the exact local native binaries, computes
SHA-256 of the input files and source code, constructs a complete scientific
identity inventory, generates `fresh-spec.json`, and calls the existing
canonical fresh preparator. All preparation files are retained for audit.

**Fail closed:** if any targets are rejected for unknown NCBI TaxID or short
sequence, preparation stops and points to `targets.rejected.tsv`. Exactly
identical duplicate FASTA records are recorded and deduplicated by Stage 00.
It will not quietly discard nonduplicate target records.

The source inputs remain in their original folders and are never modified.
The wizard requires new output directories and physical (non-symlinked) paths.
It never runs `git commit`, `git push`, or an unrelated existing workflow.

## After successful execution: find your benchmark

The generated `START_PROGENY.sh` runs the complete scientific DAG and,
**only after successful Snakemake completion**, invokes the independent
scientific collector. The results are at:

```text
YOUR-RUN/results/benchmark/
  ground_truth_targets.fasta
  benchmark_terms.tsv
  target_aspects.tsv
  target_cohorts.tsv
  species_statistics.tsv
  statistics.json
  report.html
  EVALUATION_LEGEND.md
  manifest.json
```

Open `report.html` offline to view the overview and follow the links to the
machine-readable tables. `ground_truth_targets.fasta` has the *full original*
user FASTA headers, and the TSV annotations use only the *first token* before
space/TAB as their protein ID. An input such as `>sp P02397 description` has
ID `sp`, not `P02397`. Different proteins must not share this first token.
The normalized FASTA under `DATASET/targets/targets.fasta` correctly retains
internal `T000...` IDs and is not the file for predictor submission.

`benchmark_terms.tsv` includes all propagated EVAL/SKIP/NEUTRAL for eligible
(target, aspect) pairs. The first class is scored positive truth; the latter
two are masks, not biological negatives. A protein may be evaluable in only
one GO aspect. Species are grouped by the *target's* resolved species TaxID.

Current NK/LK/PK cohorts remain `UNCLASSIFIED` pending a separately audited
START experimental annotation classifier. The collector creates ground truth
and a report, **not** predictor Fmax/Smin scores. For details see
[`PROGENY_POSTRUN_PUBLISHER_USER_GUIDE.md`](PROGENY_POSTRUN_PUBLISHER_USER_GUIDE.md).

If the canonical controller was used without `START_PROGENY.sh`, invoke the
same independent post-run publisher after scientific certificate PASS:

```bash
pixi run python scripts/installation/publish_progeny_scientific_results.py \
  --dataset /absolute/path/to/study-dataset \
  --run /absolute/path/to/study-run
```

The collector verifies and reuses an existing publication only when its
recorded input/output checksums are unchanged. It never reruns the scientific
DAG and never overwrites canonical inputs or scientific outputs.

## Limits and scientific interpretation

- A successful wizard is a *validated preparation*, not evidence that the
  user's downloaded input releases and chosen policy have been externally
  certified. GOA and UniProt consistency is validated by subsequent stages.
- Real datasets can be very large; SHA-256 hashing of all biological inputs
  may take time. This ensures the scientific identity depends on actual source
  bytes rather than a made-up run identifier.
- The wizard validates the reference V2 evidence class profile, not an
  arbitrary researcher's custom evidence classifications. Advanced users
  may still use `init_progeny_dataset.py bind` with an independently reviewed
  complete specification for other validated policies.
- The first alpha wizard runs on Linux. Other systems require validated
  native packaging before this can be claimed portable.
- For a study with changing policies, create a *new* study and run; do not
  modify an existing prepared scientific identity.

The technical reference is `docs/PROGENY_EXTERNAL_INPUT_LAYOUT.md`.
