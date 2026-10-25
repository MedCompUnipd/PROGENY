# PROGENY final scientific publication: implementation and review contract

**Status:** validated PR #1 review candidate, based on
canonical Alpha 2 `6d516425f2f83caf04c359d97ea99d4b64976ea6`.
Verified on the 2026-10-25 reference CAFA5 scientific run. This increment
changes neither Stage 00--Temporal, nor the 16 canonical receipts, nor the
scientific policies that produced them. The collector is committed to a
review branch; merging into GitHub `main` requires the final PR review.

## Entry point and trigger

`pixi run python scripts/installation/publish_progeny_scientific_results.py
--dataset DATASET --run RUN` verifies an existing 16-node scientific PASS and
publishes one user-facing directory under `RUN/results/benchmark/`.

The Guided Setup `START_PROGENY.sh` generator already invokes an exporter after
successful Snakemake. Replace only the generated command's script target with
the new publisher; **do not introduce a new scientific Snakemake rule or a
second export invocation**. For controller-only `first`/`resume` runs, invoke
this independent post-run publisher after the controller has verified PASS;
the canonical controller's own completed workflow is not changed here.

## Directories and files

- `RUN/canonical/v2-policy-*/temporal/`: immutable canonical GO publication;
  original benchmark terms may use optional source accession identifiers.
- `DATASET/targets/targets.fasta`: normalized FASTA with internal `T000...`
  IDs, NOT the user output FASTA.
- `DATASET/identity/original_headers.tsv`: SHA-locked source header registry.
- `RUN/results/benchmark/ground_truth_targets.fasta`: only original targets
  with >=1 EVAL; exact *full* original FASTA headers restored; sequence hashes
  checked against the source-identity ledger.
- `RUN/results/benchmark/benchmark_terms.tsv`: original user IDs, GO aspect,
  term and `EVAL`, `SKIP`, `NEUTRAL` (including propagated ancestors) for
  eligible target-aspects. Convenience `skip_terms.tsv` and `neutral_terms.tsv`
  preserve the corresponding masks without changing their semantics.
- `target_aspects.tsv`, `term_audit.tsv`, `temporal_events.tsv`, and
  `negative_terms.tsv`: original IDs, original scientific states and audit.
- `target_identity_map.tsv`: all accepted original IDs, original header,
  internal target ID, original taxid, resolved species TaxID and sequence hash.
  `non_evaluable_targets.tsv` lists those without EVAL in any GO aspect.
- `target_cohorts.tsv`: eligible `(user_ID, aspect)` records with species,
  per-aspect masks, NOVEL/CONFIRMATION, direct-END event counts, START evidence
  flags and *explicit* `UNCLASSIFIED` knowledge class.
- `aspect_statistics.tsv`: MF/BP/CC, status counts, events, direct END EVAL.
- `species_statistics.tsv`: `species_taxid` x `aspect`, input and evaluable
  target counts, status/event counts and explicit knowledge-class status.
- `go_frequency.tsv`: target-GO association frequency per aspect/status.
- `evidence_by_release.tsv`: verified M8 START/END evidence code, polarity,
  source-row and association-link inventories. The M8 aggregate manifests are
  read but not treated as interchangeable with the target-specific cohort.
- `statistics.json`: overview, per-aspect summaries, pipeline Stage07/M8/M10c
  report summaries when published, provenance pointers and limitations.
- `EVALUATION_LEGEND.md`, `README.md`, `report.html`: offline user guidance.
- `manifest.json`: publication version, status, full upstream input and
  output SHA-256/byte ledgers, including the pinned completion certificate.

The output is published by one atomic directory rename after *all* checks,
statistics, sequence verifications and file hashes pass. An existing final
publication is verified and reused only when all sources and outputs still
match their recorded checksums. No output is silently overwritten.

## Input-identifier contract

The first whitespace-delimited token following `>` is the user ID.
For example, `>Q9CQV8\t10090` gives `Q9CQV8`, whereas
`>sp P02397 12345` gives `sp` and will collide with other records beginning
`>sp `. The original full header is stored without interpretation in the
FASTA and identity map, but the first token alone joins all annotation files.
User IDs must be unique across distinct accepted input proteins. Do not
interpret free-text fields as optional UniProt accession automatically.

## Metric semantics

For each eligible `(target, aspect)`, the user-facing `benchmark_terms.tsv`
forms one ground truth plus two masks:

- `EVAL`: positive truth; prediction above threshold TP, missing FN.
- `SKIP`: known/non-scored GO support; excluded from TP/FP/FN/TN.
- `NEUTRAL`: conflict/temporal ambiguity; excluded from TP/FP/FN/TN.
- A valid predicted GO not in those sets is an operational FP only for
  eligible target-aspects after GO prediction propagation and mask application.
- `NOT` source assertions are not automatically biological true negatives;
  missing GO annotations are not evidence of absence.

