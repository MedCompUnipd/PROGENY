# Prediction infrastructure, milestone 1

This milestone validates evaluator inputs and prepares scores in memory. It
does not compute precision, recall, coverage, Fmax, Smin or predictor rankings.
No classifier or documentary provenance audit is introduced. Existing
scientific schemas and publications remain authoritative.

## Prediction interchange contract

Supply UTF-8 TSV with exactly this header, in this order:

```text
query_id	go_id	score
```

- `query_id` must match the original FASTA first token, exactly. No accession
  substitution, internal-ID conversion or whitespace normalization is applied.
  Only targets in the evaluable FASTA are admitted. Other input universes need
  an explicit adapter before this validator.
- `go_id` has syntax `GO:` followed by seven digits. Resolve against the
  checksum-pinned ontology using the existing PROGENY resolver. Unambiguous
  alternate IDs and replacements are accepted and counted. Syntactically valid
  unknown, ambiguous and obsolete/deprecated IDs without an unambiguous active
  mapping are excluded and audited; other valid rows continue to evaluation.
  A `consider` suggestion alone is never used as a replacement. No mapping is
  guessed from term labels, sequence similarity or another ontology release.
- `score` must be finite and within [0, 1], with higher values indicating
  greater confidence. Probability calibration is not assumed. Explicit zero
  is preserved; no score is synthesized for an absent prediction.
- Duplicate canonical target/GO pairs take the maximum score. Duplicate rows
  and remapped rows are counted separately. The TSV must contain no extra
  columns, comment records or blank records. CRLF and numeric scientific
  notation are accepted. A header-only file is a valid empty submission.

Keep original method outputs and record method version, parameters, training
data and resource versions separately. This validator performs no automatic
score rescaling and no method-specific format guessing.

## Certified benchmark binding

The CLI requires explicit dataset, run, ontology path and expected benchmark
manifest SHA-256. It reads the existing publication under
`RUN/results/benchmark`; it never invokes the publisher or Snakemake.

It checks the exact benchmark inventory and all recorded input/output sizes
and checksums, all sixteen certified receipts, the identity ledger, original
FASTA headers and sequences, eligible target/aspect pairs, disjoint term
statuses, convenience masks and overview cardinalities. It binds the dataset,
Temporal and M10C paths to the certificate and publication.

Supported source schemas are the scientific benchmark publication v1,
Temporal eval/skip/neutral v3, and compact M10C interpretation v1. Other
schemas are rejected; no migration is attempted. Temporal class, registry and
policy identities are recorded, without reclassifying annotations.

The supplied ontology bytes must match both Temporal and M10C digests. The
loader and `GoClosureIndex.from_gene_ontology` are reused from PROGENY. Graph
node/edge counts must match M10C. This preserves same-aspect `is_a`/`part_of`
inheritance, including M10C's explicit exclusion of cross-aspect links.
`regulates` and other navigable relations do not propagate prediction scores.
No ontology download or latest-release substitution is performed.
The closure's cross-aspect counter excludes edges already removed by the OWL
relation policy; a zero counter does not establish their absence in raw OWL.

## Preparation order and population

1. Validate original target IDs, GO IDs and scores.
2. Resolve GO IDs against the pinned ontology, exclude and audit unresolvable
   terms, then merge duplicate canonical pairs by maximum score.
3. Propagate maximum scores over the certified M10C graph, including self.
4. Exclude ontology roots and target/aspect pairs without EVAL eligibility.
5. Exclude SKIP and NEUTRAL terms for their own target/aspect.

A masked term never interrupts propagation to further ancestors. NOT records
are not used to construct biological negatives. Terms outside EVAL and masks
remain scorable predictions for the future evaluator; this milestone does
not count them as false positives or calculate metrics.

Predictors may submit only their most specific terms: ancestor propagation is
always performed here. Already-propagated submissions are also accepted; max
aggregation and graph closure make score preparation idempotent.

A predictor's ontology may differ from the benchmark ontology. Only mappings
available in the pinned benchmark ontology are used. A newer term absent
there, with no recognized alternate ID, is excluded. The predictor's ontology
cannot replace the benchmark graph or supply unverified backward mappings.
For every remapped or excluded input row, the audit records the original ID,
canonical ID (if available), score, ontology status, mapping candidates and
action. `input_row` is the one-based data-row index after the TSV header.
Active unchanged rows are counted but not repeated in this resolution audit.

Excluded GO terms do not enter prediction propagation, TP or operational FP
counts. Exclusion never shrinks the eligible population or removes truth
terms: unrecovered EVAL terms remain missing predictions for the future full
evaluation. Invalid target IDs, malformed GO IDs and invalid scores still
fail input validation; they are distinct from ontology-version differences.

The benchmark object retains the complete eligible population and truth even
for methods with no predictions. Consequently, a future evaluator can use
full recall denominators without reconstructing them from method coverage.
It must define threshold, precision averaging, coverage and partial evaluation
conventions explicitly before publishing metrics.

## Read-only CLI

```bash
pixi run --locked python scripts/evaluation/validate_prediction_inputs.py \
  --dataset /absolute/study-dataset \
  --run /absolute/study-run \
  --ontology /absolute/pinned-go.owl \
  --benchmark-sha256 EXPECTED_64_CHARACTER_DIGEST
```

Add `--predictions /absolute/method.tsv` to validate and prepare a submission.
The command prints a JSON audit to stdout. It creates no result directory and
does not serialize prepared scores. The Python API exposes prepared scores
for the next evaluator milestone. Any error exits without a validated audit.
With predictions, the JSON includes resolution counters and the complete
`go_resolution_audit` of remapped and excluded rows, preserving submission order.

The audit reports `metrics_status=NOT_COMPUTED`. Input validation is not a
scientific validation of a predictor. Smin requires an independently certified
information-accretion table; the existing namespace-relative information
content helper is not substituted for information accretion.

## Validation and release boundary

The tests include hand-derived score oracles and a synthetic OWL/collector
integration, including a `part_of` chain crossing both masks, an ignored
cross-aspect edge, an excluded `regulates` edge, aliases and replacements.
Negative cases include mismatched digests, wrong projections, bad receipts,
unsupported schemas, foreign datasets, incomplete masks and conflicting
statuses even after test checksums have been deliberately reconciled.

All fixtures use temporary directories. No test needs a production dataset,
production ontology or real method predictions. Before release, execute the
repository's complete suite and locked native build, as required by AGENTS.md.
