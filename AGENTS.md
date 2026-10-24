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
- Do not reuse artifacts from another installation, benchmark or run.

## Engineering and release requirements

- Ruff lint and format use the rules in `pyproject.toml`, including E501 88.
- Test the complete suite and compile all 13 native tools using locked Pixi.
- All user input paths are settable; no server-specific paths in active code.
- Keep data and run roots entirely outside the source checkout.
- New runs are virgin: a run root must not pre-exist; the preparator creates it.
- Alpha schema names are part of the serialized contract. A rename of a
  schema or executable changes identity, not the mathematical GO/DP policy.
- Do not modify a running external production or shared audit worktree.
