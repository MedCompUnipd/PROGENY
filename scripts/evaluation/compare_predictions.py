#!/usr/bin/env python3
"""Compare multiple prediction files and write CAFA-style curves and SVGs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from progeny.alpha_identity import _sha
from progeny.knowledge_cohorts import load_published_cohorts, select_eligible_pairs
from progeny.ontology import GO_ROOTS
from progeny.prediction_inputs import load_benchmark_inputs
from progeny.prediction_metrics import evaluate_scores
from progeny.prediction_plotting import (
    render_metric_svg,
    render_precision_recall_svg,
)
from progeny.prediction_weighted_metrics import evaluate_weighted_scores
from progeny.stage08_go_closure import GoClosureIndex

SCHEMA = "progeny-multi-method-evaluation-v2"
NAMESPACE_ASPECT = {
    "molecular_function": "F",
    "biological_process": "P",
    "cellular_component": "C",
}
ASPECT_LABELS = {
    "F": "Molecular Function (MF)",
    "P": "Biological Process (BP)",
    "C": "Cellular Component (CC)",
}
CURVE_FIELDS = (
    "method_id",
    "aspect",
    "threshold",
    "precision",
    "recall",
    "f1",
    "coverage",
    "weighted_precision",
    "weighted_recall",
    "weighted_f1",
    "weighted_coverage",
    "ru",
    "mi",
    "smin",
)
PLOT_METRICS = {
    "precision": ("precision", True),
    "recall": ("recall", True),
    "f1": ("f1", True),
    "coverage": ("coverage", True),
    "weighted_precision": ("weighted_precision", True),
    "weighted_recall": ("weighted_recall", True),
    "weighted_f1": ("weighted_f1", True),
    "weighted_coverage": ("weighted_coverage", True),
    "ru": ("ru", False),
    "mi": ("mi", False),
    "smin": ("smin", False),
}
IMPLEMENTATION_FILES = (
    "scripts/evaluation/compare_predictions.py",
    "scripts/evaluation/publish_start_knowledge_cohorts.py",
    "src/progeny/prediction_weighted_metrics.py",
    "src/progeny/prediction_plotting.py",
    "src/progeny/information_accretion.py",
    "src/progeny/prediction_metrics.py",
    "src/progeny/prediction_inputs.py",
    "src/progeny/prediction_contract.py",
    "src/progeny/knowledge_cohorts.py",
)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _thresholds(step: str) -> tuple[float, ...]:
    if not step or step.strip() != step:
        raise ValueError("Threshold step must be a decimal string")
    try:
        increment = Decimal(step)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Threshold step must be a decimal string") from exc
    if not increment.is_finite() or not Decimal("0.0001") <= increment < Decimal(1):
        raise ValueError("Threshold step must be between 0.0001 and 1")
    values = []
    index = 1
    while increment * index < 1:
        values.append(float(increment * index))
        index += 1
        if len(values) > 10_000:
            raise ValueError("Threshold grid exceeds 10,000 points")
    return tuple(reversed(values))


def _method_spec(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError("Methods must use METHOD_ID=/absolute/predictions.tsv")
    method_id, raw_path = value.split("=", maxsplit=1)
    if (
        not method_id
        or any(character.isspace() for character in method_id)
        or not raw_path
    ):
        raise ValueError("Invalid method specification")
    return method_id, Path(raw_path)


def _aspect_code(value: str) -> str:
    aliases = {"MF": "F", "BP": "P", "CC": "C"}
    code = aliases.get(value.upper(), value.upper())
    if code not in {"F", "P", "C"}:
        raise argparse.ArgumentTypeError("Aspect must be MF/F, BP/P or CC/C")
    return code


def _knowledge_filter(value: str) -> frozenset[str] | None:
    if value.lower() == "all":
        return None
    values = frozenset(part.strip().upper() for part in value.split(","))
    if not values or "" in values or not values <= {"NK", "LK", "PK"}:
        raise argparse.ArgumentTypeError("Knowledge must be all or a list of NK,LK,PK")
    return values


def _taxid_filter(values: list[str] | None) -> frozenset[str] | None:
    if not values or (len(values) == 1 and values[0].lower() == "all"):
        return None
    selected = frozenset(
        taxid.strip() for value in values for taxid in value.split(",")
    )
    if (
        not selected
        or "" in selected
        or any(
            not value.isascii() or not value.isdecimal() or value.startswith("0")
            for value in selected
        )
    ):
        raise ValueError("TaxID must be all or comma-separated positive integers")
    return selected


def _safe_method_filename(method_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", method_id)


def _write_prepared_predictions(
    path: Path,
    prepared,
    *,
    method_id: str,
    labels,
    species,
) -> None:
    fields = (
        "method_id",
        "protein_id",
        "go_term",
        "score",
        "aspect",
        "knowledge_status",
        "taxid",
    )
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for (query, aspect, go_id), score in sorted(prepared.scores.items()):
            writer.writerow(
                {
                    "method_id": method_id,
                    "protein_id": query,
                    "go_term": go_id,
                    "score": format(score, ".17g"),
                    "aspect": aspect,
                    "knowledge_status": labels[(query, aspect)],
                    "taxid": species[query],
                }
            )


def _read_ia(
    table_path: Path,
    manifest_path: Path,
    ontology_sha256: str,
    graph: GoClosureIndex,
):
    if any(
        path.absolute() != path.resolve(strict=True) or not path.is_file()
        for path in (table_path, manifest_path)
    ):
        raise ValueError("IA table and manifest must be regular files")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "schema": "progeny-information-accretion-v3",
        "status": "COMPUTED",
        "source_role": "START",
        "evidence_policy": "all_positive_uniprotkb_gaf_rows_including_iea",
        "go_resolution_policy": (
            "audit_source_namespace_then_follow_only_unambiguous_"
            "replaced_by_to_active_term"
        ),
        "remapped_go_count_policy": "accepted_rows_only",
        "cross_aspect_replacement_policy": "exclude_and_audit",
        "source_aspect_mismatch_policy": "exclude_and_audit",
        "invalid_gaf_aspect_policy": "exclude_and_audit",
        "ontology_sha256": ontology_sha256,
        "relations": ["is_a", "part_of"],
        "not_policy": "exclude_rows_with_NOT_qualifier",
        "smoothing": "one_synthetic_protein_annotated_to_every_active_term",
        "formula": "log2((count_all_direct_parents+1)/(count_term+1))",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"Unsupported IA manifest field: {key}")
    audit_fields = (
        (
            "cross_aspect_replacement_rows_excluded",
            "cross_aspect_replacement_mapping_counts",
        ),
        (
            "source_aspect_mismatch_rows_excluded",
            "source_aspect_mismatch_mapping_counts",
        ),
        ("invalid_gaf_aspect_rows_excluded", "invalid_gaf_aspect_mapping_counts"),
    )
    for count_field, mapping_field in audit_fields:
        row_count = manifest.get(count_field)
        mappings = manifest.get(mapping_field)
        if (
            type(row_count) is not int
            or row_count < 0
            or not isinstance(mappings, dict)
            or any(
                not isinstance(key, str) or type(count) is not int or count <= 0
                for key, count in mappings.items()
            )
            or sum(mappings.values()) != row_count
        ):
            raise ValueError(f"Invalid IA audit field: {count_field}")
    if _sha(table_path) != manifest.get("ia_table_sha256"):
        raise ValueError("IA table digest differs from its manifest")
    values = {}
    with table_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", strict=True)
        if reader.fieldnames != [
            "go_id",
            "aspect",
            "ia",
            "term_count",
            "parent_conjunction_count",
        ]:
            raise ValueError("Unexpected IA table header")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed IA table row")
            go = row["go_id"]
            if go in values or NAMESPACE_ASPECT.get(graph.aspect(go)) != row["aspect"]:
                raise ValueError("Duplicate IA term or aspect mismatch")
            try:
                weight = float(row["ia"])
                term_count = int(row["term_count"])
                parent_count = int(row["parent_conjunction_count"])
            except ValueError as exc:
                raise ValueError("Invalid IA table numeric value") from exc
            if (
                not math.isfinite(weight)
                or weight < 0
                or term_count < 0
                or parent_count < term_count
            ):
                raise ValueError("Invalid or inconsistent IA table values")
            expected_weight = (
                0.0
                if go in GO_ROOTS
                else math.log2((parent_count + 1) / (term_count + 1))
            )
            if not math.isclose(weight, expected_weight, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("IA value disagrees with its count formula")
            values[go] = weight
    if len(values) != graph.node_count or manifest.get("ia_terms") != len(values):
        raise ValueError("IA table must cover exactly the pinned active GO graph")
    if not re.fullmatch(r"[a-f0-9]{64}", str(manifest.get("gaf_sha256", ""))):
        raise ValueError("IA manifest lacks a verified source GAF digest")
    if not manifest.get("source_release_id"):
        raise ValueError("IA manifest lacks its START release identifier")
    return values, manifest


def _write_curve_table(path: Path, rows: list[dict]) -> None:
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CURVE_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _audit_path(directory: Path, method_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", method_id)
    return directory / f"go_resolution_audit_{safe_id}.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--benchmark-sha256", required=True)
    parser.add_argument("--ia-table", type=Path, required=True)
    parser.add_argument("--ia-manifest", type=Path, required=True)
    parser.add_argument("--cohorts", type=Path, required=True)
    parser.add_argument("--method", action="append", required=True)
    parser.add_argument("--threshold-step", default="0.01")
    parser.add_argument("--aspect", type=_aspect_code, action="append", required=True)
    parser.add_argument("--knowledge", type=_knowledge_filter, default=None)
    parser.add_argument("--taxid", action="append")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    methods = [_method_spec(value) for value in args.method]
    if len(methods) < 2 or len({method for method, _ in methods}) != len(methods):
        parser.error("Provide at least two prediction files with distinct method IDs")
    audit_names = [_audit_path(Path("."), method).name for method, _ in methods]
    if len(set(audit_names)) != len(audit_names):
        parser.error("Method IDs collide after audit filename normalization")
    thresholds = _thresholds(args.threshold_step)
    repository = Path(__file__).resolve().parents[2]
    implementation_before = {
        name: _sha(repository / name) for name in IMPLEMENTATION_FILES
    }
    output_dir = args.output_dir.absolute()
    if output_dir.resolve(strict=False) != output_dir or output_dir.exists():
        raise ValueError("Output directory must be new and without symlink parents")
    try:
        output_dir.relative_to(repository)
    except ValueError:
        pass
    else:
        raise ValueError("Evaluation output must be outside the source checkout")
    if output_dir.parent.resolve(strict=True) != output_dir.parent:
        raise ValueError("Output parent must not contain symlink components")
    for protected in (args.dataset, args.run):
        protected_root = protected.resolve(strict=True)
        try:
            output_dir.relative_to(protected_root)
        except ValueError:
            continue
        raise ValueError("Evaluation output must be outside dataset and run roots")

    benchmark = load_benchmark_inputs(
        dataset=args.dataset,
        run=args.run,
        ontology_path=args.ontology,
        benchmark_sha256=args.benchmark_sha256,
    )
    cohort_rows, cohort_manifest = load_published_cohorts(
        args.cohorts,
        eligible=benchmark.eligible,
        species=benchmark.species,
        provenance=benchmark.provenance,
    )
    cohort_table_sha = _sha(args.cohorts / "knowledge_cohorts.tsv")
    cohort_manifest_sha = _sha(args.cohorts / "manifest.json")
    taxids = _taxid_filter(args.taxid)
    selected_aspects = tuple(dict.fromkeys(args.aspect))
    selected_eligible, knowledge_labels = select_eligible_pairs(
        eligible=benchmark.eligible,
        cohorts=cohort_rows,
        knowledge=args.knowledge,
        aspects=set(selected_aspects),
        species=benchmark.species,
        taxids=taxids,
    )
    selected_truth = {key: benchmark.truth[key] for key in selected_eligible}
    selected_pair_counts = {
        "by_aspect": {
            aspect: sum(key[1] == aspect for key in selected_eligible)
            for aspect in ("F", "P", "C")
        },
        "by_knowledge_class": {
            knowledge: sum(
                knowledge_labels[key] == knowledge for key in selected_eligible
            )
            for knowledge in ("NK", "LK", "PK")
        },
    }
    ia_manifest_sha = _sha(args.ia_manifest)
    weights, ia_manifest = _read_ia(
        args.ia_table,
        args.ia_manifest,
        benchmark.provenance["ontology_sha256"],
        benchmark.graph,
    )
    ia_table_sha = ia_manifest["ia_table_sha256"]
    if _sha(args.ia_manifest) != ia_manifest_sha:
        raise ValueError("IA manifest changed during validation")
    reports = {}
    curve_rows = []
    plot_series = {
        aspect: {metric: {} for metric in PLOT_METRICS}
        for aspect in ("F", "P", "C")
        if aspect in selected_aspects
    }
    pr_plot_series = {aspect: {} for aspect in selected_aspects}
    input_fingerprints = {}
    working_dir = Path(
        tempfile.mkdtemp(prefix="progeny-evaluation-", dir=output_dir.parent)
    )
    for method_id, raw_path in methods:
        prediction_path = raw_path.resolve(strict=True)
        if raw_path.absolute() != prediction_path or not prediction_path.is_file():
            raise ValueError(f"Prediction file is not a regular file: {raw_path}")
        prediction_sha = _digest(prediction_path)
        prepared = benchmark.prepare(prediction_path)
        filtered_scores = {
            key: score
            for key, score in prepared.scores.items()
            if key[:2] in selected_eligible
        }
        unweighted = evaluate_scores(
            eligible=selected_eligible,
            truth=selected_truth,
            scores=filtered_scores,
            species=benchmark.species,
            aspects=selected_aspects,
            taxids=None,
            thresholds=thresholds,
        )
        weighted = evaluate_weighted_scores(
            eligible=selected_eligible,
            truth=selected_truth,
            scores=filtered_scores,
            information_accretion=weights,
            species=benchmark.species,
            aspects=selected_aspects,
            thresholds=thresholds,
            taxids=None,
        )
        if _digest(prediction_path) != prediction_sha:
            raise ValueError(f"Prediction file changed during evaluation: {method_id}")
        reports[method_id] = {
            "prediction_path": str(prediction_path),
            "prediction_sha256": prediction_sha,
            "preparation_counts": prepared.counts,
            "selected_scoring_target_aspects": len(selected_eligible),
            "unweighted": {
                aspect: {key: value for key, value in report.items() if key != "curve"}
                for aspect, report in unweighted["aspects"].items()
            },
            "weighted": {
                aspect: {key: value for key, value in report.items() if key != "curve"}
                for aspect, report in weighted.items()
            },
        }
        input_fingerprints[method_id] = prediction_sha
        audit_path = _audit_path(working_dir, method_id)
        reports[method_id]["go_resolution_audit_file"] = audit_path.name
        with audit_path.open("x", encoding="utf-8") as audit_stream:
            for audit_row in prepared.go_audit:
                audit_stream.write(
                    json.dumps(audit_row, sort_keys=True, allow_nan=False) + "\n"
                )
        filtered_predictions_path = (
            working_dir / f"filtered_predictions_{_safe_method_filename(method_id)}.tsv"
        )
        filtered_prepared = type(prepared)(
            scores=filtered_scores,
            counts=prepared.counts,
            go_audit=prepared.go_audit,
        )
        _write_prepared_predictions(
            filtered_predictions_path,
            filtered_prepared,
            method_id=method_id,
            labels=knowledge_labels,
            species=benchmark.species,
        )
        reports[method_id]["filtered_predictions_file"] = filtered_predictions_path.name
        for aspect in selected_aspects:
            unweighted_curve = unweighted["aspects"][aspect]["curve"]
            weighted_curve = weighted[aspect]["curve"]
            if len(unweighted_curve) != len(weighted_curve):
                raise ArithmeticError("Weighted and unweighted threshold grids differ")
            method_series = []
            for raw_point, weighted_point in zip(
                unweighted_curve, weighted_curve, strict=True
            ):
                if raw_point["threshold"] != weighted_point["threshold"]:
                    raise ArithmeticError("Method threshold grids are inconsistent")
                row = {
                    "method_id": method_id,
                    "aspect": aspect,
                    "threshold": raw_point["threshold"],
                    "precision": raw_point["precision"],
                    "recall": raw_point["recall_full"],
                    "f1": raw_point["f1_full"],
                    "coverage": raw_point["coverage"],
                    "weighted_precision": weighted_point["weighted_precision"],
                    "weighted_recall": weighted_point["weighted_recall"],
                    "weighted_f1": weighted_point["weighted_f1"],
                    "weighted_coverage": weighted_point["weighted_coverage"],
                    "ru": weighted_point["ru"],
                    "mi": weighted_point["mi"],
                    "smin": weighted_point["smin"],
                }
                curve_rows.append(row)
                method_series.append(row)
            for metric in PLOT_METRICS:
                plot_series[aspect][metric][method_id] = method_series
            pr_plot_series[aspect][method_id] = [
                {"recall": row["recall"], "precision": row["precision"]}
                for row in method_series
            ]

    _write_curve_table(working_dir / "curves.tsv", curve_rows)
    plots_dir = working_dir / "plots"
    plots_dir.mkdir()
    plot_inventory = []
    for aspect, metrics in plot_series.items():
        for metric, (field, unit_range) in PLOT_METRICS.items():
            path = plots_dir / f"{metric}_{aspect}.svg"
            svg = render_metric_svg(
                aspect=ASPECT_LABELS[aspect],
                metric=field,
                series=metrics[metric],
                ylabel=field,
                fixed_unit_range=unit_range,
            )
            path.write_text(svg, encoding="utf-8", newline="\n")
            plot_inventory.append(path.relative_to(working_dir).as_posix())
        pr_path = plots_dir / f"precision_recall_{aspect}.svg"
        pr_path.write_text(
            render_precision_recall_svg(
                aspect=ASPECT_LABELS[aspect], series=pr_plot_series[aspect]
            ),
            encoding="utf-8",
            newline="\n",
        )
        plot_inventory.append(pr_path.relative_to(working_dir).as_posix())
    if _sha(args.ia_table) != ia_table_sha or _sha(args.ia_manifest) != ia_manifest_sha:
        raise ValueError("IA artifact changed during evaluation")
    if (
        _sha(args.cohorts / "knowledge_cohorts.tsv") != cohort_table_sha
        or _sha(args.cohorts / "manifest.json") != cohort_manifest_sha
    ):
        raise ValueError("Knowledge cohort publication changed during evaluation")
    if _sha(args.ontology) != benchmark.provenance["ontology_sha256"]:
        raise ValueError("Pinned ontology changed during evaluation")
    if _sha(args.run / "results/benchmark/manifest.json") != args.benchmark_sha256:
        raise ValueError("Benchmark manifest changed during evaluation")
    implementation_after = {
        name: _sha(repository / name) for name in IMPLEMENTATION_FILES
    }
    if implementation_after != implementation_before:
        raise ValueError("Implementation changed during evaluation")
    artifact_paths = [working_dir / "curves.tsv"]
    artifact_paths.extend(
        working_dir / reports[method_id]["filtered_predictions_file"]
        for method_id, _ in methods
    )
    artifact_paths.extend(
        working_dir / reports[method_id]["go_resolution_audit_file"]
        for method_id, _ in methods
    )
    artifact_paths.extend(
        plots_dir / name
        for name in sorted(path.name for path in plots_dir.iterdir() if path.is_file())
    )
    report = {
        "schema": SCHEMA,
        "status": "EVALUATED",
        "benchmark_sha256": args.benchmark_sha256,
        "ontology_sha256": benchmark.provenance["ontology_sha256"],
        "ia_manifest_sha256": ia_manifest_sha,
        "ia_table_sha256": ia_table_sha,
        "ia_source_role": ia_manifest["source_role"],
        "ia_source_release_id": ia_manifest["source_release_id"],
        "ia_source_gaf_sha256": ia_manifest["gaf_sha256"],
        "threshold_profile": {
            "name": "CAFA_FIXED_GRID",
            "step": args.threshold_step,
            "interval": "[step, 1)",
            "comparison": "score >= threshold",
            "threshold_count": len(thresholds),
        },
        "aspects": list(selected_aspects),
        "knowledge_classes": (
            sorted(args.knowledge) if args.knowledge else ["NK", "LK", "PK"]
        ),
        "taxids": sorted(taxids) if taxids else None,
        "cohort_manifest_sha256": _sha(args.cohorts / "manifest.json"),
        "cohort_table_sha256": cohort_table_sha,
        "cohort_manifest_schema": cohort_manifest["schema"],
        "selected_target_aspects": len(selected_eligible),
        "selected_target_aspect_counts": selected_pair_counts,
        "methods": reports,
        "curve_table": "curves.tsv",
        "plots": plot_inventory,
        "artifact_sha256": {
            path.relative_to(working_dir).as_posix(): _sha(path)
            for path in artifact_paths
        },
        "source_git_head": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        or None,
        "implementation_sha256": implementation_before,
    }
    with (working_dir / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    if any(
        _digest(path.resolve(strict=True)) != digest
        for method, path in methods
        for digest in [input_fingerprints[method]]
    ):
        raise ValueError("A method prediction file changed before report completion")
    if output_dir.exists():
        raise ValueError("Evaluation output directory appeared during calculation")
    working_dir.rename(output_dir)
    print(json.dumps({"status": "EVALUATED", "output_dir": str(output_dir)}))


if __name__ == "__main__":
    main()
