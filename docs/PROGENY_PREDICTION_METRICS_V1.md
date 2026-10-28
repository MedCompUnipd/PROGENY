# Prediction metrics, milestone 2

This milestone adds a separate evaluator to the validated M1 input reader and
prediction preparation. No M1 source, canonical stage, benchmark term, mask,
cohort assignment or ontology is changed. The CLI evaluates one method and
prints JSON to stdout; it creates no directories or published result bundle.

## Scientific input population

Evaluate only eligible `(original_query_id, aspect)` pairs with nonempty EVAL
truth. The truth includes propagated terms. Prediction scores first pass
through M1: pinned GO resolution, maximum on duplicates, maximum propagation,
root exclusion, target/aspect eligibility and per-target SKIP/NEUTRAL masks.
Unknown or unresolvable GO rows remain excluded and audited by M1. A masked
term never stops propagation to another ancestor.

An unmasked scorable prediction outside EVAL is an operational benchmark FP.
Missing GO assertions and NOT records do not establish biological negatives.
Neither target eligibility nor knowledge classification is inferred from a
method's predictions, homolog evidence or NOVEL/CONFIRMATION term events.

Filter by original target resolved species TaxID, not donor TaxID. Multiple
TaxIDs mean a union. Apply the filter to both predictions and truth population.
The filter also changes denominators. F/P/C are evaluated separately; no pooled
ontology score or method ranking is generated. Repeated `--aspect` values are
rejected; aspect output order is F/P/C. Repeated TaxIDs are deduplicated.

## Metric definitions at one threshold

For one aspect and selected species population, let N be the number of eligible
proteins. Let T_i be the nonempty EVAL term set for protein i. Let P_i(tau) be
its explicitly present, propagated, unmasked predictions with score >= tau.
Absent predictions are never represented by numerical zero. Define:

- TP_i = size(P_i intersection T_i).
- FP_i = size(P_i minus T_i), operational only.
- FN_i = size(T_i minus P_i).
- n(tau) = number of proteins whose P_i(tau) is nonempty.
- Precision = sum_i(TP_i / size(P_i)) / n, over nonempty P_i.
- Full recall = sum_i(TP_i / size(T_i)) / N, over all eligible proteins.
- Coverage(tau) = n(tau) / N.
- Full F1 = 2 * precision * full_recall / (precision + full_recall).

These are macro averages per protein. They are neither pooled TP/FP ratios
nor averages of per-protein F1 values. Total TP, operational FP and FN are
reported only as count diagnostics, without defining biological TN.

As a secondary, explicitly named normalization, `recall_covered` divides the
same sum of per-protein recalls by n(tau), rather than N. Its F1 and Fmax appear
under `covered_normalization_secondary`. This population varies with tau.
It must not replace full evaluation in primary reporting or ranking.

`coverage_any_score` counts eligible proteins with at least one scorable
prediction at any explicitly supplied score, including zero. It is distinct
from coverage at the Fmax threshold and from raw submission coverage before
GO exclusions and masks.

## Thresholds, zeros and Fmax

Default `exact_score_sweep` uses every distinct scorable score in the selected
method/aspect/TaxID population, plus 0 and 1. Every change in a prediction set
is therefore evaluated. The threshold is global within that population, not
optimized separately for each protein. Equal-score terms activate together.
Fmax is the maximum of the harmonic mean of the macro precision and recall
at a common threshold, not the harmonic mean of independently maximized P/R.

An explicit zero-valued prediction is present at tau=0. A missing prediction
stays absent at tau=0. Terms present in another aspect or outside the selected
species population do not contribute thresholds to the exact aspect sweep.

Optional `--threshold-step` creates an explicit decimal grid containing 0, 1
and multiples of the requested step below 1. Step must be within [0.0001, 1].
The report records the step and complete grid. This grid may miss a maximum
between grid points; it is not labelled an exact Fmax. This PROGENY grid's
endpoints must not be confused with another evaluator's default grid.

If multiple examined points have exactly equal computed F1, select the highest
threshold. The selected threshold and its P/R/coverage are reported together.
Scores and metrics use Python floating point, deterministic term/query order
and compensated macro sums. Tests compare against an independent rational
oracle within 1e-12; arbitrary near-equalities are not rounded into ties.

The Fmax threshold is an evaluation statistic. Do not use held-out benchmark
truth to train a method, calibrate scores or select a prospective operating
threshold for an independent deployment claim.

## Empty cases

- N > 0 with no scorable predictions: status `NO_SCORABLE_PREDICTIONS`, zero
  precision/recall/F1/Fmax/coverage by explicit convention, all EVAL terms FN.
  In the default exact sweep, the tied best threshold is 1.
- N > 0 but n(tau)=0: zero P/R/F1/coverage at that threshold by convention.
- N = 0: status `NO_ELIGIBLE_TARGETS`, null metrics and no curve. No zero-valued
  performance is attributed to an empty population.
- A requested TaxID absent from the evaluable FASTA is listed explicitly and
  may produce an empty population. This does not certify its absence from the
  original full input dataset or from biology.

## JSON report and CLI

```bash
pixi run --locked python scripts/evaluation/evaluate_predictions.py \
  --dataset /absolute/study-dataset \
  --run /absolute/study-run \
  --ontology /absolute/pinned-go.owl \
  --benchmark-sha256 EXPECTED_64_CHARACTER_DIGEST \
  --predictions /absolute/method.tsv \
  --method-id METHOD_VERSION
```

Optional flags: repeated `--aspect F|P|C`, repeated `--taxid NCBI_SPECIES_TAXID`,
`--threshold-step 0.01`, `--include-curves`, and `--method-metadata method.json`.
Method metadata is recorded and hashed as caller-declared information. It is
not a certified audit of training dates, resource leakage or scientific cohorts.

The report preserves benchmark/ontology/Temporal/M10C/policy identities, pending
NK/LK/PK and look-ahead status, prediction SHA-256, all M1 remapping/exclusion
audit rows, Python/RDFlib versions, source commit (when available) and hashes
of the evaluator, M1 preparation and relevant GO source modules. Preparation
counts describe the full submitted evaluable FASTA before metric filters;
metric counts describe the selected population. Both scopes are explicit.

Summary JSON omits curve rows by default. `--include-curves` includes every
examined threshold; it does not change metric computation. If desired, capture
stdout in a fresh external result file. This milestone does not implement
immutable result publication, multi-method ranking or a user interface.

Smin remains `NOT_COMPUTED_PENDING_CERTIFIED_INFORMATION_ACCRETION`. No weights
are inferred from the test set, GO frequencies or ordinary information content.
No NK/LK/PK filter is available before that independent audit is certified.

## Reference semantics and validation

The macro precision/recall definitions were checked against the primary
CAFA-evaluator implementation (BioComputingUP/CAFA-evaluator, tree
`d09ba823b15d4e8a57cd1311c73e5fec3ef1c035`, evaluation.py). This implementation
uses its own sparse score sweep and preserves PROGENY's certified masks and
ontology universe. It does not assert equivalence to an official CAFA ranking.

Tests include hand-derived oracles distinguishing macro from micro and
per-protein F1; global thresholds; ties; exact versus grid optima; absent versus
explicit zero; empty populations; TaxID/ontology denominators; a long numerical
sweep; deterministic randomized cases checked with exact rational arithmetic;
and end-to-end OWL/collector/CLI fixtures from M1. Real method outputs are not
required. The sparse sweep activates each selected score once after sorting;
it does not allocate a target-by-entire-GO matrix. Curves still consume memory
proportional to the number of examined thresholds.
