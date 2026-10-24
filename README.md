# PROGENY

**PRO**tein GO function annotation benchmark **GEN**erator.

**Alpha software:** the scientific contracts, command-line interfaces and
packaging may evolve. Pin a Git commit for reproducible analyses. The Python import namespace is `progeny` and the installable
distribution is `progeny-benchmark`. Neither requires another checkout.

## Installation and separation of code, input, and runs

Install [Pixi](https://pixi.sh/) first. Clone PROGENY into a **code-only** directory:

```bash
git clone https://github.com/MedCompUnipd/PROGENY.git /work/PROGENY
cd /work/PROGENY
pixi install --locked
# Build the complete native toolchain (13 pinned executables):
bash <<'PROGENY_BUILD'
set -Eeuo pipefail
for task in \
    build-release-fasta build-goa-normalize build-go-positive-filter \
    build-raw-ox-extract build-primary-candidate-scan \
    build-primary-candidate-scan-v2 build-direct-accession-anchors \
    build-candidate-sequence-extract build-onehop-lineage-scan \
    build-directional-glocal-full-dp build-full-exact-cross-strain \
    build-certified-bounded-dp-v2 build-certified-rolling-dp-v1; do
    pixi run "$task"
done
PROGENY_BUILD
```

The native compilation uses the pinned GCC toolchain on the supported Linux
platform. See `docs/PROGENY_NATIVE_RELEASE_TOOLCHAIN.md` for build provenance.
Do **not** put raw data, preprocessed inputs, intermediate files or published
results in `/work/PROGENY`. Keep datasets and run roots outside the checkout.

## Start a new PROGENY study — guided setup

You **do not have to write a JSON specification**, modify YAML configuration,
identify native executables, calculate scientific fingerprints or use Snakemake.
Once you have collected your biological source files, start the guided assistant:

```bash
bash SETUP_PROGENY.sh
```

It explains each question and accepts ordinary protein FASTA files, either
with one organism NCBI TaxID, with a separate protein-to-TaxID table, or with
individual TaxIDs in FASTA headers. Select your UniProt/GOA/taxonomy/GO files
for the START and END releases and explicitly approve the scientific policies.
The assistant compiles missing native tools, verifies inputs, imports targets,
computes their content identity and prepares a virgin run, without reusing an
older dataset or run. It will print a second **single command** to start it:

```bash
bash /path/to/your-study-dataset/START_PROGENY.sh
```

**Read [the step-by-step scientist's guide](docs/PROGENY_GUIDED_SETUP.md)**
for the list of required biological files, example FASTA headers, the meaning
of each scientific policy and what PROGENY will and will not check.

The reference evidence classification is a versioned, reviewed PROGENY legacy
profile, **not an official ECO standard**. You must explicitly accept it and
ensure it is appropriate for your study. Files must already be available:
the assistant does not download or verify the historical identity of a release.

The detailed reference for existing advanced workflows, decompression and
strict input contracts remains [the external dataset layout specification](docs/PROGENY_EXTERNAL_INPUT_LAYOUT.md).

## Quality and alpha status

The alpha release candidate has passed the full configured Ruff ruleset,
native compilation and focused synthetic scientific tests. Its publication
and fresh-clone validation are separate release gates: **a successful local
release candidate does not imply that GitHub `main` has been updated**.

The optional historical UniProt Python oracle remains outside a standalone
installation; the canonical native converter has committed fixture coverage.
The native Stage 07/M8 integration test must run with its binary explicitly
configured in the release gate, not be silently skipped.

See `LICENSE` for licensing terms.

## Benchmark deliverables and Power User controls

A successful run through the **generated launcher** now publishes a separate
user-facing bundle at `STUDY-RUN/results/benchmark/`. The export contains a
FASTA with **the complete original user headers** for evaluable targets,
GO EVAL/SKIP tables with original protein IDs, identity mapping for debug,
and an offline `report.html` with START/END release statistics, target survival,
species and MF/BP/CC GO counts. Stage 00 and all canonical scientific outputs
continue to use `T000000...` internally and are never rewritten by the export.
The report is descriptive: Fmax/Precision–Recall scoring is deferred.

Two configuration levels are supported. Guided Setup keeps the reviewed
reference experimental evidence profile as its default and displays a
confirmation question. A **Power User** can supply a validated advanced JSON
file to change explicit evidence-code classes, CPU/DP budgets and the worker
memory profile. Scientific class changes are fingerprinted by the temporal
policy; worker resources are separately pinned in execution intents. See
[Benchmark export and Advanced Configuration](
  docs/PROGENY_BENCHMARK_EXPORT_AND_ADVANCED.md) for the exact default SCORE,
NON_SCORE and EXCLUDED code lists, template paths, validation, commands,
launcher details and output file definitions.
