# What PROGENY users receive after a successful run

At the end of the scientific PROGENY pipeline, the final collector publishes
`RUN_ROOT/results/benchmark/` only if a certified 16-receipt `PASS` exists.
The science remains available unchanged under `RUN_ROOT/canonical/`.

**Use these paths first:**

| File | Purpose |
| --- | --- |
| `ground_truth_targets.fasta` | Full original headers and original sequences for targets with at least one EVAL |
| `benchmark_terms.tsv` | Original user ID, ontology F/P/C, GO, EVAL/SKIP/NEUTRAL for evaluable aspects |
| `target_aspects.tsv` | Which target/aspects have EVAL and how many status terms |
| `target_cohorts.tsv` | Target/aspect, species and knowledge-class status for filtering |
| `species_statistics.tsv` | Per-species, per-aspect counts and scientific events |
| `evidence_by_release.tsv` | START and END GOA evidence codes, polarities and rows/links |
| `statistics.json`, `report.html` | Machine and human-readable statistical report |
| `EVALUATION_LEGEND.md` | Definitive operational scoring semantics |
| `manifest.json` | SHA-256 of inputs and outputs; reproducibility ledger |

**FASTA identity rule:** only the substring after `>` and before the first
space or TAB is the user-facing target ID. The complete untouched original
header is preserved in the exported FASTA, but GO tables use only the ID.
For example `>P62259\t10090` has user ID `P62259`. Never supply two distinct
proteins with headers `>sp P02397 ...` and `>sp P05876 ...`: both mean ID `sp`.
You must provide unambiguous first tokens before starting a new study.
The FASTA under `DATASET/targets/targets.fasta` is *internal* and correctly
uses `T000...` IDs; that is not the file distributed to predictors.

**Proteins and GO:** A protein can belong to the benchmark for MF but not BP
or CC; never include non-evaluable aspects in metric denominators. The three
status columns are propagated GO terms for an eligible target/aspect. EVAL is
positive scoring truth; SKIP and NEUTRAL are masks and must never be counted
as biological negatives. Unlisted valid GO predictions in an eligible aspect
may be *operational* false positives, not proof of biological absence.
Prediction scores must propagate up the frozen GO graph *before* masks are
applied, or valid ancestor predictions could be lost.

**NOVEL and CONFIRMATION** are distinct reasons for EVAL term acquisition,
not categories of target knowledge. They are counted for all EVAL from
`term_audit.tsv`; separate direct-END events come from `temporal_events.tsv`.
The report must not substitute one count for the other.

**NK, LK and PK:** These are experimental START knowledge strata of the
original target (NK: no experimentally supported aspect at START; LK: other
aspect known, evaluated aspect not; PK: evaluated aspect already known).
They cannot be inferred merely from GO annotations transferred from homologs.
The initial publisher therefore labels these as `UNCLASSIFIED`; a later
certified direct-evidence classifier is needed before using NK/LK/PK metrics.

**Per-species filtering** uses the original target's resolved NCBI species
TaxID, not a donor TaxID. MF/BP/CC species counts overlap for proteins with
more than one assessed aspect. Distinguish `protein`, `protein/aspect`, and
`protein/aspect/GO` cardinalities; they are not interchangeable.

**Metrics:** The benchmark is ground truth, not predictor performance. An
independent evaluator will compute Fmax and coverage by ontology and cohort
using explicit full/partial denominators. Smin requires a separately pinned
information-accretion corpus/table and cannot use the benchmark's GO counts.

## Reference output: Alpha 2 CAFA5 (2026-10-25)

The post-run publisher was verified on the frozen 141,813-input-target study
(START `2023_01`; END `2026_03`). Its `ground_truth_targets.fasta` contains
28,082 distinct original protein IDs; `target_aspects.tsv` contains 39,785
assessable target/aspect pairs. All three propagated masks/truth states
reconcile: EVAL 358,675, SKIP 1,398,082, NEUTRAL 550.

Across those EVAL, NOVEL contributes 202,052 and CONFIRMATION 156,623.
Only 62,380 EVAL have directly reported END SCORE events on the GO term;
the others are EVAL through GO propagation, not independently observed
direct GO assertions on that same term. The study contains targets from 87
resolved species TaxIDs. These values are **specific to this reference run**,
not fixed expectations of PROGENY for arbitrary studies.

You can filter records by `query_id`, `aspect` and the target species TaxID
from `target_cohorts.tsv`. A species/aspect filter changes the metric
**denominator** as well as the input truth: keep only eligible target/aspects
in that population and then apply *their own* EVAL, SKIP and NEUTRAL masks.
Do not classify the cohort as NK/LK/PK until the separate START direct-evidence
audit is certified. Do not treat NOVEL versus CONFIRMATION as that category.

The distributed `evidence_by_release.tsv` describes M8 *aggregate* GOA
source rows and links, not experimental assertions uniquely assigned to
individual targets. Documentary look-ahead cannot be estimated from this
aggregate: the collector reports `NOT_MEASURABLE_FROM_AGGREGATES`.

## Publication and failure modes

The Guided Setup launcher invokes the publisher only after Snakemake
succeeds. Users who run the canonical controller directly should invoke:

```bash
pixi run python scripts/installation/publish_progeny_scientific_results.py \
  --dataset /absolute/path/to/study-dataset \
  --run /absolute/path/to/study-run
```

The collector needs a certified 16-receipt `PASS`. If it fails, the scientific
run remains certified; repair and rerun **only** this post-run command. A
published destination cannot be overwritten silently: all recorded source
and destination file hashes must still match. The publisher does not run
Snakemake or recompute any GO biological result.
