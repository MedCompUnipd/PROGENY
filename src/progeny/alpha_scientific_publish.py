"""Immutable, post-certification user benchmark publication and statistics.

Only reads canonical and dataset inputs; creates run/results/benchmark atomically.
This is not a prediction evaluator or an NK/LK/PK classifier.
"""

from __future__ import annotations

import csv
import html
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from progeny.alpha_export import (
    TEMPORAL_FILES,
    _canonical_to_user,
    _fasta_targets,
    _json,
    _regular,
    _rows,
    _validate_headers,
    _verify_member_manifest,
)
from progeny.alpha_identity import _sha

SCHEMA = "progeny-scientific-benchmark-publication-v1"
FIELDS = ("query_id", "aspect", "go_id", "status")
ASPECTS = ("F", "P", "C")
STATUSES = ("EVAL", "SKIP", "NEUTRAL")
EVENTS = ("NOVEL", "CONFIRMATION")


def _table(path: Path, fields: tuple[str, ...], records) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(records)


_ROLE_RECEIPTS = ("exact", "ledger", "projection", "lookup")
_COMMON_RECEIPTS = (
    "handoff",
    "b3",
    "workload",
    "alignment",
    "stage07",
    "m8",
    "m10c",
    "temporal",
)
_POLICY_RECEIPTS = frozenset(("stage07", "m8", "m10c", "temporal"))
_EXPECTED_RECEIPTS = frozenset(
    f"{stage}:{role}" for stage in _ROLE_RECEIPTS for role in ("START", "END")
) | frozenset(f"{stage}:COMMON" for stage in _COMMON_RECEIPTS)


def _verify_certificate_receipts(run: Path, data: dict) -> None:
    receipts = data.get("receipts")
    if not isinstance(receipts, dict) or set(receipts) != _EXPECTED_RECEIPTS:
        raise ValueError("Scientific certificate has incorrect receipt keys")
    canonical = run / "canonical"
    namespaces = {}
    for name, receipt in sorted(receipts.items()):
        if not isinstance(receipt, dict) or set(receipt) != {"path", "sha256"}:
            raise ValueError(f"Malformed certified receipt: {name}")
        stage, role = name.split(":", 1)
        kind = "policy" if stage in _POLICY_RECEIPTS else "discovery"
        path_value = receipt["path"]
        digest = receipt["sha256"]
        if not isinstance(path_value, str) or not isinstance(digest, str):
            raise ValueError(f"Invalid certified receipt metadata: {name}")
        path = Path(path_value)
        if not path.is_absolute():
            raise ValueError(f"Nonabsolute certified receipt: {name}")
        try:
            relative = path.relative_to(canonical)
        except ValueError as exc:
            raise ValueError(f"Receipt outside canonical run: {name}") from exc
        parts = relative.parts
        expected_file = (
            f"{role}.snakemake.done" if role != "COMMON" else f"{stage}.snakemake.done"
        )
        expected_length = 3 if role != "COMMON" else 2
        if (
            len(parts) != expected_length
            or not parts[0].startswith(f"v2-{kind}-")
            or len(parts[0]) <= len(f"v2-{kind}-")
            or parts[-1] != expected_file
            or (role != "COMMON" and parts[1] != stage)
        ):
            raise ValueError(f"Unexpected certified receipt location: {name}")
        if kind in namespaces and namespaces[kind] != parts[0]:
            raise ValueError(f"Mixed scientific namespaces in receipt: {name}")
        namespaces[kind] = parts[0]
        try:
            if path.resolve(strict=True) != path:
                raise ValueError(f"Symlinked certified receipt path: {name}")
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"Missing certified receipt: {name}") from exc
        if _sha(_regular(path)) != digest:
            raise ValueError(f"Scientific receipt checksum mismatch: {name}")


def _read_certificate(run: Path) -> Path:
    records = list((run / "verification").glob("*.json"))
    matches = []
    for path in records:
        data = _json(path)
        if (
            data.get("schema") == "progeny-canonical-v2-fresh-completion-v1"
            and data.get("status") == "PASS"
            and data.get("canonical_publications") == 16
            and isinstance(data.get("receipts"), dict)
            and len(data["receipts"]) == 16
            and path.stem == data.get("content_identity_sha256")
        ):
            matches.append((path, data))
    if len(matches) != 1:
        raise ValueError("Exactly one certified 16-receipt completion is required")
    certificate, content = matches[0]
    _verify_certificate_receipts(run, content)
    return certificate


