"""Read-only, checksum-pinned inputs for a future PROGENY evaluator.

The certified publisher and scientific DAG are never invoked. This reader is
intentionally specific to the existing scientific benchmark publication v1,
Temporal v3 and compact M10C v1 contracts; other schemas fail closed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from progeny.alpha_export import (
    TEMPORAL_FILES,
    _canonical_to_user,
    _validate_headers,
    _verify_member_manifest,
)
from progeny.alpha_identity import _sha
from progeny.alpha_scientific_publish import _read_certificate, _verify_existing
from progeny.ontology import GeneOntology, TermStatus
from progeny.prediction_contract import (
    ASPECTS,
    ROOTS,
    GoResolution,
    Pair,
    PreparedPredictions,
    TermKey,
    prepare_predictions,
    read_predictions,
)
from progeny.stage08_go_closure import ALLOWED_RELATIONS, GoClosureIndex

NAMESPACE_ASPECT = {
    "molecular_function": "F",
    "biological_process": "P",
    "cellular_component": "C",
}
INPUT_SCHEMA = "progeny-prediction-input-validation-v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def _tsv(path: Path, fields: set[str]) -> Iterator[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", strict=True)
        names = reader.fieldnames or []
        _require(
            len(names) == len(set(names)) and fields <= set(names),
            f"Invalid table header: {path.name}",
        )
        for row in reader:
            _require(
                None not in row and all(value is not None for value in row.values()),
                f"Malformed table row: {path.name}:{reader.line_num}",
            )
            yield row


def _safe_directory(path: Path) -> Path:
    absolute = path.absolute()
    _require(
        absolute.resolve(strict=True) == absolute and absolute.is_dir(),
        f"Directory must exist without symlink components: {path}",
    )
    return absolute


@dataclass
class BenchmarkInputs:
    target_ids: frozenset[str]
    eligible: frozenset[Pair]
    truth: dict[Pair, frozenset[str]]
    masks: dict[TermKey, str]
    species: dict[str, str]
    ontology: GeneOntology
    graph: GoClosureIndex
    provenance: dict

    def aspect(self, go_id: str) -> str:
        namespace = self.graph.aspect(go_id)
        return NAMESPACE_ASPECT.get(namespace, "UNSUPPORTED")

    def resolve_prediction(self, go_id: str) -> GoResolution:
        resolution = self.ontology.resolve(go_id)
        return GoResolution(
            canonical_id=resolution.canonical_id,
            status=resolution.status.value,
            candidates=resolution.candidates,
        )

    def prepare(self, predictions: Path) -> PreparedPredictions:
        return prepare_predictions(
            read_predictions(predictions),
            target_ids=self.target_ids,
            eligible=self.eligible,
            masks=self.masks,
            resolve=self.resolve_prediction,
            aspect=self.aspect,
            ancestors=self.graph.ancestors,
        )


def _verify_fasta(path: Path, headers: dict) -> frozenset[str]:
    seen = set()
    current = None
    sequence: list[str] = []

    def flush() -> None:
        if current is None:
            return
        query = current.split()[0]
        _require(query in headers and query not in seen, "Invalid FASTA target ID")
        row = headers[query]
        _require(current == row["original_header"], "Original FASTA header mismatch")
        residues = "".join(sequence)
        _require(bool(residues), "Empty FASTA sequence")
        _require(
            hashlib.sha256(residues.encode("ascii")).hexdigest()
            == row["sequence_sha256"],
            "Original FASTA sequence mismatch",
        )
        seen.add(query)

    with path.open(encoding="ascii") as stream:
        for line in stream:
            line = line.rstrip("\r\n")
            if line.startswith(">"):
                flush()
                current = line[1:]
                _require(bool(current.split()), "Empty FASTA header")
                sequence = []
            elif line:
                _require(current is not None, "Sequence before FASTA header")
                sequence.append(line)
    flush()
    return frozenset(seen)


def load_benchmark_inputs(
    *,
    dataset: Path,
    run: Path,
    ontology_path: Path,
    benchmark_sha256: str,
) -> BenchmarkInputs:
    """Verify source identities and reconstruct only evaluator input state."""
    _require(
        bool(re.fullmatch(r"[a-f0-9]{64}", benchmark_sha256)),
        "Expected a lowercase SHA-256 benchmark digest",
    )
    dataset = _safe_directory(dataset)
    run = _safe_directory(run)
    benchmark = _safe_directory(run / "results/benchmark")
    manifest_path = benchmark / "manifest.json"
    _require(_sha(manifest_path) == benchmark_sha256, "Benchmark digest mismatch")
    _verify_existing(benchmark)
    manifest = _read_json(manifest_path)
    certificate = _read_certificate(run)
    certified = _read_json(certificate)
    expected_inputs = {
        "canonical_certificate": certificate,
        "original_headers": dataset / "identity/original_headers.tsv",
        "original_header_manifest": dataset / "identity/manifest.json",
        "stage00_mapping": dataset / "targets/targets.mapping.tsv",
        "canonical_target_fasta": dataset / "targets/targets.fasta",
    }
    for name, expected in expected_inputs.items():
        _require(
            manifest["inputs"][name]["path"] == str(expected),
            f"Foreign benchmark input: {name}",
        )
    temporal_receipt = Path(certified["receipts"]["temporal:COMMON"]["path"])
    m10c_receipt = Path(certified["receipts"]["m10c:COMMON"]["path"])
    temporal = temporal_receipt.parent / "temporal"
    m10c_path = m10c_receipt.parent / "m10c/manifest.json"
    for name, expected in (
        ("temporal_manifest", temporal / "manifest.json"),
        ("m10c_summary", m10c_path),
    ):
        _require(
            manifest["inputs"][name]["path"] == str(expected),
            f"Uncertified benchmark source: {name}",
        )
    temporal_data = _verify_member_manifest(
        temporal, (*TEMPORAL_FILES, "duplicate_targets.tsv")
    )
    m10c = _read_json(m10c_path)
    _require(
        temporal_data.get("schema_version") == "stage08-temporal-eval-skip-neutral-v3",
        "Unsupported Temporal schema",
    )
    for name in ("class_fingerprint", "registry_fingerprint", "policy_sha256"):
        value = temporal_data.get(name)
        _require(
            isinstance(value, str) and bool(re.fullmatch(r"[a-f0-9]{64}", value)),
            f"Missing or invalid certified Temporal identity: {name}",
        )
    _require(
        m10c.get("schema_version") == "stage08-m10c-compact-interpretation-v1",
        "Unsupported M10C schema",
    )
    _require(m10c.get("not_policy") == "preserved_no_veto", "Unsupported NOT policy")
    ontology_digest = temporal_data.get("ontology_sha256")
    _require(
        isinstance(ontology_digest, str)
        and bool(re.fullmatch(r"[a-f0-9]{64}", ontology_digest))
        and ontology_digest == m10c.get("ontology_sha256"),
        "Inconsistent certified ontology digests",
    )
    ontology_path = ontology_path.absolute()
    _require(
        ontology_path.resolve(strict=True) == ontology_path and ontology_path.is_file(),
        "Ontology must be a regular file without symlink components",
    )
    _require(_sha(ontology_path) == ontology_digest, "Pinned ontology digest mismatch")
    ontology = GeneOntology.from_owl(ontology_path)
    graph = GoClosureIndex.from_gene_ontology(ontology)
    _require(
        (graph.node_count, graph.edge_count)
        == (m10c.get("graph_terms"), m10c.get("graph_edges")),
        "GO projection differs from certified M10C",
    )

    headers = _validate_headers(dataset)
    _canonical_to_user(dataset, temporal, headers)
    by_user = {row["source_id"]: row for row in headers.values()}
    fasta_ids = _verify_fasta(benchmark / "ground_truth_targets.fasta", by_user)
    identity_ids = set()
    identity_evaluable = set()
    species = {}
    for row in _tsv(
        benchmark / "target_identity_map.tsv",
        {"original_id", "internal_target_id", "species_taxid", "benchmark_status"},
    ):
        query = row["original_id"]
        internal = row["internal_target_id"]
        _require(
            query in by_user
            and query not in identity_ids
            and internal in headers
            and headers[internal]["source_id"] == query,
            "Invalid target identity map",
        )
        _require(
            row["benchmark_status"] in {"EVALUABLE", "NO_EVAL"},
            "Unknown identity benchmark status",
        )
        identity_ids.add(query)
        if row["benchmark_status"] == "EVALUABLE":
            identity_evaluable.add(query)
        species[query] = row["species_taxid"]
    _require(identity_ids == set(by_user), "Incomplete target identity map")
    _require(identity_evaluable == fasta_ids, "FASTA eligibility mismatch")

    eligible = {}
    for row in _tsv(
        benchmark / "target_aspects.tsv",
        {"query_id", "aspect", "eval_terms", "skip_terms", "neutral_terms"},
    ):
        key = row["query_id"], row["aspect"]
        _require(
            key[0] in fasta_ids and key[1] in ASPECTS and key not in eligible,
            "Invalid eligible target-aspect",
        )
        eligible[key] = row
    _require({q for q, _ in eligible} == fasta_ids, "Eligible target set mismatch")

    labels = {}
    counts: Counter = Counter()
    for row in _tsv(
        benchmark / "benchmark_terms.tsv", {"query_id", "aspect", "go_id", "status"}
    ):
        query, value, go = row["query_id"], row["aspect"], row["go_id"]
        key = query, value, go
        resolution = ontology.resolve(go)
        _require(
            (query, value) in eligible
            and row["status"] in {"EVAL", "SKIP", "NEUTRAL"}
            and key not in labels
            and go not in ROOTS
            and resolution.status == TermStatus.ACTIVE
            and NAMESPACE_ASPECT.get(graph.aspect(go)) == value,
            "Invalid, duplicate or noncanonical benchmark term",
        )
        labels[key] = row["status"]
        counts[(query, value, row["status"])] += 1
    for key, row in eligible.items():
        _require(counts[(*key, "EVAL")] > 0, "Eligible aspect without EVAL")
        for status in ("EVAL", "SKIP", "NEUTRAL"):
            _require(
                int(row[f"{status.lower()}_terms"]) == counts[(*key, status)],
                "Per-aspect term cardinality mismatch",
            )
    status_counts = Counter(labels.values())
    for status, filename in (
        ("SKIP", "skip_terms.tsv"),
        ("NEUTRAL", "neutral_terms.tsv"),
    ):
        seen = set()
        for row in _tsv(
            benchmark / filename, {"query_id", "aspect", "go_id", "status"}
        ):
            key = row["query_id"], row["aspect"], row["go_id"]
            _require(
                row["status"] == status
                and labels.get(key) == status
                and key not in seen,
                "Invalid convenience mask",
            )
            seen.add(key)
        _require(len(seen) == status_counts[status], "Incomplete convenience mask")
    truth: dict[Pair, set[str]] = {key: set() for key in eligible}
    masks = {}
    for key, status in labels.items():
        if status == "EVAL":
            truth[key[:2]].add(key[2])
        else:
            masks[key] = status
    overview = {
        "input_targets": len(headers),
        "evaluable_targets": len(fasta_ids),
        "target_aspects": len(eligible),
        **{status: status_counts[status] for status in ("EVAL", "SKIP", "NEUTRAL")},
    }
    statistics = _read_json(benchmark / "statistics.json")
    _require(
        all(
            statistics["overview"].get(key) == value for key, value in overview.items()
        ),
        "Benchmark statistics mismatch",
    )
    _verify_existing(benchmark)
    _read_certificate(run)
    _require(_sha(manifest_path) == benchmark_sha256, "Benchmark changed during read")
    _require(_sha(ontology_path) == ontology_digest, "Ontology changed during read")
    provenance = {
        "schema": INPUT_SCHEMA,
        "status": "VALIDATED",
        "benchmark_sha256": benchmark_sha256,
        "ontology_sha256": ontology_digest,
        "ontology_path": str(ontology_path),
        "relations": sorted(ALLOWED_RELATIONS),
        "cross_aspect_policy": "ignore_as_in_certified_m10c",
        "closure_ignored_cross_aspect_edges": graph.ignored_cross_aspect_edges,
        "temporal_manifest_sha256": _sha(temporal / "manifest.json"),
        "m10c_manifest_sha256": _sha(m10c_path),
        "temporal_class_fingerprint": temporal_data["class_fingerprint"],
        "temporal_registry_fingerprint": temporal_data["registry_fingerprint"],
        "temporal_policy_sha256": temporal_data["policy_sha256"],
        "overview": overview,
        "knowledge_classification": statistics.get("classification"),
        "documentary_lookahead_audit": statistics.get("documentary_lookahead_audit"),
        "metrics_status": "NOT_COMPUTED",
        "prediction_unknown_go_policy": "exclude_and_audit",
        "prediction_go_mapping_source": "pinned_benchmark_ontology_only",
    }
    return BenchmarkInputs(
        target_ids=fasta_ids,
        eligible=frozenset(eligible),
        truth={key: frozenset(values) for key, values in truth.items()},
        masks=masks,
        species={query: species[query] for query in fasta_ids},
        ontology=ontology,
        graph=graph,
        provenance=provenance,
    )
