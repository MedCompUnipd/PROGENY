"""Compute CAFA-style GO Information Accretion from a pinned GAF corpus.

The GAF is parsed in one sequential pass. Distinct source protein/term pairs
and propagated memberships are held in an external SQLite scratch database.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from progeny.ontology import GO_ROOTS, GeneOntology, TermStatus
from progeny.stage08_go_closure import GoClosureIndex

IA_SCHEMA = "progeny-information-accretion-v3"
GAF_COLUMNS = 17
BATCH_SIZE = 50_000
PROGRESS_ROWS = 5_000_000
NAMESPACE_ASPECT = {
    "molecular_function": "F",
    "biological_process": "P",
    "cellular_component": "C",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _create_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE direct_annotations (
            protein TEXT NOT NULL,
            go_id TEXT NOT NULL,
            PRIMARY KEY (protein, go_id)
        ) WITHOUT ROWID;
        CREATE TABLE propagated_annotations (
            protein TEXT NOT NULL,
            go_id TEXT NOT NULL,
            PRIMARY KEY (protein, go_id)
        ) WITHOUT ROWID;
        CREATE INDEX propagated_by_term
            ON propagated_annotations (go_id, protein);
        CREATE TABLE protein_aspects (
            protein TEXT NOT NULL,
            aspect TEXT NOT NULL,
            PRIMARY KEY (protein, aspect)
        ) WITHOUT ROWID;
        """
    )


