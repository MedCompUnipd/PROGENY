"""Experimental native Roaring IA backend with the certified v3 policy.

The native child reads GAF bytes from a pipe. The parent hashes those same bytes;
no second input scan, SQLite database, or per-protein closure is constructed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from progeny.information_accretion import IA_SCHEMA, NAMESPACE_ASPECT
from progeny.ontology import GO_ROOTS, GeneOntology
from progeny.stage08_go_closure import GoClosureIndex

BACKEND_SCHEMA = "progeny-ia-roaring-backend-v1"
CROARING_COMMIT = "20495fec4d1622b93284033a160f67d21a5aa8bb"


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_native_inputs(
    ontology: GeneOntology, graph: GoClosureIndex, directory: Path
) -> tuple[Path, Path]:
    """Precompute every ontology resolution once; preserve literal v3 aspects."""
    graph_path = directory / "graph.tsv"
    policy_path = directory / "policy.tsv"
    active = sorted(
        term
        for term, record in ontology.terms.items()
        if record.is_active and record.namespace in NAMESPACE_ASPECT
    )
    with graph_path.open("x", encoding="ascii", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["go_id", "aspect", "is_root", "parents"])
        for term in active:
            writer.writerow(
                [
                    term,
                    NAMESPACE_ASPECT[graph.aspect(term)],
                    int(term in GO_ROOTS),
                    ",".join(graph.direct_parents(term)),
                ]
            )
    input_ids = set(ontology.terms)
    for term in ontology.terms.values():
        input_ids.update(term.alternate_ids)
    with policy_path.open("x", encoding="ascii", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["go_id", "canonical", "status", "source_aspect"])
        for term in sorted(input_ids):
            resolution = ontology.resolve(term)
            source = ontology.raw_term(term)
            writer.writerow(
                [
                    term,
                    resolution.canonical_id or "",
                    resolution.status.value,
                    NAMESPACE_ASPECT.get(source.namespace, "") if source else "",
                ]
            )
    return graph_path, policy_path


def _read_values(path: Path, ontology: GeneOntology, graph: GoClosureIndex) -> dict:
    values = {}
    with path.open(encoding="ascii", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", strict=True)
        if reader.fieldnames != [
            "go_id",
            "aspect",
            "term_count",
            "parent_conjunction_count",
        ]:
            raise ValueError("Unexpected native count header")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed native count row")
            term = row["go_id"]
            if term in values or row["aspect"] != NAMESPACE_ASPECT[graph.aspect(term)]:
                raise ValueError("Duplicate native term or aspect mismatch")
            count = int(row["term_count"])
            parent_count = int(row["parent_conjunction_count"])
            if count < 0 or parent_count < count:
                raise ValueError("Invalid native membership counts")
            ia = (
                0.0 if term in GO_ROOTS else math.log2((parent_count + 1) / (count + 1))
            )
            if not math.isfinite(ia) or ia < 0:
                raise ValueError("Invalid native Information Accretion")
            values[term] = {
                "aspect": row["aspect"],
                "ia": ia,
                "term_count": count,
                "parent_conjunction_count": parent_count,
            }
    expected = {
        term
        for term, record in ontology.terms.items()
        if record.is_active and record.namespace in NAMESPACE_ASPECT
    }
    if set(values) != expected:
        raise ValueError("Native counts must cover exactly the pinned active GO terms")
    return values


def calculate_information_accretion_roaring(
    *,
    gaf_path: Path,
    expected_gaf_sha256: str,
    ontology: GeneOntology,
    graph: GoClosureIndex,
    scratch_root: Path,
    ontology_sha256: str,
    binary_path: Path,
    threads: int = 8,
    max_address_space_bytes: int = 128 * 1024**3,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Compute v3 IA via native bitmap unions and exact parent intersections.

    The address-space limit applies to the native child, including its protein
    dictionary and all concurrent intersection temporaries. It is not an RSS cap
    on the Python parent. Failure never falls back to another backend.
    """
    for name, value in (("GAF", expected_gaf_sha256), ("ontology", ontology_sha256)):
        if len(value) != 64:
            raise ValueError(f"Invalid {name} SHA-256")
        int(value, 16)
    if type(threads) is not int or not 1 <= threads <= 64:
        raise ValueError("Threads must be an integer between 1 and 64")
    if (
        type(max_address_space_bytes) is not int
        or max_address_space_bytes < 64 * 1024**2
    ):
        raise ValueError("Invalid native address-space limit")
    gaf_path = gaf_path.absolute()
    binary_path = binary_path.absolute()
    for path in (gaf_path, binary_path):
        if path.absolute() != path.resolve(strict=True) or not path.is_file():
            raise ValueError("GAF and native binary must be regular non-symlink files")
    if not scratch_root.is_dir():
        raise ValueError("Scratch root must be an existing directory")
    initial = gaf_path.stat()
    binary_sha = digest_file(binary_path)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(
        prefix="progeny-ia-roaring-", dir=scratch_root
    ) as d:
        directory = Path(d)
        graph_path, policy_path = write_native_inputs(ontology, graph, directory)
        counts_path = directory / "counts.tsv"
        audit_path = directory / "audit.json"
        command = [
            str(binary_path),
            str(graph_path),
            str(policy_path),
            str(counts_path),
            str(audit_path),
            str(threads),
            str(max_address_space_bytes),
        ]
        digest = hashlib.sha256()
        child = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL
        )
        scanned = 0
        try:
            try:
                with gaf_path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
                        digest.update(chunk)
                        view = memoryview(chunk)
                        while view:
                            written = child.stdin.write(view)
                            if not written:
                                raise BrokenPipeError("Native input pipe closed")
                            view = view[written:]
                        scanned += len(chunk)
                        if progress and scanned % (1024**3) == 0:
                            progress(
                                f"GAF_BYTES={scanned} TOTAL_BYTES={initial.st_size}"
                            )
                child.stdin.close()
            except BrokenPipeError as exc:
                child.wait()
                raise ValueError("Native IA engine rejected the input stream") from exc
            if child.wait() != 0:
                raise ValueError("Native IA engine failed; no publication produced")
        finally:
            if child.stdin is not None:
                with suppress(BrokenPipeError):
                    child.stdin.close()
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        if digest.hexdigest() != expected_gaf_sha256.lower():
            raise ValueError("GAF SHA-256 does not match the expected digest")
        final = gaf_path.stat()
        if (initial.st_dev, initial.st_ino, initial.st_size, initial.st_mtime_ns) != (
            final.st_dev,
            final.st_ino,
            final.st_size,
            final.st_mtime_ns,
        ):
            raise ValueError("GAF changed while IA was being calculated")
        if digest_file(binary_path) != binary_sha:
            raise ValueError("Native binary changed during calculation")
        result = json.loads(audit_path.read_text(encoding="ascii"))
        native_peak_rss = result.pop("native_peak_rss_kib")
        effective_limit = result.pop("native_effective_address_space_bytes")
        values = _read_values(counts_path, ontology, graph)
        result.update(
            {
                "schema": IA_SCHEMA,
                "status": "COMPUTED",
                "gaf_sha256": digest.hexdigest(),
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
                "cross_aspect_replacement_policy": "exclude_and_audit",
                "source_aspect_mismatch_policy": "exclude_and_audit",
                "invalid_gaf_aspect_policy": "exclude_and_audit",
                "deduplication": "one_protein_canonical_go_pair",
                "propagation": "same_aspect_pinned_transitive_maximal_closure",
                "smoothing": "one_synthetic_protein_annotated_to_every_active_term",
                "formula": "log2((count_all_direct_parents+1)/(count_term+1))",
                "term_values": values,
                "backend": {
                    "schema": BACKEND_SCHEMA,
                    "name": "native-croaring",
                    "croaring_commit": CROARING_COMMIT,
                    "binary_sha256": binary_sha,
                    "graph_sha256": digest_file(graph_path),
                    "resolution_policy_sha256": digest_file(policy_path),
                    "threads": threads,
                    "native_peak_rss_kib": native_peak_rss,
                    "native_effective_address_space_bytes": effective_limit,
                    "native_max_address_space_bytes": max_address_space_bytes,
                    "elapsed_seconds": time.monotonic() - started,
                    "python_implementation_sha256": digest_file(Path(__file__)),
                },
            }
        )
        return result
