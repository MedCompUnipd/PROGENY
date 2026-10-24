# PROGENY canonical V2: R10 Gitless raw-to-temporal validation

Evidence source: `r10_r3_retest_AeBQd850_REPORT.tar.gz`, 23 October 2026.
This record documents an isolated validation run; it is not a declaration of
full repository release certification.

## Observed results

- Cold source copy **without `.git`**, with Pixi environment installed from the
  lockfile and all 13 native targets built in the original R10 cold setup.
- Isolated Stage 2C Gitless provenance patch: Ruff check/fix, format, check,
  format-check, AST and 10 targeted synthetic tests passed.
- Serial and parallel first runs completed from original-format synthetic raw
  inputs through Temporal V2; controlled verify and resume passed both runs.
- 34 raw manifests and 16 canonical publications validated for each run.
- Parallel execution recorded **M8=2** and **Temporal V2=8** effective workers;
  serial runs recorded 1 worker for each stage.
- SHA256 hashes of 15 selected scientific TSV outputs agreed exactly between
  serial and parallel; original raw inputs verified unchanged (17 files).
- The fixture had 3 accepted targets, 3 admitted DP pairs, 384 DP cells, and
  4 START / 5 END release-local GO source rows. It exercises literal fragment
  and FULL OX documentary paths but does not cover all biological scenarios.
- No-op resumes kept the 15 selected scientific output hashes unchanged.
  Serialized control metadata, run roots and resource-profile identities may
  differ legitimately; do not compare all control files byte-for-byte.
- The isolated Gitless patch had **not** been installed in the audit worktree
  when the R10-R3 report was produced.

## Change scope

Stage 2C `build_plan` historically required a Git checkout. In a source-only
snapshot without `.git`, the two discovery planners now set
`git_head_at_creation` to JSON `null`. A real Git checkout still verifies the
Git worktree and records its actual HEAD. A symlinked `.git` marker is rejected.
The source, input and native SHA256 fields continue to pin scientific identity;
planner source changes legitimately change fingerprint keys. Existing
scientific policies, input resolution, publication rules and GO/NOT semantics
are unmodified by the provenance patch.

## Limitations and pending steps

A synthetic 3-target E2E is not a full-scale performance or biological
coverage benchmark. The parallel run (88.449 s) was not faster than the serial
run (87.147 s) on this tiny fixture and cannot establish production speedup.
The next milestones are installing the tested Gitless change in the audit
worktree, then migrating the complete validated source tree and tests to the
independent GitHub `MedCompUnipd/PROGENY` and certifying a virgin clone.
Preserve historical PROGENY and the frozen CAFA5 run unchanged.
