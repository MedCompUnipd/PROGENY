# Standalone PROGENY evaluation workflow

The benchmark DAG produces and certifies the benchmark. Information
Accretion (IA) and prediction evaluation run separately, outside that DAG.
They read the published benchmark and never modify its canonical artifacts.

## 1. Compute IA once

IA is specific to the START GOA corpus, its release, the pinned ontology and
the recorded IA policy. Compute it once before evaluating prediction methods.
Keep its output directory and manifest as immutable inputs to later runs.

Build the optional native Roaring executable in a new external build
directory:

```bash
pixi install --locked
pixi run python scripts/evaluation/build_information_accretion_roaring.py \
  --build-dir /absolute/path/to/external/ia-build \
  --jobs 2
```

Run the full calculation with the START GOA file, pinned ontology and expected
SHA-256 digests:

```bash
pixi run python scripts/evaluation/compute_information_accretion_roaring.py \
  --gaf /absolute/path/to/START/goa.gaf \
  --gaf-sha256 EXPECTED_START_GAF_SHA256 \
  --source-role START \
  --release-id START_RELEASE \
  --ontology /absolute/path/to/pinned/go.owl \
  --ontology-sha256 EXPECTED_PINNED_ONTOLOGY_SHA256 \
  --native-binary /absolute/path/to/external/ia-build/progeny-ia-roaring-v1 \
  --scratch-root /absolute/path/to/new/external/ia-scratch \
  --output-dir /absolute/path/to/new/external/ia-publication \
  --threads 8 \
  --max-address-space-gib 128
```

Use new scratch and output directories outside the source checkout, dataset,
run and input directories. The output directory must be virgin. Preserve the
IA table, manifest and checksums. Adding prediction methods does not require
recomputing IA. Recompute only if the START corpus, release, pinned ontology
or IA policy changes.

The Roaring backend is experimental and separately built. Its provenance is
recorded in the IA manifest. Full-corpus equivalence with the SQLite reference
is a separate validation result.

## 2. Prediction file contract

Each method supplies one UTF-8 TSV with exactly this header:

    query_id    go_id    score

The header uses literal tab characters between columns. Each following row
contains one predicted target/GO score:

- `query_id` is the first token of the original header in
  `ground_truth_targets.fasta`. Do not substitute an internal `T000...` ID.
- `go_id` is `GO:` followed by seven digits. The evaluator resolves IDs only
  with the benchmark's pinned ontology. Unambiguous recognized aliases and
  replacements can be mapped; unresolved or ambiguous IDs are excluded and
  audited.
- `score` is finite and in `[0, 1]`; larger values mean greater confidence.
  Scores need not be calibrated across methods.
- Do not submit NOT rows, EVAL labels, SKIP/NEUTRAL masks or other ground
  truth. Missing predictions stay missing and are not biological negatives.

The evaluator merges duplicate canonical target/GO pairs by maximum score,
propagates scores through the pinned `is_a` and `part_of` graph, then applies
benchmark eligibility and the per-target/aspect SKIP and NEUTRAL masks.

## 3. Evaluate or add methods

Run the comparison CLI with the unchanged IA publication. Repeat `--method`
for each method, use distinct method IDs and choose a new output directory:

    pixi run python scripts/evaluation/compare_predictions.py \
      --dataset /absolute/path/to/certified-dataset \
      --run /absolute/path/to/certified-run \
      --ontology /absolute/path/to/pinned/go.owl \
      --benchmark-sha256 EXPECTED_BENCHMARK_MANIFEST_SHA256 \
      --ia-table /absolute/path/to/ia-publication/information_accretion.tsv \
      --ia-manifest /absolute/path/to/ia-publication/manifest.json \
      --method method_a=/absolute/path/to/method_a.tsv \
      --method method_b=/absolute/path/to/method_b.tsv \
      --threshold-step 0.01 \
      --output-dir /absolute/path/to/new/evaluation-output

The output directory must not exist and must be outside the source checkout,
dataset and run. To add methods, rerun the CLI with all methods to compare,
the same benchmark and IA files, and a new output directory. Do not rerun IA.

Use repeated `--aspect F`, `--aspect P` or `--aspect C` to restrict aspects.
Use repeated `--taxid TAXID` to select species. By default all aspects and
represented species are included. Curves use the shared threshold grid from
`step` to below 1, with `score >= threshold`.

## 4. Tables and plot source

The comparison output includes:

- `curves.tsv`: numeric source table with method ID, aspect, threshold,
  unweighted and IA-weighted metrics, RU, MI and Smin. Use it to redraw plots.
- `summary.json`: best grid Fmax, wFmax and Smin and their thresholds, method
  summaries, input identities, checksums and artifact inventory.
- `go_resolution_audit_<method>.jsonl`: audit of submitted GO IDs remapped
  or excluded for each method.
- `plots/*.svg`: one metric plot per aspect, with methods overlaid.

SVGs are derived outputs. The renderer is
`src/progeny/prediction_plotting.py`. Other plotting tools can consume
`curves.tsv` and use `method_id` as the series label.