def _parse_gaf(
    gaf_path: Path,
    *,
    ontology: GeneOntology,
    graph: GoClosureIndex,
    connection: sqlite3.Connection,
    expected_sha256: str,
    progress: Callable[[str], None] | None,
) -> dict[str, object]:
    digest = hashlib.sha256()
    counts: Counter[str] = Counter()
    evidence_counts: Counter[str] = Counter()
    resolution_counts: Counter[str] = Counter()
    cross_aspect_replacement_counts: Counter[str] = Counter()
    source_aspect_mismatch_counts: Counter[str] = Counter()
    invalid_gaf_aspect_counts: Counter[str] = Counter()
    batch: list[tuple[str, str]] = []
    min_annotation_date = "99999999"
    max_annotation_date = "00000000"
    with gaf_path.open("rb") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            digest.update(raw_line)
            if raw_line.startswith(b"!") or not raw_line.strip():
                continue
            counts["data_rows"] += 1
            if progress is not None and counts["data_rows"] % PROGRESS_ROWS == 0:
                progress(f"GAF_ROWS={counts['data_rows']}")
            try:
                row = raw_line.decode("ascii").rstrip("\r\n").split("\t")
            except UnicodeDecodeError as exc:
                raise ValueError(f"GAF line {line_number} is not ASCII") from exc
            if len(row) != GAF_COLUMNS:
                raise ValueError(
                    f"GAF line {line_number} has {len(row)} fields; "
                    f"expected {GAF_COLUMNS}"
                )
            if row[0] != "UniProtKB":
                counts["non_uniprot_rows_excluded"] += 1
                continue
            if not row[1] or not row[4].startswith("GO:"):
                raise ValueError(f"GAF line {line_number} has invalid identity/GO")
            annotation_date = row[13]
            if len(annotation_date) != 8 or not annotation_date.isdecimal():
                raise ValueError(f"GAF line {line_number} has invalid annotation date")
            min_annotation_date = min(min_annotation_date, annotation_date)
            max_annotation_date = max(max_annotation_date, annotation_date)
            qualifiers = frozenset(row[3].split("|"))
            if "NOT" in qualifiers:
                counts["not_rows_excluded"] += 1
                continue
            counts["positive_rows"] += 1
            evidence_counts[row[6]] += 1
            resolution = ontology.resolve(row[4])
            resolution_counts[resolution.status.value] += 1
            canonical = resolution.canonical_id
            if canonical is None:
                counts["unresolved_go_rows_excluded"] += 1
                continue
            source_term = ontology.raw_term(row[4])
            source_namespace = source_term.namespace if source_term else ""
            source_aspect = NAMESPACE_ASPECT.get(source_namespace)
            gaf_aspect = row[8] if row[8] in {"F", "P", "C"} else None
            if gaf_aspect is None:
                counts["invalid_gaf_aspect_rows_excluded"] += 1
                mapping = f"{row[4]}|GAF={row[8]}|source={source_aspect or '?'}"
                invalid_gaf_aspect_counts[mapping] += 1
                continue
            if source_aspect is None or gaf_aspect != source_aspect:
                counts["source_aspect_mismatch_rows_excluded"] += 1
                mapping = f"{row[4]}|GAF={gaf_aspect}|source={source_aspect or '?'}"
                source_aspect_mismatch_counts[mapping] += 1
                continue
            try:
                canonical_namespace = graph.aspect(canonical)
            except KeyError:
                counts["inactive_or_unprojected_go_rows_excluded"] += 1
                continue
            canonical_aspect = NAMESPACE_ASPECT.get(canonical_namespace)
            if canonical_aspect is None:
                raise ValueError(
                    f"GAF line {line_number} canonical GO has unsupported namespace"
                )
            if (
                resolution.status is TermStatus.REPLACED
                and source_aspect != canonical_aspect
            ):
                mapping = f"{row[4]}|{source_aspect}->{canonical}|{canonical_aspect}"
                cross_aspect_replacement_counts[mapping] += 1
                counts["cross_aspect_replacement_rows_excluded"] += 1
                continue
            if canonical != row[4]:
                counts["remapped_go_rows"] += 1
            batch.append((f"{row[0]}:{row[1]}", canonical))
            if len(batch) >= BATCH_SIZE:
                connection.executemany(
                    "INSERT OR IGNORE INTO direct_annotations VALUES (?, ?)", batch
                )
                connection.commit()
                batch.clear()
                if progress is not None:
                    progress(f"GAF_ROWS={counts['data_rows']}")
    if batch:
        connection.executemany(
            "INSERT OR IGNORE INTO direct_annotations VALUES (?, ?)", batch
        )
        connection.commit()
    observed_sha256 = digest.hexdigest()
    if observed_sha256 != expected_sha256.lower():
        raise ValueError("GAF SHA-256 does not match the expected digest")
    counts["gaf_sha256"] = observed_sha256
    counts["unique_direct_pairs"] = connection.execute(
        "SELECT COUNT(*) FROM direct_annotations"
    ).fetchone()[0]
    counts["unique_direct_proteins"] = connection.execute(
        "SELECT COUNT(DISTINCT protein) FROM direct_annotations"
    ).fetchone()[0]
    counts["minimum_annotation_date"] = (
        min_annotation_date if min_annotation_date != "99999999" else ""
    )
    counts["maximum_annotation_date"] = (
        max_annotation_date if max_annotation_date != "00000000" else ""
    )
    counts["evidence_code_counts"] = dict(sorted(evidence_counts.items()))
    counts["go_resolution_status_counts"] = dict(sorted(resolution_counts.items()))
    counts["cross_aspect_replacement_rows_excluded"] = sum(
        cross_aspect_replacement_counts.values()
    )
    counts["cross_aspect_replacement_mapping_counts"] = dict(
        sorted(cross_aspect_replacement_counts.items())
    )
    counts["source_aspect_mismatch_rows_excluded"] = sum(
        source_aspect_mismatch_counts.values()
    )
    counts["source_aspect_mismatch_mapping_counts"] = dict(
        sorted(source_aspect_mismatch_counts.items())
    )
    counts["invalid_gaf_aspect_rows_excluded"] = sum(invalid_gaf_aspect_counts.values())
    counts["invalid_gaf_aspect_mapping_counts"] = dict(
        sorted(invalid_gaf_aspect_counts.items())
    )
    return dict(counts)


