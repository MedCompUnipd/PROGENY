# Prepare standalone evaluation artifacts

Benchmark generation remains the canonical Snakemake workflow. Evaluation
preparation runs afterward and does not edit the benchmark publication or
rerun the DAG.

## One command after benchmark publication

From the PROGENY checkout, run:

```bash
pixi run prepare-evaluation --dataset /path/to/study-dataset \
  --run /path/to/study-run
```

The command reads START release, GOA and pinned ontology from the dataset's
`config/fresh-spec.json`. It checks the certified benchmark, publishes or
validates the START knowledge cohorts, builds or reuses the pinned Roaring
executable, and computes IA synchronously when the matching publication is
absent. It returns only after each artifact has passed its manifest and
checksum checks. It does not launch a hidden background job.

## Installer-managed artifact layout

Guided setup creates `PROGENY_SHARED` next to the dataset and run roots:

```text
<study-base>/PROGENY_SHARED/
  START/<release>/information_accretion/<start-fingerprint>/
  RUNS/<run-name>/<benchmark-manifest-sha256>/knowledge_cohorts/
  native/ia-roaring/<build-fingerprint>/
  scratch/ia-roaring/
```

The IA fingerprint includes the START release, materialized START GAF hash,
pinned ontology hash and serialized IA policy. Parameterized runs under the
same setup base reuse IA only when all those inputs match. Cohorts remain
scoped to one certified benchmark manifest. Existing canonical benchmark
files and receipts are read-only inputs to this step.

The user does not select or create these storage paths. The setup summary
records the shared root; the evaluator derives the expected IA and cohort
paths from the dataset and run. Advanced explicit IA and cohort paths remain
available for reviewed external artifacts, but default evaluation requires
the installer-managed publications and stops with a `prepare-evaluation`
instruction if they are absent or mismatched.

## Re-evaluating methods

Once preparation succeeds, methods can be added or filtered without
recomputing IA. Use `pixi run compare-predictions --help` for the evaluator
options. Supply each method as `method_id=/absolute/path/predictions.tsv`;
the prediction schema is documented in
`PROGENY_PREDICTION_INPUTS_V1.md`. The evaluator resolves the stored IA and
knowledge cohorts automatically, then emits tables and plot source SVGs into
a new output directory.

The standard software validation command is `pixi run test`. It builds all 13
locked native tools, builds the IA Roaring tool in isolated temporary space,
and enables the Roaring differential tests during the full pytest run. The
independent full-corpus IA equivalence check remains a separate scientific
validation question; SQLite is not treated as the scientific truth source.