def _verify_existing(destination: Path) -> Path:
    manifest = _json(destination / "manifest.json")
    if manifest.get("schema") != SCHEMA or manifest.get("status") != "PUBLISHED":
        raise ValueError("Existing user benchmark is not a valid publication")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        raise ValueError("Existing benchmark has no output inventory")
    if any(
        not isinstance(name, str)
        or not name
        or name == "manifest.json"
        or Path(name).name != name
        for name in outputs
    ):
        raise ValueError("Existing benchmark has unsafe output names")
    actual = {member.name for member in destination.iterdir()}
    if actual != set(outputs) | {"manifest.json"}:
        raise ValueError("Existing benchmark output inventory mismatch")
    if any(
        member.is_symlink() or not member.is_file() for member in destination.iterdir()
    ):
        raise ValueError("Existing benchmark contains unsafe output members")
    for section in ("inputs", "outputs"):
        for name, item in manifest[section].items():
            path = Path(item["path"]) if section == "inputs" else destination / name
            if _sha(_regular(path)) != item["sha256"]:
                raise ValueError(f"Published {section} checksum mismatch: {name}")
            if path.stat().st_size != item["bytes"]:
                raise ValueError(f"Published {section} size mismatch: {name}")
    return destination


def _html_report(summary: dict) -> str:
    esc = html.escape
    overview = summary["overview"]
    aspects = summary["aspects"]
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{esc(str(v))}</td>"
            for v in (
                aspect,
                aspects[aspect]["target_aspects"],
                aspects[aspect]["EVAL"],
                aspects[aspect]["SKIP"],
                aspects[aspect]["NEUTRAL"],
                aspects[aspect]["NOVEL"],
                aspects[aspect]["CONFIRMATION"],
                aspects[aspect]["DIRECT_EVAL"],
            )
        )
        + "</tr>"
        for aspect in ASPECTS
    )
    species_rows = "".join(
        "<tr>" + "".join(f"<td>{esc(str(value))}</td>" for value in row) + "</tr>"
        for row in summary["top_species"]
    )
    return (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<title>PROGENY scientific benchmark</title>"
        "<style>body{font:16px/1.5 system-ui;max-width:1050px;"
        "margin:2em auto;padding:0 1.5em}table{border-collapse:collapse}"
        "td,th{padding:8px;border:1px solid #bbb}"
        "code{overflow-wrap:anywhere}</style>"
        "<h1>PROGENY scientific benchmark</h1>"
        "<p>Canonical science: certified PASS. This post-run publication "
        "does not compute predictor metrics.</p>"
        f"<p>Input targets: {overview['input_targets']:,}; evaluable proteins: "
        f"{overview['evaluable_targets']:,}; eligible target-aspects: "
        f"{overview['target_aspects']:,}.</p>"
        "<table><tr><th>GO aspect</th><th>Target-aspects</th>"
        "<th>EVAL</th><th>SKIP</th><th>NEUTRAL</th>"
        "<th>NOVEL</th><th>CONFIRMATION</th><th>Direct END EVAL</th></tr>"
        + rows
        + "</table><h2>Target species: leading 50</h2>"
        "<table><tr><th>NCBI species TaxID</th><th>Input targets</th>"
        "<th>Distinct evaluable targets</th></tr>"
        + species_rows
        + "</table><p>Complete per-species/aspect statistics: "
        "<a href='species_statistics.tsv'>species_statistics.tsv</a>.</p>"
        "<h2>Knowledge classes</h2>"
        "<p>NK/LK/PK require verified target-specific experimental START "
        "annotations. They are NOT inferred from transferred donor GO; "
        "the present publication marks cohorts UNCLASSIFIED.</p>"
        "<h2>Files and evaluation rules</h2><p>See "
        "<a href='README.md'>README.md</a>, "
        "<a href='EVALUATION_LEGEND.md'>EVALUATION_LEGEND.md</a>, "
        "<a href='target_cohorts.tsv'>target_cohorts.tsv</a>, "
        "<a href='species_statistics.tsv'>species_statistics.tsv</a> "
        "and <a href='benchmark_terms.tsv'>benchmark_terms.tsv</a>.</p>"
        "</html>"
    )