def _flush_protein(
    connection: sqlite3.Connection,
    graph: GoClosureIndex,
    protein: str,
    direct_terms: list[str],
) -> None:
    propagated: set[str] = set()
    for term in direct_terms:
        propagated.update(graph.ancestors(term))
        propagated.add(term)
    rows = [(protein, term) for term in sorted(propagated)]
    connection.executemany(
        "INSERT OR IGNORE INTO propagated_annotations VALUES (?, ?)", rows
    )
    aspects = sorted({graph.aspect(term) for term in propagated})
    connection.executemany(
        "INSERT OR IGNORE INTO protein_aspects VALUES (?, ?)",
        [(protein, aspect) for aspect in aspects],
    )


def _build_propagated_memberships(
    connection: sqlite3.Connection,
    graph: GoClosureIndex,
    progress: Callable[[str], None] | None,
) -> None:
    cursor = connection.execute(
        "SELECT protein, go_id FROM direct_annotations ORDER BY protein, go_id"
    )
    current_protein = None
    direct_terms: list[str] = []
    processed = 0
    for protein, go_id in cursor:
        if current_protein is not None and protein != current_protein:
            _flush_protein(connection, graph, current_protein, direct_terms)
            direct_terms.clear()
            processed += 1
            if processed % 1_000 == 0:
                connection.commit()
                if progress is not None:
                    progress(f"PROPAGATED_PROTEINS={processed}")
        current_protein = protein
        direct_terms.append(go_id)
    if current_protein is not None:
        _flush_protein(connection, graph, current_protein, direct_terms)
    connection.commit()


def _intersection_count(
    connection: sqlite3.Connection,
    parents: tuple[str, ...],
    counts: dict[str, int],
) -> int:
    ordered = tuple(sorted(parents, key=lambda term: (counts.get(term, 0), term)))
    selects = [
        "SELECT protein FROM propagated_annotations WHERE go_id = ?" for _ in ordered
    ]
    query = "SELECT COUNT(*) FROM (" + " INTERSECT ".join(selects) + ")"
    row = connection.execute(query, ordered).fetchone()
    return int(row[0])


