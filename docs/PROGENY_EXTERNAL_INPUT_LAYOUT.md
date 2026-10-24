# PROGENY alpha — external dataset layout and preflight

This document is the technical contract implemented by
`scripts/installation/init_progeny_dataset.py`.

## Separation invariant

- **Code checkout:** contains source, Pixi lock/environment, binaries and tests.
- **External dataset:** contains original source files, Stage 00 canonical
  targets, pinned ontology, GOA, UniProt DAT, taxonomy, and input controls.
- **Virgin run root:** separately created by the fresh preparator, owns work,
  scientific publications, checkpoints, scratch, controls, logs and results.

No component may be nested within another. A run root must not exist before
preparation. The initializer never creates or overwrites a run root.

## Filename contract and compression

The initializer creates `config/dataset-layout.json`. Its `paths` section is
the authoritative expected-file inventory. Its `formats` section records
`gzip` or `plain` separately for Swiss-Prot DAT, TrEMBL DAT and GOA
in each role. Options `--start-sprot`, `--start-trembl`,
`--end-sprot`, `--end-trembl` override role-wide DAT defaults. The YAML
pipeline configuration is generated from the checked-out project's own
`config/pipeline.yaml` and points to **absolute paths** for those files.

| Role or scope | Input path relative to dataset root | Input format |
| --- | --- | --- |
| Common | `input/source/targets.raw.fasta` | ASCII FASTA, Stage 00 input |
| Common | `input/targets/targets.fasta` | Stage 00 two-line canonical FASTA |
| Common | `input/targets/targets.metadata.tsv` | Strict `target_id`, `ncbi_taxid`, `uniprot_accession` columns |
| Common | `input/ontology/go.owl` | Uncompressed OWL, one pinned ontology |
| Common | `input/policies/evidence_registry.json` | User-provided controlled registry |
| Common | `input/policies/temporal_policy.json` | User-provided controlled temporal policy |
| START / END | `input/<ROLE>/uniprot/uniprot_sprot.dat[.gz]` | Plain DAT or gzip DAT |
| START / END | `input/<ROLE>/uniprot/uniprot_trembl.dat[.gz]` | Plain DAT or gzip DAT |
| START / END | `input/<ROLE>/goa/goa.gaf[.gz]` | Plain GAF or gzip source GAF |
| START / END | `input/<ROLE>/taxonomy/nodes.dmp` | Plain NCBI taxonomy |
| START / END | `input/<ROLE>/taxonomy/names.dmp` | Plain NCBI taxonomy |
| START / END | `input/<ROLE>/taxonomy/merged.dmp` | Plain NCBI taxonomy |
| START / END | `input/<ROLE>/taxonomy/delnodes.dmp` | Plain NCBI taxonomy |

For `.gaf.gz`, a separate controlled materialization writes
`prepared/<ROLE>/goa.gaf`. The pipeline always reads **uncompressed GAF**.
No silent fallback to an unverified decompressor is allowed.

## Usage

`init` creates only directories and input controls; it refuses to overwrite an
existing dataset directory. Stage 00 creates the `input/targets` directory
only after processing a valid external source FASTA. When all data are present,
run `check --seal`; if a GOA source is gzip-compressed, use `check
--materialize-goa --seal` **once**. A repeated materialization is accepted only after a byte-for-byte
comparison of the prepared GOA with the original gzip source; no overwrite is
performed. Later checks should omit both flags: they verify the decompressed GOA
byte-for-byte against the declared compressed source without writing output. Missing files, unexpected gzip headers,
unsupported GAF version, changed ontology checksum, and pre-existing run
roots fail closed.

`bind --template` accepts a **complete** fresh specification from an
independently audited source; it does not infer a scientific identity or
invent donor policies. It maps input paths into that specification, ensures
all executable tool references point inside this checkout, and leaves the
run creation to the existing fresh preparator. Do not treat `bind` as a
replacement for fresh preparation or its scientific preflight.

## Alpha limits

- No implicit downloads or taxonomy snapshot selection.
- No on-the-fly `.gaf.gz` support in Stage 01B1 C++; materialize first.
- No automatic transitive input provenance pin for every large raw file:
  use the preparator's `--hash-biological-inputs` when needed.
- No automatically generated scientific identity or temporal policy.
- Paths in a generated layout are data-specific; they are **not** embedded in
  the installed Python or Snakemake implementation.
