"""Post-publication user-ID benchmark bundle and offline HTML summary.

This adapter never changes Stage 07, M8, M10c or temporal publications.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from progeny.alpha_identity import HEADER_FIELDS, _sha

SCHEMA = "progeny-user-benchmark-export-v1"
ASPECT_NAMES = {"F": "MF", "P": "BP", "C": "CC"}
TEMPORAL_FILES = (
    "benchmark_terms.tsv",
    "target_aspects.tsv",
    "temporal_events.tsv",
    "term_audit.tsv",
    "negative_terms.tsv",
)


def _regular(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or symlinked scientific input: {path}")
    return path


def _json(path: Path) -> dict:
    value = json.loads(_regular(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Invalid manifest: {path}")
    return value


def _rows(path: Path):
    with _regular(path).open(encoding="utf-8", newline="") as stream:
        yield from csv.DictReader(stream, delimiter="\t")


def _read_all(path: Path) -> list[dict]:
    return list(_rows(path))


def _write_table(path: Path, columns: tuple[str, ...], rows) -> None:
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=columns, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _verify_member_manifest(path: Path, names: tuple[str, ...]) -> dict:
    manifest = _json(path / "manifest.json")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("Temporal manifest has no output integrity ledger")
    for name in names:
        item = outputs.get(name)
        file = _regular(path / name)
        if (
            not isinstance(item, dict)
            or item.get("sha256") != _sha(file)
            or item.get("bytes") != file.stat().st_size
        ):
            raise ValueError(f"Published temporal payload checksum mismatch: {name}")
    return manifest


def _validate_headers(dataset: Path) -> dict[str, dict]:
    identity = dataset / "identity"
    meta = _json(identity / "manifest.json")
    if meta.get("schema") != "progeny-original-fasta-headers-v1":
        raise ValueError("Original FASTA header ledger is missing")
    path = identity / "original_headers.tsv"
    if (
        _sha(path) != meta["original_headers_sha256"]
        or _sha(dataset / "targets/targets.mapping.tsv")
        != meta["stage00_mapping_sha256"]
    ):
        raise ValueError("Original FASTA identity ledger was modified")
    mapping = {
        row["target_id"]: row for row in _rows(dataset / "targets/targets.mapping.tsv")
    }
    headers = {}
    ids = set()
    for row in _rows(path):
        if set(row) != set(HEADER_FIELDS):
            raise ValueError("Unexpected original-header schema")
        target = row["target_id"]
        if target in headers or target not in mapping:
            raise ValueError("Duplicate or foreign original-header target")
        first = mapping[target]
        if any(
            row[key] != first[key]
            for key in ("source_record", "source_id", "sequence_sha256")
        ):
            raise ValueError("Original FASTA provenance mismatch")
        if row["source_id"] in ids or "\n" in row["original_header"]:
            raise ValueError("Duplicate or invalid original FASTA ID")
        ids.add(row["source_id"])
        headers[target] = row
    if set(headers) != set(mapping):
        raise ValueError("Original FASTA/header mapping cardinality mismatch")
    if len(headers) != meta["accepted_targets"]:
        raise ValueError("Original FASTA target count mismatch")
    return headers


def _canonical_to_user(dataset: Path, temporal: Path, headers: dict) -> dict:
    metadata = {}
    for row in _rows(dataset / "targets/targets.metadata.tsv"):
        target = row["target_id"]
        if target in metadata or target not in headers:
            raise ValueError("Invalid metadata target")
        metadata[target] = row
    if set(metadata) != set(headers):
        raise ValueError("Metadata identity mismatch")
    query_groups = defaultdict(list)
    for target, row in metadata.items():
        query_groups[row["uniprot_accession"] or target].append(target)
    ledger = _read_all(temporal / "duplicate_targets.tsv")
    observed = {
        (row["query_id"], row["canonical_target_id"], row["duplicate_target_id"])
        for row in ledger
    }
    expected = set()
    for query, targets in query_groups.items():
        if len(targets) > 1:
            canonical = min(targets)
            for target in targets:
                if target != canonical:
                    expected.add((query, canonical, target))
    if observed != expected:
        raise ValueError("Temporal alias ledger does not match original targets")
    return dict(query_groups)


def _release_statistics(run: Path) -> dict:
    result = {}
    for role in ("START", "END"):
        base = run / "work/pipeline-v2" / role
        summaries = {
            "uniprot_full": base / "01A_FULL/01A_full_v2.summary.json",
            "goa_normalized": base / "01B1/goa.stats.json",
        }
        result[role] = {}
        for name, path in summaries.items():
            data = _json(path)
            # Native UniProt counts live in `totals`; GOA is top-level.
            totals = data.get("totals", data)
            if not isinstance(totals, dict):
                raise ValueError(f"Unexpected release summary totals: {path}")
            counters = {
                key: value
                for key, value in totals.items()
                if type(value) is int
                and any(
                    part in key.lower()
                    for part in (
                        "count",
                        "records",
                        "rows",
                        "protein",
                        "sequence",
                        "annotation",
                        "accession",
                        "retained",
                        "rejected",
                    )
                )
            }
            if name == "uniprot_full":
                inputs = data.get("inputs", [])
                if isinstance(inputs, list) and len(inputs) == 2:
                    for label, item in zip(("sprot", "trembl"), inputs, strict=True):
                        if not isinstance(item, dict):
                            raise ValueError("Malformed UniProt source counters")
                        for key in (
                            "records_seen",
                            "records_written",
                            "records_skipped",
                        ):
                            if type(item.get(key)) is int:
                                counters[f"{label}_{key}"] = item[key]
            result[role][name] = counters
    return result


def _fasta_targets(path: Path, accepted: set[str], headers: dict, output: Path) -> int:
    seen = set()
    target: str | None = None
    residues = []
    exported = 0

    def flush(handle):
        nonlocal exported
        if target is None or target not in accepted:
            return
        if target not in headers or target in seen:
            raise ValueError("Invalid canonical target FASTA identity")
        row = headers[target]
        seq = "".join(residues)
        if hashlib.sha256(seq.encode("ascii")).hexdigest() != row["sequence_sha256"]:
            raise ValueError(f"Original target sequence altered: {target}")
        handle.write(f">{row['original_header']}\n{seq}\n")
        seen.add(target)
        exported += 1

    with (
        _regular(path).open(encoding="ascii") as original,
        output.open("x", encoding="ascii", newline="\n") as exported_stream,
    ):
        for line in original:
            line = line.rstrip("\r\n")
            if line.startswith(">"):
                flush(exported_stream)
                target = line[1:]
                residues = []
            elif line:
                residues.append(line)
        flush(exported_stream)
    if seen != accepted:
        raise ValueError("Missing eligible FASTA target sequences")
    return exported


def _report_html(report: dict) -> str:
    def esc(value):
        return html.escape(str(value), quote=True)

    overview = report["overview"]
    cards = "".join(
        f"<div class='stat'><strong>{esc(value)}</strong><span>{esc(name)}</span></div>"
        for name, value in overview.items()
    )
    aspects = "".join(
        "<tr>"
        + "".join(
            f"<td>{esc(value)}</td>"
            for value in (
                ASPECT_NAMES[a],
                *(
                    report["aspects"][a][key]
                    for key in (
                        "evaluable_targets",
                        "unique_eval_go",
                        "eval_pairs",
                        "unique_skip_go",
                        "skip_pairs",
                        "novel",
                        "confirmation",
                    )
                ),
            )
        )
        + "</tr>"
        for a in ("F", "P", "C")
    )
    eval_species = dict(report["species_distribution"])
    species = "".join(
        f"<tr><td>{esc(taxid)}</td><td>{count}</td>"
        f"<td>{eval_species.get(taxid, 0)}</td></tr>"
        for taxid, count in report["species_input_distribution"][:100]
    )
    classes_html = "".join(
        f"<tr><td>{esc(group)}</td><td>{esc(', '.join(codes))}</td></tr>"
        for group, codes in sorted(report["evidence_classes"].items())
    )
    release_html = ""
    for role, snapshots in report["release_statistics"].items():
        for source, counts in snapshots.items():
            release_html += f"<h3>{esc(role)} — {esc(source)}</h3><table>"
            release_html += "<tr><th>Producer-reported counter</th><th>Value</th></tr>"
            for key, value in sorted(counts.items()):
                release_html += f"<tr><td>{esc(key)}</td><td>{esc(value)}</td></tr>"
            release_html += "</table>"
    return (
        """<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>PROGENY benchmark report</title><style>
