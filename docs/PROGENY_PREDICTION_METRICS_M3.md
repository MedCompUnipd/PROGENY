# PROGENY weighted metrics, Information Accretion and comparisons

This additive milestone consumes the M1 validated benchmark inputs and M2
prepared predictions. It does not alter canonical CAFA5 files, M1 masks, the
ontology snapshot, eligibility, or the exact-score Fmax report.

## Information Accretion corpus

The IA corpus is a caller-supplied GOA GAF snapshot explicitly labelled
`START`. For CAFA5 the source is the configured `2023_01` GOA GAF and its
expected SHA-256 is supplied on the command line. The evaluator reads the file
once, computes SHA-256 during that same scan, and rejects a mismatch before
writing an IA publication.

The parser accepts GAF 2.x rows with 17 fields. It uses UniProtKB database
object IDs as protein identities, retains all positive evidence rows including
IEA, excludes rows with the literal `NOT` qualifier, and deduplicates each
protein/canonical-GO pair. GO aliases and replacement relationships are
resolved through PROGENY's pinned ontology resolver. The GAF aspect is checked
against the namespace of the requested source GO term. A unique `replaced_by`
resolution that crosses aspects is excluded, matching the canonical GOA
normalization policy; its row count and source-to-replacement mappings are
recorded in the IA manifest. Rows with an invalid GAF aspect or a GAF aspect
that disagrees with the source term namespace are also audited and excluded,
so one anomaly does not prevent auditing the remainder of the corpus.
Unresolved inactive terms are audited and excluded. The `remapped_go_rows`
count covers accepted rows only. These policies are serialized as IA schema v3;
earlier IA schemas are not accepted by the comparison evaluator.

For each active GO term, annotations are closed upward through same-aspect
`is_a` and `part_of` edges. Let `n(v)` be the number of distinct GOA proteins
with term `v`, and `n(Pa(v))` the number annotated to every direct parent of
`v`. The add-one-smoothed weight is

`IA(v) = log2((n(Pa(v)) + 1) / (n(v) + 1))`.

The added one corresponds to a synthetic protein annotated to every active
term. For a root, IA is zero. An IA publication contains a deterministic TSV
and a JSON manifest recording the source role/release, GAF and ontology
hashes, relation and evidence policies, row audit counts and IA table hash.
The IA table covers every active term in the pinned graph, including terms
with zero START observations.

The 190 GB GOA source is processed sequentially. Deduplication and propagated
protein-term memberships use a temporary SQLite database under a caller
selected scratch root. This database is separate from the source checkout,
dataset, run and IA output directory. The benchmark EVAL labels and END GOA
are never read to compute IA.

## Weighted evaluation

Prepared scores from M1 have already been mapped to the pinned GO snapshot,
propagated, root-filtered and masked. For each aspect and threshold, weighted
precision is the macro mean over targets with positive predicted IA of
`IA(TP) / IA(predicted)`. Weighted recall is the macro mean over all eligible
targets of `IA(TP) / IA(truth)`. Weighted F1 is their harmonic mean.

Remaining uncertainty and misinformation are `RU = sum(IA(FN)) / N` and
`MI = sum(IA(FP)) / N`, where `N` is the complete eligible target population
for that aspect and selected TaxID filter. `S(tau) = hypot(RU, MI)` and Smin
is its minimum on the common CAFA threshold grid. The best-score summary
ignores grid points with no predictions, matching the CAFA evaluator's
scorable-row convention. Empty populations return null scalar metrics.

## Common threshold curves and plots

`compare_predictions.py` accepts two or more `METHOD_ID=prediction.tsv`
arguments. Every method is evaluated on the same decimal threshold grid,
defaulting to 0.01 through 0.99 with `score >= threshold`. This matches the
CAFA evaluator's fixed-grid interval `[step, 1)`; it is separate from M2's
exact distinct-score sweep. Fmax/wFmax/Smin values in this report are grid
optima and are labelled with their selected threshold.

The new, virgin output directory contains:

- `curves.tsv`: one row per method, aspect and shared threshold, with
  precision, recall, F1, coverage, weighted precision/recall/F1/coverage, RU,
  MI and S(tau).
- `summary.json`: benchmark, ontology, IA, method-input and implementation
  hashes, per-method metric summaries, output artifact checksums and plot
  inventory.
- `go_resolution_audit_<method>.jsonl`: per-method GO mapping/exclusion audit.
- `plots/`: one SVG per metric and aspect, with all methods overlaid on the
  same axes. Plots require no additional Python dependency.

Plots use caller score values on the shared numeric threshold axis. They do
not calibrate or rescale scores across methods. If methods use different score
scales, the threshold curves show that difference and should not be read as a
comparison at equivalent calibrated probabilities.

## Limitations

This milestone does not certify NK/LK/PK, documentary look-ahead, training
data leakage, or predictor metadata. It does not rank methods across aspects
or cohorts. IA values are corpus- and ontology-specific; an IA manifest with a
different ontology hash or source role is rejected. It does not replace the
exact-score Fmax report in M2 or the scientific CAFA5 publication.
