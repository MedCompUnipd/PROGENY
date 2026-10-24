# Canonical V2 performance: workload and final GO stages

## Scope and baseline

The frozen scientific reference is commit
`e5abd2590c6fb43f105922309977cda61a8445b1`. This package changes only
SQLite access paths in two code files for **future runs**. It does not alter
CAFA5's live interpreter, scratch database, binaries, workflow or receipts.

## Workload (after B3 and documentary handoff)

`release_candidate_boundary.prepare_release_candidate_boundary` imports
candidate and documentary rows into a private scratch database. The primary
key `(role,target,rid)` is not suitable for repeated queries by `(role,rid)`
because the middle `target` column is not constrained. A secondary index
`candidates_by_role_rid` is created after imports and before the overlap
sequence validation.

`release_workload.build_release_workload` repeatedly counts `extra` by
`(role,rid)`, while its primary key is `(role,target,rid)`. The secondary
index `extra_by_role_rid` is created after pair import and primary merge,
before the FULL-store merge.

The data, ordering queries, exact matching, donor decisions, taxonomic
policy, DP algorithms and release-local GO rules are unchanged. Both scratch
databases are discarded after publication; the new indexes are not output
artifacts. Source code identity will nonetheless differ from the freeze, so
new runs must retain their new implementation provenance.

## The final stage is not demonstrably the same SQLite problem

- **M8 collection:** `stage08_gaf_collection.collect_one_normalized_gaf`
  streams complete normalized GOA files and hashes the bytes, filtering by
  donor accession in memory. No repeated SQLite `(role,rid)` query appears
  in this collector. A full release scan and output expansion can be costly.
- **M10C interpretation:** `stage08_compact_interpretation` bulk-inserts
  direct support, creates `direct_by_source`, groups unique terms, expands
  GO closure and upserts into a keyed `term_code_support` table. Performance
  risks involve insertion, expansion and term aggregation.
- **Temporal benchmark:** `stage08_temporal_benchmark` streams ordered
  `term_code_support` and imports into `terms`, with a composite primary key
  `(target_id,aspect,go_id)`. Its repeated accesses are not the workload's
  `(role,rid)` pattern. Profiling must distinguish the source scan, upserts,
  final iteration, GO ancestor lookups and I/O.

Do not add speculative indexes to M8/M10C/Temporal. First collect timings
for their actual stages on the independent release, using the same inputs,
source/version fingerprints and certified output comparison.

## Acceptance gates

1. Existing boundary/workload/identity tests pass under both original and
   patched source modules.
2. End-to-end synthetic workload output bytes and summary hashes match the
   original under an identical fixture root.
3. SQLite query plans use both columns of the two new indexes.
4. The release installation script fails with a nonzero exit on an error,
   without reporting a successful build.
5. The GCC 14.4 release profile builds independently and provides C++20,
   OpenMP and bounded `-O3` / rolling `-O2` verification.
6. A final fresh E2E and full scientific regression remain mandatory before
   `REPOSITORY_AUTONOMY=CERTIFIED` may be declared.
