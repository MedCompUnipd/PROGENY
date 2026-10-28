# PROGENY knowledge cohorts and evaluator filters v1

Knowledge classes are derived from the certified M10C direct provenance for
START. The cohort publication is a separate, immutable output. It does not
change the certified benchmark, canonical receipts, or information-accretion
table.

## Classification rule

Classification is at the `(original protein accession, aspect)` level.

- `PK`: the original target has at least one positive direct START annotation
  in a SCORE evidence code for this aspect.
- `LK`: the target has positive direct START SCORE evidence in another aspect,
  but none in this aspect.
- `NK`: the target has no positive direct START SCORE evidence in any aspect.

The SCORE set is `EXP,HDA,HEP,HGI,HMP,HTP,IDA,IEP,IGI,IMP,IPI`. A source row
counts only when M10C `donor_accession` equals the original FASTA accession.
Transferred donor annotations, `NOT` rows, non-SCORE evidence and GO closure
are excluded from class assignment. Replaced or alternate GO identifiers are
accepted only if resolution is unambiguous and the active term remains in the
source aspect. Cross-aspect replacements and unresolved terms are excluded
from class evidence and recorded in the audit TSV.

One protein can have different classes for MF, BP and CC. Counts are therefore
reported as target-aspect pairs, not unique proteins. Documentary look-ahead
remains a separate unresolved audit question.

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
  --output-dir /absolute/path/outside-run/cafa5-start-knowledge-cohorts-v1
```

The publisher validates the benchmark and certificate, verifies the M10C
manifest and direct-provenance database against their checksums, then queries
only exact-target positive SCORE evidence for the certified START release. It
also checks every source GO against the pinned ontology. It publishes:

- `knowledge_cohorts.tsv`: one row per eligible target-aspect pair, with the
  original accession, internal provenance ID, species TaxID, aspect, class,
  and direct-evidence aspects.
- `direct_start_go_resolution_audit.tsv`: one auditable row per exact-target
  direct SCORE evidence record, including GO disposition and evidence ID.
- `manifest.json`: benchmark, ontology, temporal and M10C identities, policies,
  class counts, evidence counts, and file hashes.

## Evaluate methods with filters

The cohort directory is a required input, even for `--knowledge all`, so every
exported prediction row carries its class label. Each run must name at least
one aspect. Use the CAFA names (`MF`, `BP`, `CC`) or the PROGENY codes (`F`,
`P`, `C`). The evaluator produces separate outputs per aspect and never pools
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
  --cohorts /absolute/path/to/cafa5-start-knowledge-cohorts-v1 \
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

Each method's `filtered_predictions_<method>.tsv` contains the propagated,
scorable prediction rows with `method_id`, `protein_id`, `go_term`, `score`,
`aspect`, `knowledge_status` and `taxid`. `curves.tsv` contains one row per
method, aspect and threshold, including the unweighted and IA-weighted metrics,
RU, MI and Smin. `plots/` contains comparative threshold curves and a separate
precision-recall plot per aspect. The tables and SVG source files are the
reusable inputs for later custom plotting and tables.
The run summary uses schema `progeny-multi-method-evaluation-v2` and records
the exact filter selection and selected target-aspect counts.

Information Accretion is computed separately once for a fixed START GAF,
ontology and policy. Adding methods or changing cohort filters does not require
recomputing IA.