Correct evaluator order: normalize scores, maximum over duplicate predictions,
GO propagation over frozen approved relations, exclude roots/out-of-universe,
apply per-target masks, compute TP/FP/FN. Propagation must *not* stop on a
masked ancestor. Report per MF/BP/CC and per independently certified cohort;
full evaluation includes eligible targets without predictions in recall.
Smin requires separate certified IA weights; do not infer IA from the EVAL
frequencies or equate this collector with predictor metrics.

## Knowledge classes

This increment **does not claim CAFA NK/LK/PK**. The existing Stage07/M8/M10c
annotation transfers do not, by themselves, prove which experimental functions
were attributed directly to each original target at START. Set every
knowledge class to `UNCLASSIFIED` and publish useful START score flags
separately. NK/LK/PK may be filled only by a subsequent certified, direct
START source-annotation audit and versioned classifier. No hidden mapping
`NOVEL -> NK` or `CONFIRMATION -> PK` is permitted. Until such certification,
an evaluator must *not* report NK/LK/PK scores from this output.

## Validation gates

1. Canonical completion certificate: exactly 16 receipts, PASS, expected
   content identity, temporal receipt exact path and SHA-256.
2. All original header identities cross-checked with normalized Stage 00 and
   SHA-locked identity ledger; all exported sequences checked by SHA-256.
3. All temporal payloads SHA-256 checked against temporal producer manifest.
4. All user-output EVAL/SKIP/NEUTRAL total counts reconcile to producer
   counts for unaliased runs; every target-aspect reconciles individually;
   NOVEL+CONFIRMATION partition EVAL, direct END counts do not exceed EVAL.
5. Both M8 evidence inventories reconcile by role to source-row and link
   totals when the M8 summary is present.
6. No in-place source modifications; atomic new destination; on retry, validate
   both upstream inputs and all published output SHA-256.
7. Ruff check --fix, Ruff format, Ruff check, Ruff format --check, full AST
   parse, focused pytest and full repository regression on staged sources.
8. On the real CAFA5 reference, verify exactly: 141813 input, 28082 distinct
   evaluable targets, 39785 eligible aspects, 358675 EVAL, 1398082 SKIP,
   550 NEUTRAL, 202052 NOVEL, 156623 CONFIRMATION, 62380 direct END EVAL.
   Refuse to claim scientific regression PASS until actual server results
   reconcile. No Stage00--Temporal stages may be rerun as part of this check.

## Deferred work and non-goals

- Direct-target, evidence-certified NK/LK/PK classification and its scientific
  contract; preserve `UNCLASSIFIED` until proven.
- Predictor scoring Fmax/Smin/coverage and interactive cohort selector;
  this publication supplies their inputs, not a computed score.
- Full documentary look-ahead audit requiring release-per-document witness
  provenance. Current aggregate reports explicitly identify that limit.
- Changes to header parsing or Stage 00 duplicate handling; do not change
  the sealed CAFA5 dataset in a post-run publication increment.

This publication is a post-science step and does not alter the count of 16
canonical scientific publications.

## Completed reference validation (2026-10-25)

Reference identity: commit `6d516425f2f83caf04c359d97ea99d4b64976ea6`,
START `2023_01`, END `2026_03`, original CAFA5 query list of 141,813.
Certified canonical science had 16 receipts and `VERIFICATION=PASS`.
The independently published bundle at `RUN/results/benchmark/` reconciled:

| Measure | Independently verified reference value |
| --- | ---: |
| Original target IDs | 141,813 |
| Evaluable targets in FASTA | 28,082 |
| Eligible target/aspects | 39,785 |
| Propagated EVAL | 358,675 |
| Propagated SKIP | 1,398,082 |
| Propagated NEUTRAL | 550 |
| EVAL NOVEL | 202,052 |
| EVAL CONFIRMATION | 156,623 |
| Direct END EVAL events | 62,380 |
| Target species TaxIDs represented | 87 |

The bundle reported `BUNDLE_RECONCILIATION=PASS` and
`CANONICAL_FILES_UNCHANGED=YES`. The manifest digest of this specific output
was `9cf52e251e550cf098ba411fcc197401b1161310fa3f0ddbb6ec031af2c1a70a`.
That is an example of a verified **run artifact**, not a hash that should be
hardcoded in the library or expected for other studies.

Staging Ruff check/fix, format, check, format-check, AST/E501, 37 focused
tests and the complete 2026-10-25 regression passed. Full regression:
**1,932 passed, 2 skipped**. The skipped tests were a native Stage07/M8
integration fixture with an unconfigured optional DP binary and an optional
historical UniProt Python oracle. They must not be called passed tests.
No Snakemake execution occurred during the reference post-run publication.

The full `report.html` lists the 50 largest species cohorts by evaluable
targets, while the unabridged species table contains all represented species.
The M8 evidence inventory is aggregate by release, evidence code, polarity
and ontology; it is not proof of direct target-specific experimental support.
NK/LK/PK and documentary look-ahead remain open scientific audits.
