# PROGENY metrics and CAFA4 comparison, 2026-11-04

## Scope and references

Reviewed the supplied CAFA4 preprint, version 2 posted June 12, 2026,
DOI 10.64898/2026.05.06.722942, Methods 2.2-2.5 (PDF pp. 4-7),
its 40-page supplement (S1 and S3), and Figure S11 supplied separately.
The latter has nine panels: three aspects times PR, weighted PR, and RU-MI.
It is an ARGOT comparison figure; it should not be identified as a CAFA4
supplementary figure.

Also inspected the primary implementation cited by the supplement:
https://github.com/claradepaolis/CAFA-evaluator-PK
Files: src/cafaeval/evaluation.py, graph.py, parser.py and README.md.
Repository contents were read on 2026-11-04; this is not a frozen commit
comparison or an execution of their evaluator.

The numerical audit uses the submitted PROGENY curves.tsv and summary JSON.
Source evaluation git head recorded there:
ed359d925936bcb2ee197bc9a0ab4f1209141472.
Curve table SHA-256:
d2e51fcfce54a60d1a23eea147ebfdfd002205aa7c70f2e34fab495e1f440696.
Source inspection used available PROGENY snapshots plus the public main
macro and weighted metric modules. This does not certify every file at
that server commit; no access to the thanos filesystem was available.

## Implemented formulas

For an eligible target/aspect i, let T_i be its published EVAL truth, and
P_i(tau) the submitted predictions after GO resolution, maximum propagation,
and SKIP/NEUTRAL/root removal. Let N be the fixed eligible population, and
m(tau) the number of targets with a nonempty scorable prediction set.

- Macro precision = sum_i |P_i intersect T_i| / |P_i|, divided by m(tau).
  Empty prediction sets do not contribute to that mean.
- Full macro recall = sum_i |P_i intersect T_i| / |T_i|, divided by N.
  Targets without predictions retain a zero contribution.
- F(tau) is the harmonic mean of these two means; Fmax is its grid maximum.
  This is not an average of per-protein F scores.
- Weighted macro precision replaces set cardinalities by sums of IA.
  The implementation averages over targets with positive predicted IA.
- Weighted macro recall uses weighted truth denominators and fixed N.
  A zero-weight truth target contributes zero to this mean.
- RU(tau) = sum_i sum_{g in T_i minus P_i} IA(g) / N.
- MI(tau) = sum_i sum_{g in P_i minus T_i} IA(g) / N.
- S(tau) = hypot(RU(tau), MI(tau)); Smin is its grid minimum among
  thresholds with scorable predictions in the existing implementation.

The macro precision/full recall and RU/MI formulas have the CAFA4 form,
conditional on using the same truth, masks, IA, propagation and population.
Weighted macro PR is an additional PROGENY output, distinct from micro PR.
Zero-IA populations are an edge case that needs a declared denominator policy
when comparing other evaluators; unweighted and weighted coverage can differ.

## Concrete differences from the CAFA4 experiment

| Topic | CAFA4 paper/supplement | Current PROGENY profile |
|---|---|---|
| Knowledge cohorts | Prior experimental evidence, separately per evaluated aspect | Same NK/LK/PK logic, using positive SCORE evidence from all accepted target donors |
| SCORE codes | 13 listed codes, including TAS and IC | 11 SCORE codes; TAS and IC are not SCORE |
| Target identity | UniProt object IDs mapped to CAFA targets | Arbitrary target IDs and certified accepted donors; exact and admitted nonexact donors can contribute |
| Existing nonexperimental GO | Not prior experimental knowledge | Can become EVAL CONFIRMATION when END acquires SCORE; compatible with experimental gain interpretation |
| Known experimental GO | Excluded using START known terms in PK | START SCORE already known is SKIP; published masks also handle other states |
| Conflicts and NOT | Negative annotations dropped in preprocessing | Explicit temporal conflict/NOT rules and NEUTRAL masks; not the identical scoring universe |
| MF protein binding | GO:0005515 explicitly excluded | No global exclusion found in the reviewed evaluator profile |
| Propagation | Supplement command uses `-prop fill` | Maximum propagated to all admitted ancestors |
| Ancestor scores | `fill` only assigns an ancestor where its current score is zero | `max` can increase a supplied ancestor score using descendants |
| Graph | GO version specific to each CAFA4 benchmark | One pinned ontology, same-aspect is_a and part_of closure |
| IA reference | Paper describes experimentally annotated UniProtKB proteins | Accepted positive START corpus across evidence codes; NOT excluded |
| IA estimator | Paper describes maximum likelihood | Published PROGENY adds one synthetic universally annotated protein: log2((parent_conjunction+1)/(term+1)) |
| IA denominator | Conditional on all parents being present | Same parent-conjunction interpretation, not sum of child counts |
| Micro PR/Fmax | Explicitly included in CAFA4 | Current curves.tsv contains macro and IA-weighted macro, not micro |
| Grid | Supplement command uses step 0.001 | Supplied run uses 0.01; 99 thresholds from 0.01 to 0.99 |
| Endpoints | Cited implementation uses arange(step,1,step) | Same endpoint convention for the compared CLI profile |
| Statistical intervals | 1,000 bootstrap iterations, 2.5-97.5 percentiles | No bootstrap confidence intervals in the current supplied outputs |
| Coverage | Coverage over benchmark population | Output has any-score coverage plus threshold-dependent coverage; label them explicitly |
| Incomplete mode | Fixed denominator m(0) | Secondary covered recall uses m(tau); it is not the same incomplete-mode estimator |