LEGEND = """# PROGENY: benchmark evaluation semantics

The `query_id` is the original user's FASTA identifier (first token before
whitespace). The exported FASTA restores each entire original header.
Internal `T000...` IDs are only computational identities.

Each row of `benchmark_terms.tsv` is a propagated GO term for a single
`(query_id, aspect)` that has at least one EVAL term. The GO aspect is one
of `F` (MF), `P` (BP), or `C` (CC).

- **EVAL**: scored positive truth. Above-threshold prediction => TP;
  absent prediction => FN.
- **SKIP**: prior-known or not-scorable annotation. Exclude from TP/FP/FN;
  it is not a true negative.
- **NEUTRAL**: conflicting or temporally ambiguous annotation. Exclude from
  TP/FP/FN; keep separate from SKIP for scientific auditing.
- **Other valid GO prediction**: if the target/aspect is eligible and the
  predicted term is within the approved GO universe after exclusions, a
  prediction not matching EVAL/SKIP/NEUTRAL is an *operational* FP, not
  proof that the biological function is absent.
- **NOT** is audit evidence, not an automatically constructed TN class.
- **No EVAL in an aspect**: target/aspect is outside that aspect's scoring
  denominator, even if the target is evaluable in a different aspect.

Evaluator order: validate predictions and IDs; merge duplicate term scores
using max; propagate scores to GO ancestors under the pinned relation policy;
exclude roots/out-of-universe terms; apply SKIP/NEUTRAL per target/aspect;
then compute TP/FP/FN. A masked intermediate term must not interrupt score
propagation. Report Fmax per ontology and cohort using one global threshold
per method/aspect/stratum; full evaluation includes eligible targets with no
predictions in recall. Partial evaluation is secondary and named explicitly.
Smin requires separately certified, pinned information accretion weights.
No biological TN is inferred from missing GO assertions.

`NOVEL` and `CONFIRMATION` describe individual temporal EVAL events; they
are NOT synonymous with NK/LK/PK target knowledge classes. `temporal_events.tsv`
contains direct-END events; `term_audit.tsv` covers all EVAL reasons,
including GO-propagated terms.

**Knowledge classification status:** This edition intentionally reports
`UNCLASSIFIED`. A true CAFA-style NK/LK/PK assignment requires independent
verification of START experimental annotations *directly attributed to the
original target*. GO transferred from a homolog is insufficient. Do not
interpret UNCLASSIFIED as NK, and do not calculate NK/LK/PK metric strata
from this publication until a certified classification is added.
"""


README = """# PROGENY certified user benchmark

This directory was published **after** the independent canonical 16-receipt
scientific completion certificate. It is independent of Stage 07/M8/M10c/
Temporal and never modifies their scientific publications.

- `ground_truth_targets.fasta`: only targets with >=1 EVAL; original **full**
  FASTA headers and exact sequences restored and SHA-256 checked.
- `benchmark_terms.tsv`: `query_id,aspect,go_id,status` for propagated
  EVAL/SKIP/NEUTRAL annotations associated with eligible target-aspects.
- `skip_terms.tsv`, `neutral_terms.tsv`: convenience filtered copies.
- `target_aspects.tsv`: eligible target-aspects and their status counts.
- `target_identity_map.tsv`: all accepted input proteins, original ID,
  internal ID, original and resolved species TaxIDs, original header.
- `non_evaluable_targets.tsv`: original targets with no EVAL in any aspect.
- `target_cohorts.tsv`: one row per evaluated target-aspect with species,
  counts, event details and the explicit `UNCLASSIFIED` knowledge flag.
- `aspect_statistics.tsv`, `species_statistics.tsv`, `go_frequency.tsv`:
  machine-readable scientific collector summaries.
- `evidence_by_release.tsv`: START/END evidence-code and polarity inventory;
  requires both certified M8 source inventories.
- `term_audit.tsv`, `temporal_events.tsv`, `negative_terms.tsv`: scientific
  reasons, direct events and negative-assertion audits.
- `statistics.json`, `report.html`: overview and human-readable report.
- `EVALUATION_LEGEND.md`: required scoring and mask semantics.
- `manifest.json`: output SHA-256 and exact upstream input SHA-256.

`query_id` is the token before the first whitespace in the original header;
full original headers are retained in `ground_truth_targets.fasta`. A header
like `>sp P02397 example` produces ID `sp`, **not** `P02397`; ID collisions
are rejected by PROGENY input validation. The supported UniProt accession
form is a separately declared import mode, not inferred from free text.

A protein may be evaluable in F and not in P or C. Species statistics use
*target* species TaxID, not the species of annotation donors. Species and
aspect counts must not be summed to estimate distinct protein counts.
No unobserved GO assertion is assumed a biological true negative.
"""


