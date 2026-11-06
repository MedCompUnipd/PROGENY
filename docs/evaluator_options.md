# Evaluation policy options

The canonical benchmark and its EVAL/SKIP/NEUTRAL labels remain unchanged.
Evaluation options only change a separate prediction evaluation result.

`compare-predictions` and `evaluate-predictions` accept `--propagation max|fill`.
`max` is the PROGENY default and raises each ancestor to the largest score
below it. `fill` keeps an ancestor's positive supplied score; an ancestor at
zero takes the maximum from its already propagated direct children. Thus a
positive intermediate node can block a higher descendant score on one path,
while another parent path can still carry it. Explicit score zero behaves as
an empty cell for `fill`. The selected policy is recorded in the result.
These semantics follow the [CAFA-evaluator implementation](https://github.com/BioComputingUP/CAFA-evaluator/blob/main/src/cafaeval/graph.py),
but this does not establish full CAFA equivalence.

`prepare-evaluation --ia-profile all-positive|score-experimental|cafa4-experimental`
selects START Information Accretion (IA). `all-positive` preserves the current
positive UniProtKB GAF policy, including IEA. `score-experimental` admits the
11 PROGENY SCORE codes: EXP, HDA, HEP, HGI, HMP, HTP, IDA, IEP, IGI, IMP,
and IPI. `cafa4-experimental` adds TAS and IC to those 11 codes. NOT rows are
excluded in all profiles. All profiles use the same pinned ontology, GO
resolution, closure, protein identity and add-one regularization:
`IA(t) = log2((count(all direct parents)+1)/(count(t)+1))`.
When a term and its parent conjunction both have zero observed proteins, its
IA is zero. When the term count is zero but its parent conjunction count is
positive, its IA is `log2(parent_count+1)`. Each profile has a separate
fingerprint and artifact. `prepare-evaluation` reuses verified IA by default;
`--compute-ia` is required to run the full START GAF calculation.

The comparison TSV includes macro precision, recall and F1; pooled micro
precision, recall and F1; IA-weighted macro and micro versions; RU, MI and
Smin for each method, aspect and threshold. `summary.json` records Fmax for
macro and micro curves. Plots can be rebuilt from `curves.tsv`.

`--exclude-go FILE` accepts one active GO ID per line. For example, a file
containing `GO:0005488` and `GO:0005515` excludes exactly those two terms.
The evaluator applies the filter after prediction propagation to both
predictions and ground truth; descendants are retained. Target/aspect pairs
whose ground truth becomes empty leave the scoring population and are listed
in the result. The result records the file checksum, IDs and pair counts
before and after filtering. Filtering after propagation need not equal
excluding direct annotations before propagation as in CAFA4. Independent
cross-evaluator comparison remains necessary before claiming CAFA parity.