Thus PROGENY follows a compatible temporal evaluation philosophy, but is not
numerically interchangeable with that CAFA4 experiment. These differences
are not automatically bugs. The approved SCORE, donor, IA and mask policies
must not be changed as part of a graphics update.

The reference CAFA code drops zero-coverage thresholds before selecting
optima. PROGENY semantic optima also omit those points. A theoretical optimum
over a grid that includes empty predictions can differ. Report the grid and
scope rather than claiming a continuous or endpoint-inclusive optimum.

## Checks performed

1. Compared both ARGOT methods for every one of 99 thresholds in each aspect.
   All 11 metric columns match exactly, giving 3,267 identical paired values.
2. Checked F1 as harmonic mean, weighted F1 likewise, and S as hypot(RU,MI)
   for all 891 table rows: maximum absolute error is zero for each identity.
3. Ran an independent direct set calculation on three proteins, including a
   target without a correct prediction and a threshold with no predictions.
   Macro/full recall, weighted macro PR, RU, MI and S matched the reviewed
   PROGENY implementations. This is a small formula oracle, not validation
   of corpus annotation construction or a full CAFA evaluator comparison.
4. Rendered separate PR, weighted PR and RU-MI panels from the real data.
   Optima refer to sampled rows, with no fitted or fabricated observations.
5. Added tests for correct axis mapping, optimum selection, singleton points,
   XML escaping, overlap styling, and preservation of source curves.

Ruff and pytest executables were unavailable in the authoring runtime and
package installation failed. AST parsing, E501 checks and the four checks
via their Python entry points were run locally. The installer instructions
include the actual locked Pixi Ruff sequence and pytest checks for thanos.
A full PROGENY/Snakemake/native installation test is outside this plot add-on.

## New plotting outputs

Default: six SVG files, PR and RU-MI for MF, BP and CC.
With --include-weighted: nine files, adding weighted PR for each aspect.
Every file is a single panel. Existing evaluation plots remain available.

Graphics use thin connected observations, subtle grids, consistent colors,
different line dash styles, a circled optimum, and a legend including the
method, best value, and threshold. Identical curves are not offset to create
an artificial difference; dash styles and concentric optimum markers help
show that multiple methods occupy the same coordinates.

RU/MI remain averaged per eligible protein, in bits/protein. The very large
axes in the provided ARGOT Figure S11 must not be copied as though its plotted
sums and the PROGENY per-protein averages were the same quantity.

No statistical smoothing, spline, envelope or extrapolated PR endpoint is
introduced. Curve segments follow threshold order, preserving nonmonotone
precision. best_points.tsv records the exact numeric source for markers.

The new command works on existing curves.tsv, including filtered NK/LK/PK
or species runs. It neither recomputes IA nor selects cohorts after metrics
have already been aggregated. Per-cohort metrics require the existing
--knowledge/--taxid evaluation options and their own curves.tsv.

CAFA4 micro curves require new micro calculations, and confidence bars require
per-target bootstrap data. Year-by-year supplementary plots require separate
certified END releases/runs. These cannot be reconstructed from one aggregate
curve table and are not fabricated by the plot command.
