# PROGENY knowledge cohorts and evaluator filters v2

Knowledge classes are derived from positive SCORE evidence in the certified
M10C START provenance database. M10C contains assertions attributed to each
target through the accepted donor links recorded by the certified M8 lineage.
The donor accession is provenance metadata; it is not required to equal the
target's external FASTA identifier. The cohort publication remains separate
from the immutable benchmark and does not alter its receipts or information
accretion table.

## Classification rule

Classification is at the `(target, aspect)` level. For each target, the
publisher gathers positive START assertions for all three aspects by the
internal target ID. It keeps only the configured SCORE evidence codes:
`EXP,HDA,HEP,HGI,HMP,HTP,IDA,IEP,IGI,IMP,IPI`.

- `PK`: at least one accepted positive START SCORE assertion is in the
  evaluated aspect.
- `LK`: there is no accepted positive START SCORE assertion in the evaluated
  aspect, but there is one in another aspect.
- `NK`: there is no accepted positive START SCORE assertion in any aspect.

Thus an IEA-only START annotation does not establish experimentally known
status. If that GO term gains SCORE evidence in END, its term-level temporal
event may be `CONFIRMATION`; the target class still depends only on all START
SCORE evidence. For example, such a target is NK if it has no START SCORE in
any aspect, LK for an aspect with no START SCORE if it has SCORE evidence in a
different aspect, or PK if it has another START SCORE in the evaluated aspect.
END evidence does not assign or change a class.

`NOT` assertions are excluded. The class audit uses each direct source GO
assertion from accepted donors, without GO closure. A replaced GO identifier
is retained only when the pinned ontology resolves it to a usable term in the
same aspect; cross-aspect replacements, unresolved terms and unsupported terms
are excluded and listed in the audit. These cohorts implement the documented
PROGENY START policy; they do not certify the separate documentary look-ahead
audit.

One protein can have different classes for MF, BP and CC. Counts are reported
as target-aspect pairs, not unique proteins. A v1 cohort publication used an
incorrect exact-accession restriction and is not accepted by the v2 loader;
republish it using this version before applying cohort filters.

## Publish the cohort table once

Run from the repository root. Keep the output outside the source checkout,
dataset and run directories:

```bash
cd /data/PROGENY/PROGENY-ia-roaring-staging
mkdir -p /absolute/path/outside-run
pixi run python scripts/evaluation/publish_start_knowledge_cohorts.py \
  --dataset /absolute/path/to/cafa5-141813-dataset \
  --run /absolute/path/to/cafa5-141813-run \
  --ontology /absolute/path/to/pinned/go.owl \
  --benchmark-sha256 9cf52e251e550cf098ba411fcc197401b1161310fa3f0ddbb6ec031af2c1a70a \
  --output-dir /absolute/path/outside-run/cafa5-start-knowledge-cohorts-v2
```

The publisher verifies the benchmark certificate and M10C manifest/database
checksums, then queries positive START SCORE assertions using the certified
internal target ID. Donor accessions are preserved in the audit, including
when they differ from the target's external identifier. It checks each source
GO against the pinned ontology and publishes:

- `knowledge_cohorts.tsv`: one row per eligible target-aspect pair, with the
  original FASTA ID, internal provenance ID, species TaxID, aspect, class and
  the aspects with accepted START SCORE evidence.
- `direct_start_go_resolution_audit.tsv`: one auditable row per selected
  target-attributed START SCORE assertion, including donor, GO disposition,
  release and provenance identifiers.
- `manifest.json`: benchmark, ontology, temporal and M10C identities, policy,
  class counts, evidence counts and artifact hashes. Its schema is
  `progeny-start-knowledge-cohorts-v2`.

## Evaluate methods with filters

The cohort directory is a required input, even for `--knowledge all`, so each
exported prediction row carries its class label. Each run must name at least
one aspect. Use the CAFA names (`MF`, `BP`, `CC`) or PROGENY codes (`F`, `P`,
`C`). The evaluator creates separate outputs per aspect and never pools
aspects.

```bash
cd /data/PROGENY/PROGENY-ia-roaring-staging
mkdir -p /absolute/path/outside-run
pixi run python scripts/evaluation/compare_predictions.py \
  --dataset /absolute/path/to/cafa5-141813-dataset \
  --run /absolute/path/to/cafa5-141813-run \
  --ontology /absolute/path/to/pinned/go.owl \
  --benchmark-sha256 9cf52e251e550cf098ba411fcc197401b1161310fa3f0ddbb6ec031af2c1a70a \
  --ia-table /absolute/path/to/ia/information_accretion.tsv \
  --ia-manifest /absolute/path/to/ia/manifest.json \
  --cohorts /absolute/path/to/cafa5-start-knowledge-cohorts-v2 \
  --method method_a=/absolute/path/to/method_a.tsv \
  --method method_b=/absolute/path/to/method_b.tsv \
  --aspect MF --aspect BP --aspect CC \
  --knowledge NK,LK \
  --taxid 9606,10090 \
  --output-dir /absolute/path/outside-run/cafa5-evaluation-nk-lk
```

Omit `--knowledge` to use all classes. Set `--knowledge PK` or a comma list
such as `NK,LK`. Omit `--taxid` or use `--taxid all` for all species. Multiple
TaxIDs can be given in one comma-separated argument or through repeated
`--taxid` options.

The denominator is filtered by aspect, class and TaxID before metric
calculation. Eligible proteins with no predictions remain in that denominator;
missing predictions are not treated as biological negatives. Predictions are
canonicalized and propagated first, then filtered by eligible target-aspect
and the benchmark SKIP/NEUTRAL masks.

Each method's `filtered_predictions_<method>.tsv` contains propagated,
scorable prediction rows with `method_id`, `protein_id`, `go_term`, `score`,
`aspect`, `knowledge_status` and `taxid`. `curves.tsv` contains one row per
method, aspect and threshold, including unweighted and IA-weighted metrics,
RU, MI and Smin. `plots/` contains comparative threshold curves and a separate
precision-recall plot per aspect. The tables and SVG source files can be reused
for custom plots and tables. The run summary uses schema
`progeny-multi-method-evaluation-v2` and records the filters and selected
target-aspect counts.

Information Accretion is computed separately once for a fixed START GAF,
ontology and policy. Adding methods or changing cohort filters does not require
recomputing IA.
