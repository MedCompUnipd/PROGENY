# Canonical V2 operations

Status date: 2026-10-22. Consolidation status: **NOT_YET_CERTIFIED**.

The scientific baseline is commit `e5abd2590c6fb43f105922309977cda61a8445b1`, tagged
`progeny-canonical-v2-rolling-dp-validated-20261022`.
This guide describes that baseline and the outstanding operational work.
It adds no scientific policy and makes no new installation or run certification.
Historical evidence remains scoped to recorded inputs, source, binaries,
environment, and outputs.

## Current support boundary

| Area | Current status |
| --- | --- |
| Raw inputs through temporal benchmark | Implemented by the fresh workflow; controlled validation evidence exists. |
| Exact bounded and rolling DP | Implemented, with differential and interruption/resume validation evidence. |
| Arbitrary target formats | Must first satisfy the canonical target contract; a general Stage 00 adapter is outside this entry. |
| General recipe preparation | Recipe reader exists; no general production recipe-generation CLI was found at the freeze. |
| Final completion verification | API exists; the fresh workflow and inspected production launcher do not invoke it. |
| Clean installation on another server | Not certified by this consolidation; environment/build and acceptance work remains. |
| macOS and Windows execution | Pixi platform declarations are not execution certification; current operational evidence concerns Linux. |
| Prediction and external scoring | Outside this benchmark-construction DAG. |

On thanos, consolidation belongs to `[HISTORICAL_MACHINE_PATH_REMOVED]`, on
`chatgpt/progeny-v2-autonomy-consolidation`. Production uses `[HISTORICAL_MACHINE_PATH_REMOVED]`.
Its branch remains `chatgpt/progeny-v2-validated` at the frozen commit.
These are observed deployment paths, not portable defaults.
Builds and intensive acceptance runs are deferred while they would compete
with the CAFA5 production run. Documentation changes do not certify that run.

## Fresh entry and graph

The raw-input entry is [workflow/canonical_v2_fresh.smk](../workflow/canonical_v2_fresh.smk).
Its only Snakemake configuration key is `fresh_recipe`, selecting an absolute recipe path.
The schema is `progeny-canonical-v2-fresh-recipe-v1`.
The recipe selects a physical source checkout and a separate physical run root.
Configuration is `<run>/pipeline.stage08.collection.yaml`; all publications belong to that run.

The workflow imports only the required upstream rules from
[workflow/Snakefile](../workflow/Snakefile). It produces 34 raw-stage bundles,
six discovery bundles across START and END, and 16 canonical publications.
Plans/specification resolve after upstream producers finish; old results are not prerequisites.

| Canonical node | Instances | Immediate canonical predecessors |
| --- | --- | --- |
| `exact` | START, END | Raw/discovery inputs |
| `ledger` | START, END | Raw/discovery inputs |
| `projection` | START, END | Same-role `ledger` |
| `lookup` | START, END | Both `exact` publications |
| `handoff` | COMMON | Both `lookup` publications |
| `b3` | COMMON | Both `projection` publications |
| `workload` | COMMON | `b3`, `handoff` |
| `alignment` | COMMON | `workload` |
| `stage07` | COMMON | `workload`, `alignment` |
| `m8` | COMMON | `stage07` |
| `m10c` | COMMON | `stage07`, `m8` |
| `temporal` | COMMON | `m10c`, `m8` |

The table omits additional direct inputs and tools. Their explicit dependency
map is `node_dependencies` in [fresh_dag.py](../src/progeny/canonical_v2/fresh_dag.py);
execution is dispatched by [dag_execution.py](../src/progeny/canonical_v2/dag_execution.py).

## Raw input boundary

[Canonical external target input v1](CANONICAL_TARGET_INPUT_V1.md) is the target
contract. Supply a coordinated FASTA and metadata TSV with one-to-one IDs:

- Each FASTA record has exactly two physical lines: `>target_id`, then sequence.
  IDs are unique and non-empty; headers contain no description or whitespace.
