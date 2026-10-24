# PROGENY R5: bounded per-target GO aggregation

## Scientific invariants

The stage08 M10C direct-provenance input is unchanged. The optimization
replaces only the internal reduction of GO closures to
`term_code_support`. Each grouped direct GO contribution is expanded using
the exact same pinned `graph.ancestors()` for POSITIVE and
`graph.descendants()` for NOT. Counts remain integer additions, keyed by
`(release, target, aspect, propagated_go, polarity, evidence_code)`;
`direct_count` is added only if `propagated_go == source_go`.

Instead of submitting every propagated group-term contribution as an SQLite
UPSERT, R5 folds counts by `(release,target)` in RAM, sorts reduced keys,
and then submits reduced UPSERT rows. It flushes at 32,768 distinct keys,
which bounds per-target RAM; repeated keys across flushes still sum through
SQLite's existing ON CONFLICT logic. The SQL schema, index, provenance and
scientific classifications are not modified. The number of source groups
and raw group-term expansions reported in manifests is unchanged.

## Identity and storage caveat

`propagated_terms.tsv` is checked byte-identical. The `direct_support` and
`term_code_support` SQLite contents, including primary keys and counts, are
checked logically identical. SQLite database *bytes* need not be identical
because insertion order and B-tree page layouts can change; the publication
manifest therefore will contain a different database SHA256 for the new
run. This is not scientific drift, but it must not be used to resume a
frozen recipe. Git/release fingerprinting must identify this code change.

The speedup numbers apply only to `_propagate_unique_groups`, not to the
whole M10C stage, DP or CAFA5. It currently remains single-process. Separate
per-target/release worker databases and deterministic merging are future
steps, not implemented or implicitly advertised by this R5 gate.

## Temporal progeny

R5 additionally benchmarks, without installing, `journal_mode=MEMORY` and
`synchronous=OFF` for the *private ephemeral* Temporal state database,
compared with the original FULL/DELETE staging configuration. It compares
all four Temporal TSV SHA256 digests, flags, counts and logical SQLite rows.
No Temporal source modification is installed: atomic-publication failure
semantics and full E2E parity must be tested before promotion.

## Limits

The fixture includes two releases, positive and explicit NOT, three literal
evidence codes, overlapping GO is_a/part_of closures, duplicate direct
supports, and forced RAM spill. It does not replace a complete virgin E2E
CAFA5 run or prove scaling to full GO graph/141,865 targets. The R5 server
gate checks identity, R4 regression, Python formatting, logical equality,
scientific TSV identity and a real timing comparison; it updates only the
autonomy audit worktree on success. No commit or push.