def calculate_information_accretion(
    *,
    gaf_path: Path,
    expected_gaf_sha256: str,
    ontology: GeneOntology,
    graph: GoClosureIndex,
    scratch_database: Path,
    ontology_sha256: str,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Compute smoothed IA values from a positive START-release GAF corpus.

    One synthetic protein annotated to every active GO term implements the
    published add-one count regularization. Parent conjunctions are measured
    over same-aspect direct is_a/part_of parents in the pinned projection.
    """
    if gaf_path.is_symlink() or not gaf_path.is_file():
        raise ValueError("GAF must be a regular non-symlink file")
    if scratch_database.exists() or scratch_database.is_symlink():
        raise ValueError("IA scratch database must not already exist")
    if len(expected_gaf_sha256) != 64 or len(ontology_sha256) != 64:
        raise ValueError("Expected SHA-256 values must contain 64 hex digits")
    int(expected_gaf_sha256, 16)
    int(ontology_sha256, 16)
    initial_stat = gaf_path.stat()
    connection = sqlite3.connect(scratch_database)
    try:
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute("PRAGMA temp_store = FILE")
        connection.execute("PRAGMA cache_size = -262144")
        _create_tables(connection)
        audit = _parse_gaf(
            gaf_path,
            ontology=ontology,
            graph=graph,
            connection=connection,
            expected_sha256=expected_gaf_sha256,
            progress=progress,
        )
        final_stat = gaf_path.stat()
        if (
            final_stat.st_size != initial_stat.st_size
            or final_stat.st_mtime_ns != initial_stat.st_mtime_ns
            or final_stat.st_ino != initial_stat.st_ino
        ):
            raise ValueError("GAF changed while IA was being calculated")
        _build_propagated_memberships(connection, graph, progress)
        term_counts = {
            term: int(count)
            for term, count in connection.execute(
                "SELECT go_id, COUNT(*) FROM propagated_annotations GROUP BY go_id"
            )
        }
        aspect_counts = {
            aspect: int(count)
            for aspect, count in connection.execute(
                "SELECT aspect, COUNT(*) FROM protein_aspects GROUP BY aspect"
            )
        }
        parent_count_cache: dict[tuple[str, ...], int] = {}
        values: dict[str, dict] = {}
        active_terms = sorted(
            term
            for term, record in ontology.terms.items()
            if record.is_active
            and record.namespace
            in {"molecular_function", "biological_process", "cellular_component"}
        )
        for term in active_terms:
            aspect = graph.aspect(term)
            parents = graph.direct_parents(term)
            term_count = term_counts.get(term, 0)
            if term in GO_ROOTS:
                parent_count = aspect_counts.get(aspect, 0)
                ia = 0.0
            elif not parents:
                parent_count = aspect_counts.get(aspect, 0)
                ia = math.log2((parent_count + 1) / (term_count + 1))
            elif len(parents) == 1:
                parent_count = term_counts.get(parents[0], 0)
                ia = math.log2((parent_count + 1) / (term_count + 1))
            else:
                parent_count = parent_count_cache.get(parents)
                if parent_count is None:
                    parent_count = _intersection_count(connection, parents, term_counts)
                    parent_count_cache[parents] = parent_count
                ia = math.log2((parent_count + 1) / (term_count + 1))
            if term_count > parent_count:
                raise ValueError(f"Inconsistent propagated annotation counts: {term}")
            if not math.isfinite(ia) or ia < 0:
                raise ValueError(f"Invalid Information Accretion value: {term}")
            values[term] = {
                "aspect": NAMESPACE_ASPECT[aspect],
                "ia": ia,
                "term_count": term_count,
                "parent_conjunction_count": parent_count,
            }
        audit.update(
            {
                "schema": IA_SCHEMA,
                "status": "COMPUTED",
                "ontology_sha256": ontology_sha256.lower(),
                "relations": ["is_a", "part_of"],
                "evidence_policy": "all_positive_uniprotkb_gaf_rows_including_iea",
                "not_policy": "exclude_rows_with_NOT_qualifier",
                "identity_policy": "GAF_database_and_object_id",
                "go_resolution_policy": (
                    "audit_source_namespace_then_follow_only_unambiguous_"
                    "replaced_by_to_active_term"
                ),
                "remapped_go_count_policy": "accepted_rows_only",
                "cross_aspect_replacement_policy": ("exclude_and_audit"),
                "source_aspect_mismatch_policy": "exclude_and_audit",
                "invalid_gaf_aspect_policy": "exclude_and_audit",
                "deduplication": "one_protein_canonical_go_pair",
                "propagation": "same_aspect_pinned_transitive_maximal_closure",
                "smoothing": "one_synthetic_protein_annotated_to_every_active_term",
                "formula": "log2((count_all_direct_parents+1)/(count_term+1))",
                "aspect_protein_counts": {
                    NAMESPACE_ASPECT[aspect]: count
                    for aspect, count in sorted(aspect_counts.items())
                },
                "term_values": values,
            }
        )
        return audit
    finally:
        connection.close()


def write_information_accretion(
    result: dict,
    *,
    tsv_path: Path,
    manifest_path: Path,
) -> None:
    """Write deterministic IA TSV and JSON provenance into a fresh directory."""
    if result.get("schema") != IA_SCHEMA or result.get("status") != "COMPUTED":
        raise ValueError("IA result is not a completed supported calculation")
    if tsv_path.exists() or manifest_path.exists():
        raise ValueError("IA output files must not already exist")
    with tsv_path.open("x", encoding="utf-8", newline="") as stream:
        stream.write("go_id\taspect\tia\tterm_count\tparent_conjunction_count\n")
        for go_id, row in sorted(result["term_values"].items()):
            stream.write(
                f"{go_id}\t{row['aspect']}\t{row['ia']:.17g}\t"
                f"{row['term_count']}\t{row['parent_conjunction_count']}\n"
            )
    manifest = {key: value for key, value in result.items() if key != "term_values"}
    manifest["ia_table_sha256"] = _sha256(tsv_path)
    manifest["ia_terms"] = len(result["term_values"])
    with manifest_path.open("x", encoding="utf-8", newline="") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