- The TSV header is exactly `target_id`, `ncbi_taxid`, `uniprot_accession`, in
  that order. All columns are required; the accession value may be empty.
- TaxID is explicit. Accession is provenance evidence, not protein identity
  and not a source from which the core silently infers TaxID.
- Sequence is continuous ASCII uppercase `ACDEFGHIKLMNPQRSTVWYBJOUXZ`.
  Ambiguous symbols and U/O are literal. No layout, case, gap, punctuation,
  or terminal-stop repair occurs at this boundary.
- Distinct IDs remain distinct even when sequence and TaxID are equal.
  Invalid records retain deterministic rejection/audit evidence.
- Sequence length and SHA-256 assist indexing; literal equality remains the
  final exact-identity guard.

Also supply explicit START/END release identifiers and original UniProt,
GOA, and taxonomy inputs, plus ontology, evidence registry, and temporal policy.
The additional `targets_input` points at canonical metadata in the production recipe.
Stage 01 requires `targets.mode=canonical`; source-specific adaptation precedes it.

Raw files currently stored beneath `TESTING` are input locations, not a
dependency on old scientific outputs. Fresh canonical sources are mapped to
publications produced under the new run root. Relocating raw files requires
new explicit paths and provenance; no old result bundle should replace a producer.

## Environment and native tools

[pixi.toml](../pixi.toml), [pixi.lock](../pixi.lock), and
[pyproject.toml](../pyproject.toml) describe the environment; the project is
installed editably and Snakemake is pinned to 9.27.0. Native builds use CMake/Ninja,
the compiler, zlib, and OpenMP. Linux x86-64 is the first clean-installation
certification target; other platforms require separate evidence.

The current fresh path with rolling DP uses these 11 native executables.
These are task names and declared outputs, not instructions to build now.
All output paths in the last column are relative to `.pixi/build/`.

| Build task | Executable task | Declared executable path |
| --- | --- | --- |
| `build-release-fasta` | `release-fasta-v2` | `progeny-release-fasta/progeny-release-fasta-v2` |
| `build-goa-normalize` | `goa-normalize-v1` | `progeny-goa-normalize/progeny-goa-normalize-v1` |
| `build-go-positive-filter` | `go-positive-filter-v1` | `progeny-go-positive-filter/progeny-go-positive-filter-v1` |
| `build-raw-ox-extract` | `raw-ox-extract-v1` | `progeny-raw-ox-extract/progeny-raw-ox-extract-v1` |
| `build-primary-candidate-scan` | `primary-candidate-scan-v1` | `progeny-primary-candidate-scan/progeny-primary-candidate-scan-v1` |
| `build-primary-candidate-scan-v2` | `primary-candidate-scan-v2` | `progeny-primary-candidate-scan-v2/progeny-primary-candidate-scan-v2` |
| `build-direct-accession-anchors` | `direct-accession-anchors-v1` | `progeny-direct-accession-anchors/progeny-direct-accession-anchors-v1` |
| `build-onehop-lineage-scan` | `onehop-lineage-scan-v1` | `progeny-onehop-lineage-scan/progeny-onehop-lineage-scan-v1` |
| `build-full-exact-cross-strain` | `full-exact-cross-strain-v1` | `progeny-full-exact-cross-strain/progeny-full-exact-cross-strain-v1` |
| `build-certified-bounded-dp-v2` | `certified-bounded-dp-v2` | `progeny-certified-bounded-dp-v2-cmake/progeny-directional-glocal-bounded-dp-v2` |
| `build-certified-rolling-dp-v1` | `certified-rolling-dp-v1` | `progeny-certified-rolling-dp-v1-cmake/progeny-directional-glocal-linear-dp-v1` |

