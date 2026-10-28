# PROGENY contributor instructions

PROGENY creates time-resolved protein GO benchmark datasets. The public code
checkout, external input dataset, and each virgin run must stay separate.

## Scientific invariants

- Preserve literal extended IUPAC sequence identity, including ambiguous amino
  acids, in EXACT matching. NONEXACT donors require the same resolved TaxID.
- Preserve START/END release-local GO annotations and documentary provenance.
  Documentary look-ahead is explicit; GO annotations must not leak across roles.
- Keep DP scoring, GO/NOT handling, independent manifests, hashes and
  versioned scientific schemas fail-closed; do not silently migrate old runs.
- Do not reuse benchmark, cohort or run artifacts across installations or
  benchmarks. The only cross-run cache is START Information Accretion under
  the installer-managed shared root, keyed by release, materialized GOA hash,
  pinned ontology hash and the complete serialized IA policy. Reject any
  cache whose manifest or checksums do not match that identity.

## Engineering and release requirements

- Ruff lint and format use the rules in `pyproject.toml`, including E501 88.
- `pixi run test` builds all 13 native tools and the pinned IA Roaring tool
  using locked Pixi, then runs the complete suite with both native paths
  enabled. A missing required native binary must fail the command, not skip.
- All user input paths are settable; no server-specific paths in active code.
- Keep data and run roots entirely outside the source checkout.
- New runs are virgin: a run root must not pre-exist; the preparator creates it.
- Alpha schema names are part of the serialized contract. A rename of a
  schema or executable changes identity, not the mathematical GO/DP policy.
- Do not modify a running external production or shared audit worktree.
