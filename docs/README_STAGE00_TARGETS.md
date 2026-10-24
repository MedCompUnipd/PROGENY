# PROGENY alpha — Stage 00: import your FASTA targets

Stage 00 (manifest schema `progeny-target-import-v2`) converts a **multiline protein FASTA** into the strict two-line FASTA
and metadata TSV required by PROGENY. It never performs biological sequence
repair, alignment, or GO annotation. Users must provide an NCBI TaxID for each
protein; the original source ID is preserved in a mapping file.

## Required input header

Every FASTA header **must** contain exactly two fields separated by a **real TAB**:

```text
>SOURCE_ID<TAB>NCBI_TAXID
```

The printed string `<TAB>` above is an explanatory placeholder: in your actual
file, press the Tab key (ASCII 0x09); **do not enter `<TAB>` literally**.

`SOURCE_ID` must have a consistent identity and use only ASCII letters `A-Z`, `a-z`, digits,
underscore `_`, dot `.`, colon `:`, and hyphen `-`; it must start with a letter
or digit. No spaces, pipes, slashes, Unicode symbols or additional TABs.
`NCBI_TAXID` must be a positive decimal integer in canonical form; only digits
`0-9`, no sign, whitespace, decimals, zero or leading zeroes.

Example (the gap before the TaxID is a real TAB):

```text
>Protein_001	9606
MALWMRLLPLL
ALLALWGPDP
>sample-B:02	10090
ACDXBJZUOXX
```

A syntactically invalid header aborts the **entire conversion**; no dataset is
published. Multiline sequences are joined without changing residue characters.
The downstream canonical Stage 01 performs biological sequence validation and
may reject unsupported symbols or layouts. Empty sequences are not allowed. Identical repeated records are deduplicated.

## Usage

Run from an installed PROGENY checkout, with an output directory that **does
not exist yet** and is **outside the Git repository**:

```bash
pixi run python scripts/pipeline/00_import_targets.py \
  --input /absolute/path/to/proteins.fasta \
  --output-directory /absolute/path/to/datasets/study1 \
  --minlen 10
```

### Sequence-length filter and exact duplicates

`--minlen N` sets the minimum **amino-acid sequence length** after assembling
multiline FASTA records. Default: **10**. `N` must be an integer **greater
than or equal to zero**; use `--minlen 0` to disable length filtering (empty
sequences are still invalid). A sequence with 2 amino acids is excluded by
default, with `BELOW_MINLEN` recorded in `targets.rejected.tsv`. An invalid
value aborts conversion without publishing any dataset.

When **exactly the same validated header** (`SOURCE_ID<TAB>NCBI_TAXID`) and
**identical assembled sequence** occur repeatedly, Stage 00 retains only the
first occurrence. All later occurrences are recorded under
`DUPLICATE_IDENTICAL_RECORD`, with `first_source_record` identifying the first
occurrence, even if it was excluded for length or unknown taxonomy.

If the same `SOURCE_ID` appears with a **different sequence or TaxID**, Stage
00 aborts conversion instead of choosing arbitrarily. Two distinct IDs with
the same sequence are **not** deduplicated. Internal target IDs are assigned
according to original source-record position, leaving intentional gaps for
excluded or duplicate records.

For early checking of real taxonomy IDs against an explicitly chosen NCBI
Taxonomy release, supply `nodes.dmp` and, ideally, `merged.dmp` from **the same
release**:

```bash
pixi run python scripts/pipeline/00_import_targets.py \
  --input /absolute/path/to/proteins.fasta \
  --output-directory /absolute/path/to/datasets/study1 \
  --taxonomy-nodes /absolute/path/to/taxon/nodes.dmp \
  --taxonomy-merged /absolute/path/to/taxon/merged.dmp
```

With taxonomy checking enabled, unknown numeric TaxIDs cause **only those
sequences** to be omitted and logged in `targets.rejected.tsv`. Merged IDs are
kept with the original TaxID and the validated current ID is recorded in the
mapping TSV. With no taxonomy files, IDs are syntax-checked but their existence
is **not verified**; subsequent PROGENY taxonomy resolution is still mandatory.
A conversion with zero accepted proteins fails closed.

If, and **only if**, source IDs are actual UniProt accessions, use
`--header-ids-are-uniprot-accessions`. This option checks accession syntax but
**cannot establish that the accessions exist**. Without this explicit option,
the `uniprot_accession` metadata column remains blank, preventing an arbitrary
user identifier from masquerading as documentary UniProt evidence.

## Output files

Stage 00 publishes an entire new dataset directory after successful validation:

| File | Purpose |
| --- | --- |
| `targets.fasta` | Strict two-line canonical FASTA, IDs `T000000001`, etc. |
| `targets.metadata.tsv` | Exact columns: `target_id`, `ncbi_taxid`, `uniprot_accession` |
| `targets.mapping.tsv` | Original source IDs, row numbers, raw/resolved TaxIDs, SHA256 |
| `targets.rejected.tsv` | Exclusions: `BELOW_MINLEN`, `DUPLICATE_IDENTICAL_RECORD`, `UNKNOWN_TAXID`; reference to first occurrence when duplicated |
| `00_summary.json` | Accepted, short, duplicate, unknown-TaxID counts, `minlen`, modes |
| `00_manifest.json` | Input, taxonomy reference, and output SHA256 checksums |

Generated target numbers correspond to **original input record order**. If a
record is too short, duplicated or has an unknown TaxID, its number is not
reused; gaps are intentional and preserve provenance. The destination must not exist; no `--overwrite` option
is offered in this alpha. Keep output directories and manifests for auditing.

## Connecting Stage 00 to a virgin PROGENY run

Do **not** create input files under the intended run root: the fresh preparator
requires that `RUN_ROOT` does not yet exist. Instead, save Stage 00 files in an
external dataset directory and point the complete fresh specification to them:

```json
{
  "pipeline": {
    "targets": {
      "mode": "canonical",
      "fasta": "/absolute/path/to/datasets/study1/targets.fasta",
      "metadata": "/absolute/path/to/datasets/study1/targets.metadata.tsv"
    }
  },
  "recipe": {
    "targets_input": "/absolute/path/to/datasets/study1/targets.metadata.tsv"
  }
}
```

The JSON fragment above only illustrates the **three relevant fields**; it is
**not** a complete valid fresh specification. To update those fields in your
own complete JSON template automatically, add:

```text
--fresh-spec-template /absolute/path/to/complete-fresh-spec.json
```

This produces `fresh_spec.stage00.json` in the Stage 00 dataset directory,
without editing the original template or creating the run. All other fields
(including releases, evidence registry, ontology, native binary paths, policies,
limits and identity) must already be valid and controlled independently.
The Stage 00 adapter does **not** validate the full downstream fresh schema.

## Alpha support boundaries

- Input is uncompressed ASCII FASTA with strict `>SOURCE_ID<TAB>NCBI_TAXID` headers.
- No taxonomic database is downloaded or implicitly selected.
- Raw TaxIDs from merged records are preserved for the native taxonomy resolver.
- Taxonomy checks are only as current and complete as the user-supplied release.
- Conversion and GO annotation are separate stages.
- Scratch and output directories must remain outside the source checkout.