The recipe key `full_dp_binary` selects the certified bounded V2 executable,
despite its historical name. The optional `large_dp.binary` selects rolling DP.
The active production recipe pins both under `.pixi/build/progeny-exact-large-dp/`,
which differs from the two task output directories above. A rebuild is not
automatically byte-identical. Record binary hashes, source, compiler, flags, and linked libraries.
Legacy full-DP and candidate-sequence-extract tasks are not required in this fresh path.
An environment installation alone does not establish that the 11 native tools
exist or have passed their acceptance gates.

## Separate operational phases

### Prepare

Choose isolated run/scratch roots, canonical targets, release inputs, policies,
source snapshot, and tool paths. Materialize the run-local
configuration and recipe, preserving the frozen schema and scientific settings.
`read_recipe` validates control files and paths without executing producers.
The test fixture generator serves controlled validation scenarios; the
historical large-DP validation driver is not shipped with this alpha.
Neither provides a general production bootstrap CLI. Reusable preparation
and source-identity capture remain separate development work.

### Start

Use the fresh entry with the prepared recipe and matching checkout/environment.
Snakemake owns dependency ordering, scheduling, declared resources, and restart.
The stages own scientific admission, validation, numerical execution, and merge.
A cold dry run assesses graph construction; it is not scientific validation.
Keep large release scans and deep hash audits out of workflow parse time.
Use the run-specific launcher and persistent job/session mechanism established for that deployment.

### Resume

Resume against the same pinned recipe, sources, policies, tools, and checkpoint
identity. Preserve committed checkpoints and completed publications. The rolling
engine can checkpoint within a pair; its continuation status is not completion.
Canonical receipts and the publication protocol validate completed nodes.
Raw-stage recovery has its own wrapper behavior; do not assume every raw bundle
has the canonical receipt/immutability protocol. Do not delete or overwrite
scientific outputs to force a restart, or reuse a checkpoint after changing its
bound inputs/resources. Different experiments require a new run identity/root.

The inspected CAFA5 launcher requires absent `work`, `plans`, and `canonical`
directories: it handles first start only. A general resume procedure remains
to be completed. `validate_existing_upstreams` exists, but the frozen fresh
workflow does not invoke it before scheduling. Validate existing publications
before choosing restart options; `--rerun-incomplete` alone is not that validation.

### Verify: outstanding P0 integration gate

The final API is `validate_completed_workflow(recipe, spec)` in
[fresh_dag.py](../src/progeny/canonical_v2/fresh_dag.py). It checks completion
identity, deeply validates the complete upstream inventory, validates all 16
canonical receipts, and publishes `<run>/verification/<content_identity_sha256>.json`.
Its implemented checks complement validation performed when each node publishes.

The frozen fresh `rule all` requests outputs/receipts and checks the canonical
count. It does not invoke that final API. Its comment names `verify_fresh_run.py`,
but no such versioned CLI was found in the audited freeze. The inspected
production launcher reports `SNAKEMAKE_COMPLETED` after waiting for Snakemake;
it does not run final verification. The large-DP validation driver calls the API
for its controlled fresh128 scenario; that is not general launcher integration.

Therefore scheduler success alone does not establish final scientific acceptance.
Connecting a general final verifier to the operational lifecycle is the P0 gap.
Do not certify the current full CAFA5 run from its launcher message or infer
that the missing integration proves a scientific result is wrong. Final checks
and their retained report belong after execution, with source/build evidence.

## Scratch, resources, and publication

Set `TMPDIR`, `TMP`, and `TEMP` before starting Python or Snakemake: temporary
directory selection can be cached. Select an explicit persistent scratch root
isolated from source and scientific run directories and from other runs.
The thanos parent is `[HISTORICAL_MACHINE_PATH_REMOVED]`; the recipe gives its
per-run path. Check actual scratch and destination filesystems: current
alignment publication requires the same filesystem.
Retain scratch, checkpoints, and resume journals until the run is fully verified.

`large_dp.max_dp_memory_bytes` bounds accounted DP workspace, not total process
RSS or aggregate concurrent workload. Snakemake resource declarations alone do
not certify peak memory. Pair/chunk/invocation caps remain execution controls;
resource refusal means incomplete execution, never a biological exclusion.
Checkpoint identity includes inputs, geometry, executables, and resources.
Changing these requires deliberate re-preparation, not silent checkpoint adoption.