body{font:16px/1.5 system-ui,sans-serif;max-width:1080px;margin:auto;
padding:24px;color:#17212d;background:#fafbfc}h1,h2{line-height:1.2}
.statgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));
gap:12px}.stat{background:#edf3f7;padding:16px;border-radius:10px}
.stat strong{display:block;font-size:1.6em}.stat span{display:block}
table{width:100%;border-collapse:collapse;margin-bottom:22px}
th,td{border-bottom:1px solid #d6dce2;padding:8px;text-align:left}
a{color:#145e92}code{overflow-wrap:anywhere}
</style></head><body><h1>PROGENY ground-truth report</h1>
<p>Post-publication user-ID export. Scientific source outputs are not modified.
Non-observed GO annotations are not biological negatives.</p>
<h2>Target survival</h2><div class='statgrid'>"""
        + cards
        + """</div>
<h2>Ontology aspects</h2><table><tr><th>Aspect</th><th>Proteins with EVAL</th>
<th>Unique EVAL GO</th><th>EVAL protein-GO pairs</th><th>Unique SKIP GO</th>
<th>SKIP protein-GO pairs</th><th>NOVEL</th><th>CONFIRMATION</th>
</tr>"""
        + aspects
        + """</table>
<h2>Species (resolved species TaxID)</h2>
<p>Top 100 species by input targets; evaluable counts use original IDs.</p>
<table><tr><th>NCBI species TaxID</th><th>Stage 00 targets</th>
<th>Evaluable targets</th></tr>
"""
        + species
        + """</table>
<h2>Evidence-code classification for this benchmark</h2>
<table><tr><th>Class</th><th>Evidence codes</th></tr>"""
        + classes_html
        + """</table>
<h2>START / END input release summaries</h2>
<p>Original counters supplied by the canonical UniProt and GOA producers.
Universes and denominators are specific to each stage.</p>"""
        + release_html
        + """
<h2>Downloadable output files</h2><ul>"""
        + "".join(
            f"<li><a href='{esc(name)}'>{esc(name)}</a></li>"
            for name in (
                "ground_truth_targets.fasta",
                "benchmark_terms.tsv",
                "skip_terms.tsv",
                "target_aspects.tsv",
                "temporal_events.tsv",
                "term_audit.tsv",
                "negative_terms.tsv",
                "target_identity_map.tsv",
                "statistics.json",
                "manifest.json",
            )
        )
        + """</ul><p><strong>GO evaluation metrics are not part of this report.</strong>
The original internal target identifiers remain available in
<code>target_identity_map.tsv</code> and the canonical audit publications.</p>
</body></html>"""
    )


def export_benchmark(dataset: Path, run: Path) -> Path:
    """Publish a new immutable end-user bundle only after canonical completion."""
    dataset = dataset.resolve(strict=True)
    run = run.resolve(strict=True)
    roots = sorted((run / "canonical").glob("v2-policy-*/temporal"))
    if len(roots) != 1:
        raise ValueError("Expected exactly one canonical temporal publication")
    temporal = roots[0]
    if not _regular(temporal.parent / "temporal.snakemake.done"):
        raise ValueError("Canonical temporal DAG completion receipt is absent")
    source = _verify_member_manifest(
        temporal, (*TEMPORAL_FILES, "duplicate_targets.tsv")
    )
    headers = _validate_headers(dataset)
    groups = _canonical_to_user(dataset, temporal, headers)
    if source.get("source_target_count") != len(headers):
        raise ValueError("Temporal target cardinality mismatch")
    final = run / "results/benchmark"
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.is_symlink():
        raise ValueError("Existing benchmark bundle is symlinked")
    if final.exists():
        old = _json(final / "manifest.json")
        if old.get("schema") != SCHEMA or old.get("status") != "PUBLISHED":
            raise ValueError("Existing benchmark has no valid publication receipt")
        for item, metadata in old.get("outputs", {}).items():
            file = _regular(final / item)
            if (
                _sha(file) != metadata["sha256"]
                or file.stat().st_size != metadata["bytes"]
            ):
                raise ValueError("Existing exported file was modified")
        for item, metadata in old.get("sources", {}).items():
            file = _regular(Path(metadata["path"]))
            if _sha(file) != metadata["sha256"]:
                raise ValueError(f"Existing benchmark input changed: {item}")
        return final
    staging = Path(tempfile.mkdtemp(prefix=".benchmark-export-", dir=final.parent))
    try:
        source_by_id = {
            row["target_id"]: row
            for row in _rows(dataset / "targets/targets.mapping.tsv")
        }
        tax_by_id = {target: row["raw_taxid"] for target, row in source_by_id.items()}
        seen_queries = set()
        evaluable = set()
        aspects = {
            aspect: {
                "evaluable_targets": 0,
                "unique_eval_go": 0,
                "eval_pairs": 0,
                "unique_skip_go": 0,
                "skip_pairs": 0,
                "novel": 0,
                "confirmation": 0,
            }
            for aspect in ASPECT_NAMES
        }
        per_aspect_evaluable = defaultdict(set)
        distinct_eval_go = defaultdict(set)
        distinct_skip_go = defaultdict(set)
        for name in TEMPORAL_FILES:
            with (
                _regular(temporal / name).open(encoding="utf-8", newline="") as stream,
                (staging / name).open("x", encoding="utf-8", newline="") as target_file,
            ):
                reader = csv.DictReader(stream, delimiter="\t")
                columns = tuple(reader.fieldnames or ())
                if not columns or "query_id" not in columns:
                    raise ValueError(f"Malformed temporal output: {name}")
                writer = csv.DictWriter(
                    target_file,
                    fieldnames=columns,
                    delimiter="\t",
                    lineterminator="\n",
                )
                writer.writeheader()
                for record in reader:
                    query = record["query_id"]
                    if query not in groups:
                        raise ValueError("Unknown canonical temporal query ID")
                    seen_queries.add(query)
                    for internal in sorted(groups[query]):
                        user_id = headers[internal]["source_id"]
                        row = dict(record)
                        row["query_id"] = user_id
                        if "target_id" in row:
                            row["target_id"] = user_id
                        writer.writerow(row)
                        if name == "benchmark_terms.tsv":
                            status, aspect, go_id = (
                                row["status"],
                                row["aspect"],
                                row["go_id"],
                            )
                            if aspect not in aspects:
                                raise ValueError("Unexpected GO aspect")
                            if status == "EVAL":
                                evaluable.add(user_id)
                                per_aspect_evaluable[aspect].add(user_id)
                                distinct_eval_go[aspect].add(go_id)
                                aspects[aspect]["eval_pairs"] += 1
                            elif status == "SKIP":
                                distinct_skip_go[aspect].add(go_id)
                                aspects[aspect]["skip_pairs"] += 1
                            else:
                                raise ValueError("Unsupported benchmark status")
                        if name == "temporal_events.tsv":
                            event = row["event"]
                            if event == "NOVEL":
                                aspects[row["aspect"]]["novel"] += 1
                            if event == "CONFIRMATION":
                                aspects[row["aspect"]]["confirmation"] += 1
        for aspect, record in aspects.items():
            record["evaluable_targets"] = len(per_aspect_evaluable[aspect])
            record["unique_eval_go"] = len(distinct_eval_go[aspect])
            record["unique_skip_go"] = len(distinct_skip_go[aspect])

        with (
            (staging / "benchmark_terms.tsv").open(
                encoding="utf-8", newline=""
            ) as stream,
            (staging / "skip_terms.tsv").open(
                "x", encoding="utf-8", newline=""
            ) as target_file,
        ):
            reader = csv.DictReader(stream, delimiter="\t")
            writer = csv.DictWriter(
                target_file,
                fieldnames=reader.fieldnames,
                delimiter="\t",
                lineterminator="\n",
            )
            writer.writeheader()
            for row in reader:
                if row["status"] == "SKIP":
                    writer.writerow(row)
        original_to_internal = {
            row["source_id"]: target for target, row in headers.items()
        }
        _fasta_targets(
            dataset / "targets/targets.fasta",
            {original_to_internal[user] for user in evaluable},
            headers,
            staging / "ground_truth_targets.fasta",
        )
        _write_table(
            staging / "target_identity_map.tsv",
            (
                "original_id",
                "internal_target_id",
                "original_header",
                "ncbi_taxid",
                "benchmark_status",
                "sequence_sha256",
            ),
            (
                {
                    "original_id": header["source_id"],
                    "internal_target_id": target,
                    "original_header": header["original_header"],
                    "ncbi_taxid": tax_by_id[target],
                    "benchmark_status": (
                        "EVALUABLE" if header["source_id"] in evaluable else "NO_EVAL"
                    ),
                    "sequence_sha256": header["sequence_sha256"],
                }
                for target, header in sorted(headers.items())
            ),
        )
        with (staging / "target_identity_map.tsv").open(
            encoding="utf-8", newline=""
        ) as stream:
            records = csv.DictReader(stream, delimiter="\t")
            _write_table(
                staging / "non_evaluable_targets.tsv",
                ("original_id", "internal_target_id", "reason"),
                (
                    {
                        "original_id": row["original_id"],
                        "internal_target_id": row["internal_target_id"],
                        "reason": "NO_EVAL_IN_ANY_ASPECT",
                    }
                    for row in records
                    if row["benchmark_status"] == "NO_EVAL"
                ),
            )
        species_by_target = {}
        for row in _rows(run / "work/pipeline-v2/START/02B/02B_target_taxonomy.tsv"):
            species_by_target[row["target_id"]] = row["species_taxid"]
        if set(headers) - set(species_by_target):
            raise ValueError("Missing species taxonomy for source targets")
        species_counts = Counter(
            species_by_target[original_to_internal[user]] for user in evaluable
        )
        input_species_counts = Counter(species_by_target.values())
        authorized = set()
        authorized_by_release = defaultdict(set)
        for row in _rows(temporal.parent / "stage07/07_accepted_associations.tsv"):
            if row["annotation_donor"] == "YES":
                authorized.add(row["target_id"])
                authorized_by_release[row["release"]].add(row["target_id"])
        if authorized - set(headers):
            raise ValueError("Stage 07 contains a foreign target")
        summary = {
            "schema": SCHEMA,
            "overview": {
                "FASTA source records": _json(dataset / "targets/00_summary.json")[
                    "source_records"
                ],
                "Stage 00 accepted targets": len(headers),
                "Targets with authorized GO donor": len(authorized),
                "Evaluable original target IDs": len(evaluable),
                "Not evaluable original target IDs": len(headers) - len(evaluable),
                "Benchmark survival (%)": round(100 * len(evaluable) / len(headers), 2),
                "Canonical EVAL terms": source["counts"]["benchmark_EVAL"],
                "Exported EVAL protein-GO pairs": sum(
                    a["eval_pairs"] for a in aspects.values()
                ),
            },
            "aspects": aspects,
            "species_distribution": sorted(
                species_counts.items(), key=lambda item: (-item[1], item[0])
            ),
            "species_input_distribution": sorted(
                input_species_counts.items(), key=lambda item: (-item[1], item[0])
            ),
            "release_statistics": _release_statistics(run),
            "authorized_donor_targets_by_release": {
                release: len(ids)
                for release, ids in sorted(authorized_by_release.items())
            },
            "evidence_classes": source.get("classes", {}),
            "policy_sha256": source.get("policy_sha256"),
            "temporal_manifest_sha256": _sha(temporal / "manifest.json"),
        }
        (staging / "statistics.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "report.html").write_text(_report_html(summary), encoding="utf-8")
        source_paths = {
            "original_headers": dataset / "identity/original_headers.tsv",
            "stage00_mapping": dataset / "targets/targets.mapping.tsv",
            "stage00_fasta": dataset / "targets/targets.fasta",
            "temporal_manifest": temporal / "manifest.json",
            "exporter_source": Path(__file__),
        }
        receipt = {
            "schema": SCHEMA,
            "status": "PUBLISHED",
            "sources": {
                name: {"path": str(path), "sha256": _sha(path)}
                for name, path in source_paths.items()
            },
            "outputs": {
                name.name: {"bytes": name.stat().st_size, "sha256": _sha(name)}
                for name in sorted(staging.iterdir())
                if name.is_file()
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.rename(staging, final)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return final