def publish_scientific_benchmark(dataset: Path, run: Path) -> Path:
    """Publish user benchmark exactly once, retaining the canonical run as-is."""
    dataset = dataset.resolve(strict=True)
    run = run.resolve(strict=True)
    certificate = _read_certificate(run)
    certificate_data = _json(certificate)
    temporal_roots = sorted((run / "canonical").glob("v2-policy-*/temporal"))
    if len(temporal_roots) != 1:
        raise ValueError("Expected exactly one canonical temporal bundle")
    temporal = temporal_roots[0]
    temporal_receipt = _regular(temporal.parent / "temporal.snakemake.done")
    certified = certificate_data["receipts"].get("temporal:COMMON")
    if (
        not isinstance(certified, dict)
        or certified.get("path") != str(temporal_receipt)
        or certified.get("sha256") != _sha(temporal_receipt)
    ):
        raise ValueError("Temporal receipt is not the certified temporal receipt")
    source = _verify_member_manifest(
        temporal, (*TEMPORAL_FILES, "duplicate_targets.tsv")
    )
    headers = _validate_headers(dataset)
    groups = _canonical_to_user(dataset, temporal, headers)
    if source.get("source_target_count") != len(headers):
        raise ValueError("Input target cardinality differs from temporal publication")

    destination = run / "results/benchmark"
    if destination.is_symlink():
        raise ValueError("Refusing symlink destination")
    if destination.exists():
        return _verify_existing(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".scientific-benchmark-", dir=destination.parent)
    )
    try:
        _write_publication(
            staging=staging,
            dataset=dataset,
            run=run,
            temporal=temporal,
            source=source,
            certificate=certificate,
            headers=headers,
            groups=groups,
        )
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("Benchmark destination appeared during publication")
        os.rename(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination


def _write_publication(
    *,
    staging: Path,
    dataset: Path,
    run: Path,
    temporal: Path,
    source: dict,
    certificate: Path,
    headers: dict,
    groups: dict,
) -> None:
    mapping = {
        row["target_id"]: row for row in _rows(dataset / "targets/targets.mapping.tsv")
    }
    species_by_target = {
        row["target_id"]: row["species_taxid"]
        for row in _rows(run / "work/pipeline-v2/START/02B/02B_target_taxonomy.tsv")
    }
    if set(mapping) != set(headers) or set(headers) - set(species_by_target):
        raise ValueError("User IDs and target taxonomy do not reconcile")
    if any(
        not species_by_target[target].isascii()
        or not species_by_target[target].isdecimal()
        for target in headers
    ):
        raise ValueError("Target species TaxID cannot be resolved for the report")
    original_id = {key: value["source_id"] for key, value in headers.items()}
    by_user = {value: key for key, value in original_id.items()}
    if len(by_user) != len(headers):
        raise ValueError("Duplicate original FASTA ID")
    input_species = Counter(species_by_target[target] for target in headers)
    eligible = set()
    eligible_aspects: dict[tuple[str, str], dict] = {}
    status_totals = Counter()
    aspect_totals = Counter()
    species_totals = Counter()
    go_frequency = Counter()
    per_target_status = Counter()
    novel = Counter()
    direct = Counter()

    with (
        (staging / "benchmark_terms.tsv").open(
            "x", encoding="utf-8", newline=""
        ) as target,
        (staging / "skip_terms.tsv").open("x", encoding="utf-8", newline="") as skipped,
        (staging / "neutral_terms.tsv").open(
            "x", encoding="utf-8", newline=""
        ) as neutral,
    ):
        writers = [
            csv.writer(h, delimiter="\t", lineterminator="\n")
            for h in (target, skipped, neutral)
        ]
        for writer in writers:
            writer.writerow(FIELDS)
        for record in _rows(temporal / "benchmark_terms.tsv"):
            status = record["status"]
            aspect = record["aspect"]
            if status not in STATUSES or aspect not in ASPECTS:
                raise ValueError("Unknown benchmark status or GO aspect")
            if not record["go_id"].startswith("GO:"):
                raise ValueError("Malformed GO identifier")
            try:
                targets = groups[record["query_id"]]
            except KeyError as exc:
                raise ValueError("Unknown original target identity") from exc
            for internal in sorted(targets):
                user = original_id[internal]
                values = (user, aspect, record["go_id"], status)
                writers[0].writerow(values)
                if status == "SKIP":
                    writers[1].writerow(values)
                elif status == "NEUTRAL":
                    writers[2].writerow(values)
                if status == "EVAL":
                    eligible.add(internal)
                taxid = species_by_target[internal]
                status_totals[status] += 1
                aspect_totals[(aspect, status)] += 1
                species_totals[(taxid, aspect, status)] += 1
                go_frequency[(aspect, record["go_id"], status)] += 1
                per_target_status[(user, aspect, status)] += 1

    if source.get("identical_duplicate_target_aliases", 0) == 0:
        for status in STATUSES:
            expected = source.get("counts", {}).get(f"benchmark_{status}", 0)
            if status_totals[status] != expected:
                raise ValueError(
                    f"{status} cardinality mismatch: "
                    f"{status_totals[status]} != {expected}"
                )

    mapped_files = (
        "target_aspects.tsv",
        "temporal_events.tsv",
        "term_audit.tsv",
        "negative_terms.tsv",
    )
    for name in mapped_files:
        with (staging / name).open("x", encoding="utf-8", newline="") as dest:
            reader = _rows(temporal / name)
            first = next(reader, None)
            with _regular(temporal / name).open(
                encoding="utf-8", newline=""
            ) as input_handle:
                header = tuple(
                    csv.DictReader(input_handle, delimiter="\t").fieldnames or ()
                )
            if not header or "query_id" not in header:
                raise ValueError(f"Invalid mapped temporal TSV: {name}")
            writer = csv.DictWriter(
                dest, fieldnames=header, delimiter="\t", lineterminator="\n"
            )
            writer.writeheader()
            for row in [first] if first is not None else []:
                _map_row(row, writer, groups, original_id)
                _accumulate(
                    name,
                    row,
                    groups,
                    original_id,
                    species_by_target,
                    eligible_aspects,
                    novel,
                    direct,
                )
            for row in reader:
                _map_row(row, writer, groups, original_id)
                _accumulate(
                    name,
                    row,
                    groups,
                    original_id,
                    species_by_target,
                    eligible_aspects,
                    novel,
                    direct,
                )

    for (user, aspect), item in eligible_aspects.items():
        if int(item["eval_terms"]) <= 0:
            raise ValueError("Published target aspect has no EVAL")
        for status in STATUSES:
            if (
                int(item[status.lower() + "_terms"])
                != per_target_status[(user, aspect, status)]
            ):
                raise ValueError("Per-target status cardinality mismatch")
    for user, aspect, _status in per_target_status:
        if (user, aspect) not in eligible_aspects:
            raise ValueError("Benchmark term outside an eligible target/aspect")
    for status in STATUSES:
        if (
            sum(
                int(row[status.lower() + "_terms"]) for row in eligible_aspects.values()
            )
            != status_totals[status]
        ):
            raise ValueError("target_aspects counts disagree with terms")
    if (
        len(eligible_aspects)
        != source.get("counts", {}).get(
            "eligible_target_aspects", len(eligible_aspects)
        )
        and source.get("identical_duplicate_target_aliases", 0) == 0
    ):
        raise ValueError("Eligible target-aspect count differs from manifest")

    for (key, event), count in novel.items():
        if key not in eligible_aspects or event not in EVENTS or count <= 0:
            raise ValueError("Audit event outside eligible target/aspect")
    for (key, event), count in direct.items():
        if key not in eligible_aspects or event not in EVENTS:
            raise ValueError("Direct event outside eligible target/aspect")
        if count > novel[(key, event)]:
            raise ValueError("More direct EVAL than total EVAL for a term event")
    if sum(novel.values()) != status_totals["EVAL"]:
        raise ValueError("NOVEL+CONFIRMATION must partition EVAL")

    _fasta_targets(
        dataset / "targets/targets.fasta",
        eligible,
        headers,
        staging / "ground_truth_targets.fasta",
    )
    _table(
        staging / "target_identity_map.tsv",
        (
            "original_id",
            "internal_target_id",
            "original_header",
            "original_taxid",
            "species_taxid",
            "sequence_sha256",
            "benchmark_status",
        ),
        (
            {
                "original_id": original_id[target],
                "internal_target_id": target,
                "original_header": value["original_header"],
                "original_taxid": mapping[target]["raw_taxid"],
                "species_taxid": species_by_target[target],
                "sequence_sha256": value["sequence_sha256"],
                "benchmark_status": "EVALUABLE" if target in eligible else "NO_EVAL",
            }
            for target, value in sorted(headers.items())
        ),
    )
    _table(
        staging / "non_evaluable_targets.tsv",
        ("original_id", "internal_target_id", "reason"),
        (
            {
                "original_id": original_id[target],
                "internal_target_id": target,
                "reason": "NO_EVAL_IN_ANY_ASPECT",
            }
            for target in sorted(headers)
            if target not in eligible
        ),
    )
    _table(
        staging / "target_cohorts.tsv",
        (
            "original_id",
            "internal_target_id",
            "species_taxid",
            "aspect",
            "knowledge_class",
            "eval_terms",
            "skip_terms",
            "neutral_terms",
            "known_start_score",
            "known_start_non_score",
            "novel",
            "confirmation",
            "direct_novel",
            "direct_confirmation",
        ),
        (
            _cohort(user, aspect, row, by_user[user], species_by_target, novel, direct)
            for (user, aspect), row in sorted(eligible_aspects.items())
        ),
    )
    species_evaluable = defaultdict(set)
    species_aspect_targets = Counter()
    aspect_targets = defaultdict(set)
    for user, aspect in eligible_aspects:
        internal = by_user[user]
        species_evaluable[species_by_target[internal]].add(user)
        aspect_targets[aspect].add(user)
        species_aspect_targets[(species_by_target[internal], aspect)] += 1
    _table(
        staging / "aspect_statistics.tsv",
        (
            "aspect",
            "target_aspects",
            "eval",
            "skip",
            "neutral",
            "novel",
            "confirmation",
            "direct_novel",
            "direct_confirmation",
        ),
        (
            {
                "aspect": aspect,
                "target_aspects": len(aspect_targets[aspect]),
                "eval": aspect_totals[(aspect, "EVAL")],
                "skip": aspect_totals[(aspect, "SKIP")],
                "neutral": aspect_totals[(aspect, "NEUTRAL")],
                "novel": sum(
                    v
                    for (key, label), v in novel.items()
                    if key[1] == aspect and label == "NOVEL"
                ),
                "confirmation": sum(
                    v
                    for (key, label), v in novel.items()
                    if key[1] == aspect and label == "CONFIRMATION"
                ),
                "direct_novel": sum(
                    v
                    for (key, label), v in direct.items()
                    if key[1] == aspect and label == "NOVEL"
                ),
                "direct_confirmation": sum(
                    v
                    for (key, label), v in direct.items()
                    if key[1] == aspect and label == "CONFIRMATION"
                ),
            }
            for aspect in ASPECTS
        ),
    )
    species_events = Counter()
    species_direct = Counter()
    for ((user, aspect), event), count in novel.items():
        species_events[(species_by_target[by_user[user]], aspect, event)] += count
    for ((user, aspect), event), count in direct.items():
        species_direct[(species_by_target[by_user[user]], aspect, event)] += count
    _table(
        staging / "species_statistics.tsv",
        (
            "species_taxid",
            "aspect",
            "input_targets",
            "evaluable_unique_targets",
            "evaluable_targets",
            "eval",
            "skip",
            "neutral",
            "novel",
            "confirmation",
            "direct_novel",
            "direct_confirmation",
            "knowledge_class",
        ),
        (
            {
                "species_taxid": taxid,
                "aspect": aspect,
                "input_targets": input_species[taxid],
                "evaluable_unique_targets": len(species_evaluable[taxid]),
                "evaluable_targets": species_aspect_targets[(taxid, aspect)],
                "eval": species_totals[(taxid, aspect, "EVAL")],
                "skip": species_totals[(taxid, aspect, "SKIP")],
                "neutral": species_totals[(taxid, aspect, "NEUTRAL")],
                **{
                    event.lower(): species_events[(taxid, aspect, event)]
                    for event in EVENTS
                },
                **{
                    "direct_" + event.lower(): species_direct[(taxid, aspect, event)]
                    for event in EVENTS
                },
                "knowledge_class": "UNCLASSIFIED",
            }
            for taxid in sorted(input_species, key=int)
            for aspect in ASPECTS
        ),
    )
    _table(
        staging / "go_frequency.tsv",
        ("aspect", "go_id", "status", "target_associations"),
        (
            {"aspect": a, "go_id": go, "status": status, "target_associations": n}
            for (a, go, status), n in sorted(go_frequency.items())
        ),
    )
    evidence_rows = []
    m8_bundle = temporal.parent / "m8"
    evidence_availability = "NOT_AVAILABLE"
    m8_summary_path = m8_bundle / "08_collection_summary.json"
    if m8_summary_path.is_file():
        m8_summary = _json(m8_summary_path)
        for role in ("START", "END"):
            file = m8_bundle / f"08_{role.lower()}_evidence_inventory.tsv"
            if not file.is_file() or file.is_symlink():
                raise ValueError(f"Missing published M8 evidence inventory: {role}")
            rows = list(_rows(file))
            for row in rows:
                if row["release"] != m8_summary["by_role"][role]["release"]:
                    raise ValueError("M8 evidence inventory release mismatch")
                evidence_rows.append(row)
            if (
                sum(int(row["source_rows"]) for row in rows)
                != (m8_summary["by_role"][role]["retrieved_source_rows"])
            ):
                raise ValueError("M8 evidence source-row totals disagree")
            if (
                sum(int(row["association_links"]) for row in rows)
                != (m8_summary["by_role"][role]["annotation_links"])
            ):
                raise ValueError("M8 evidence association-link totals disagree")
        evidence_availability = "CERTIFIED_M8_INVENTORY"
    _table(
        staging / "evidence_by_release.tsv",
        (
            "release",
            "evidence_code",
            "aspect",
            "polarity",
            "source_rows",
            "association_links",
        ),
        (
            dict(row)
            for row in sorted(
                evidence_rows,
                key=lambda row: (
                    row["release"],
                    row["evidence_code"],
                    row["aspect"],
                    row["polarity"],
                ),
            )
        ),
    )
    (staging / "EVALUATION_LEGEND.md").write_text(LEGEND, encoding="utf-8")
    (staging / "README.md").write_text(README, encoding="utf-8")
    aspects_report = {
        aspect: {
            "target_aspects": len(aspect_targets[aspect]),
            **{status: aspect_totals[(aspect, status)] for status in STATUSES},
            **{
                event: sum(
                    v
                    for (key, label), v in novel.items()
                    if key[1] == aspect and label == event
                )
                for event in EVENTS
            },
            "DIRECT_EVAL": sum(v for (key, _), v in direct.items() if key[1] == aspect),
        }
        for aspect in ASPECTS
    }
    summary = {
        "schema": SCHEMA,
        "classification": "UNCLASSIFIED_PENDING_DIRECT_START_EVIDENCE_AUDIT",
        "ontology_aspects": list(ASPECTS),
        "overview": {
            "input_targets": len(headers),
            "evaluable_targets": len(eligible),
            "target_aspects": len(eligible_aspects),
            **{status: status_totals[status] for status in STATUSES},
            **{
                event: sum(v for (_, label), v in novel.items() if label == event)
                for event in EVENTS
            },
            "direct_end_eval": sum(direct.values()),
        },
        "aspects": aspects_report,
        "species_target_count": len(input_species),
        "top_species": [
            [taxid, input_species[taxid], len(species_evaluable[taxid])]
            for taxid in sorted(
                input_species,
                key=lambda taxid: (-len(species_evaluable[taxid]), taxid),
            )[:50]
        ],
        "evidence_inventory_status": evidence_availability,
        "documentary_lookahead_audit": "NOT_MEASURABLE_FROM_AGGREGATES",
        "canonical_certificate": str(certificate),
        "canonical_temporal_sha256": _sha(temporal / "manifest.json"),
    }
    for stage, filename in (
        ("stage07", "07_canonical_scientific_summary.json"),
        ("m8", "08_collection_summary.json"),
        ("m10c", "manifest.json"),
    ):
        src = temporal.parent / stage / filename
        if src.is_file() and not src.is_symlink():
            summary[stage] = _json(src)
    (staging / "statistics.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (staging / "report.html").write_text(_html_report(summary), encoding="utf-8")
    input_paths = {
        "canonical_certificate": certificate,
        "temporal_manifest": temporal / "manifest.json",
        "original_headers": dataset / "identity/original_headers.tsv",
        "original_header_manifest": dataset / "identity/manifest.json",
        "stage00_mapping": dataset / "targets/targets.mapping.tsv",
        "canonical_target_fasta": dataset / "targets/targets.fasta",
        "target_taxonomy_start": run
        / "work/pipeline-v2/START/02B/02B_target_taxonomy.tsv",
    }
    for stage, filename in (
        ("stage07", "07_canonical_scientific_summary.json"),
        ("m8", "08_collection_summary.json"),
        ("m10c", "manifest.json"),
    ):
        path = temporal.parent / stage / filename
        if path.is_file() and not path.is_symlink():
            input_paths[stage + "_summary"] = path
    if evidence_availability == "CERTIFIED_M8_INVENTORY":
        for role in ("START", "END"):
            input_paths["evidence_inventory_" + role] = (
                temporal.parent / "m8" / f"08_{role.lower()}_evidence_inventory.tsv"
            )
    output_files = sorted(path for path in staging.rglob("*") if path.is_file())
    manifest = {
        "schema": SCHEMA,
        "status": "PUBLISHED",
        "canonical_completion": "PASS",
        "classification": summary["classification"],
        "inputs": {
            name: {
                "path": str(path),
                "sha256": _sha(_regular(path)),
                "bytes": path.stat().st_size,
            }
            for name, path in sorted(input_paths.items())
        },
        "outputs": {
            str(path.relative_to(staging)): {
                "sha256": _sha(path),
                "bytes": path.stat().st_size,
            }
            for path in output_files
        },
    }
    (staging / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _map_row(row: dict, writer, groups: dict, original_id: dict) -> None:
    if row["query_id"] not in groups:
        raise ValueError("Unknown original query in temporal audit")
    for internal in sorted(groups[row["query_id"]]):
        item = dict(row)
        item["query_id"] = original_id[internal]
        if "target_id" in item:
            item["target_id"] = original_id[internal]
        writer.writerow(item)


def _accumulate(
    name: str,
    row: dict,
    groups: dict,
    original_id: dict,
    species_by_target: dict,
    eligible_aspects: dict,
    novel: Counter,
    direct: Counter,
) -> None:
    del species_by_target
    if name == "target_aspects.tsv":
        for internal in sorted(groups[row["query_id"]]):
            key = original_id[internal], row["aspect"]
            if key in eligible_aspects:
                raise ValueError("Duplicate eligible target-aspect")
            eligible_aspects[key] = dict(row)
    elif name == "term_audit.tsv" and row["status"] == "EVAL":
        if row["reason"] not in EVENTS:
            raise ValueError("Unknown EVAL scientific reason")
        for internal in sorted(groups[row["query_id"]]):
            novel[((original_id[internal], row["aspect"]), row["reason"])] += 1
    elif (
        name == "temporal_events.tsv"
        and row["status"] == "EVAL"
        and row["event"] in EVENTS
    ):
        for internal in sorted(groups[row["query_id"]]):
            direct[((original_id[internal], row["aspect"]), row["event"])] += 1


def _cohort(
    user: str,
    aspect: str,
    row: dict,
    internal: str,
    species: dict,
    novel: Counter,
    direct: Counter,
) -> dict:
    return {
        "original_id": user,
        "internal_target_id": internal,
        "species_taxid": species[internal],
        "aspect": aspect,
        "knowledge_class": "UNCLASSIFIED",
        **{
            key: row[key]
            for key in (
                "eval_terms",
                "skip_terms",
                "neutral_terms",
                "known_start_score",
                "known_start_non_score",
            )
        },
        "novel": novel[((user, aspect), "NOVEL")],
        "confirmation": novel[((user, aspect), "CONFIRMATION")],
        "direct_novel": direct[((user, aspect), "NOVEL")],
        "direct_confirmation": direct[((user, aspect), "CONFIRMATION")],
    }