## Scientific invariants to preserve

- EXACT uses literal IUPAC26. FULL EXACT includes whole-sequence matches with
  `FRAG=1`; downstream eligibility still applies. Primary similarity scanning
  excludes fragments. Under `same_species_exact`, cross-subtaxon EXACT requires
  verified same-species evidence; it does not permit cross-species donors.
- NONEXACT admission requires independent documentary eligibility and the same
  resolved TaxID. DP does not select the biological candidate universe.
- The validated policy is `same_species_exact`, `partial_sequence=allow`,
  `documentary_fragment=allow`. Partial sequence and documentary fragment are
  independent donor controls; preserve their explicit provenance.
- START/END discovery stays release-specific. START union END documentary EXACT
  keys retain origin-release provenance and represent retrospective look-ahead.
- GO is strictly release-local. Preserve source assertions, NOT, evidence,
  permitted ontology relations, confirmation, and temporal masking semantics.
- Stage 07 association acceptance and `annotation_donor=YES` are distinct;
  downstream collection consumes the eligible donor channel.
- Preserve both affine glocal directions, literal match +2/mismatch -1/gap
  open -3/extend -1, deterministic tie-breaks, certified geometry, and finalizer.
  `dp_backend` identifies the contract; `dp_execution_backend` identifies the
  actual numerical engine. Rolling execution does not change pair admission.
- Preserve legacy behavior/fingerprints when optional `large_dp` is absent.
  Temporal truth follows the frozen policy, not a simple END-minus-START set.

## Identity, evidence, and historical documents

The recipe's `identity_sha256` is a supplied lock token; the reader checks its
format, not a complete live source-tree digest. Resolved content identity binds
recipe bytes, upstream manifests, and declared direct inputs/tools. Individual
planners include selected code inputs; this is not automatic coverage of every
transitive source file. Retain external source-freeze and build provenance.
Paths/manifest bytes participate in identity; relocation can change
fingerprints without scientific changes.

The recorded fresh128 and DP validation results are evidence for their bounded
scenarios. [PROGENY_V2_FRESH_INTEGRATION.py](../tests/PROGENY_V2_FRESH_INTEGRATION.py)
exercises real synthetic raw-to-temporal execution and restart; it is a future
isolated installation gate, not evidence that a new installation already passed.
The observed untracked `workflow/canonical_v2_long63_reuse.smk` is experimental:
it reuses prepared upstreams and exercises DP/Stage 07. It is neither the
portable fresh entry nor an independent raw-to-temporal certification.

Read earlier documents in their dated scope: [freeze handoff](PROGENY_CANONICAL_V2_FREEZE_AND_DP_HANDOFF.md),
[large-DP design](PROGENY_CANONICAL_V2_LARGE_DP_DESIGN.md), [source baseline](PROGENY_CANONICAL_V2_SOURCE_BASELINE_STATUS.md), and
[build integration](PROGENY_CANONICAL_V2_BUILD_INTEGRATION.md) contain historical
status or next-step statements. Earlier BLOCKED statuses do not describe every
later freeze; design text alone is not execution evidence. The old
[Stage 2C contract](PROGENY_STAGE2C_EXACT_DONOR_CONTRACT_V1.md),
[stage registry](PIPELINE_V2_STAGE_REGISTRY.md), [scientific decisions](SCIENTIFIC_DECISIONS.md), and
[Stage 07/08 interface](STAGE07_STAGE08_INTERFACE_CONTRACT.md) retain historical
context and applicable scientific decisions. Earlier alphabet restrictions
and integration-status statements must be read within their versioned scope;
the validated Canonical V2 contracts govern the frozen canonical execution.

Remaining work covers the final verifier, reusable preparation, source/build identity,
and isolated clean-installation evidence. Keep **NOT_YET_CERTIFIED** until those gates pass.
