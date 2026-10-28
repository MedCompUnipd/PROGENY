"""M2 end-to-end tests use the certified synthetic collector fixture from M1."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_alpha_benchmark_export import _sha
from test_prediction_inputs import bundle as bundle

from progeny.prediction_inputs import load_benchmark_inputs
from progeny.prediction_metrics import evaluate_scores

ROOT = Path(__file__).resolve().parents[1]


def _predictions(tmp_path, body):
    path = tmp_path / "predictions.tsv"
    path.write_text("query_id\tgo_id\tscore\n" + body, encoding="utf-8")
    return path


def _cli(bundle, predictions, *extra, check=True):
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "scripts/evaluation/evaluate_predictions.py"),
            "--dataset",
            str(bundle["dataset"]),
            "--run",
            str(bundle["run"]),
            "--ontology",
            str(bundle["ontology_path"]),
            "--benchmark-sha256",
            bundle["benchmark_sha256"],
            "--predictions",
            str(predictions),
            "--method-id",
            "synthetic_test",
            *extra,
        ],
        check=check,
        capture_output=True,
        text=True,
    )


def test_cli_perfect_predictions_propagate_before_metrics(bundle, tmp_path):
    path = _predictions(tmp_path, "T1\tGO:0000001\t0.8\nT3\tGO:0000003\t0.9\n")
    report = json.loads(_cli(bundle, path).stdout)
    metrics = report["metrics"]["aspects"]["F"]
    assert metrics["full"]["fmax"] == 1
    assert metrics["full"]["threshold"] == 0.8
    assert metrics["truth_terms"] == 3
    assert metrics["scorable_pairs"] == 3
    assert "curve" not in metrics
    assert report["curves_included"] is False
    assert report["source_identity"]["ontology_sha256"] == _sha(bundle["ontology_path"])
    assert report["predictions"]["sha256"] == _sha(path)
    assert report["implementation_sha256"]["src/progeny/prediction_metrics.py"]


def test_cli_missing_target_stays_in_full_recall(bundle, tmp_path):
    path = _predictions(tmp_path, "T1\tGO:0000001\t0.8\n")
    report = json.loads(_cli(bundle, path, "--include-curves").stdout)
    metrics = report["metrics"]["aspects"]["F"]
    assert metrics["eligible_targets"] == 2
    assert metrics["full"]["fmax"] == pytest.approx(2 / 3)
    assert metrics["full"]["recall"] == 0.5
    assert metrics["covered_normalization_secondary"]["fmax"] == 1
    assert metrics["curve"][-1]["fn"] == 1
    assert metrics["curve"][-1]["covered_targets"] == 1


def test_masked_direct_prediction_can_recover_unmasked_ancestor(bundle, tmp_path):
    path = _predictions(tmp_path, "T1\tGO:0000002\t0.8\n")
    report = json.loads(_cli(bundle, path, "--include-curves").stdout)
    metrics = report["metrics"]["aspects"]["F"]
    assert metrics["full"]["fmax"] == pytest.approx(0.4)
    assert metrics["full"]["precision"] == 1
    assert metrics["full"]["recall"] == 0.25
    assert metrics["curve"][-1]["tp"] == 1
    assert metrics["curve"][-1]["operational_fp"] == 0
    counts = report["predictions"]["preparation_counts"]
    assert counts["skip_pairs_excluded"] == 1
    assert counts["neutral_pairs_excluded"] == 1


def test_unresolved_rows_are_excluded_without_shrinking_truth(bundle, tmp_path):
    path = _predictions(tmp_path, "T1\tGO:9999999\t0.99\n")
    report = json.loads(_cli(bundle, path, "--include-curves").stdout)
    metrics = report["metrics"]["aspects"]["F"]
    assert metrics["full"]["fmax"] == 0
    assert metrics["eligible_targets"] == 2
    assert metrics["truth_terms"] == 3
    assert metrics["curve"][-1]["fn"] == 3
    assert metrics["curve"][-1]["operational_fp"] == 0
    assert report["predictions"]["go_resolution_audit"][0]["action"] == "EXCLUDED"


def test_aliases_merge_before_counting_operational_false_positives(bundle, tmp_path):
    path = _predictions(tmp_path, "T1\tGO:0000009\t0.6\nT1\tGO:0000007\t0.9\n")
    report = json.loads(_cli(bundle, path, "--include-curves").stdout)
    metrics = report["metrics"]["aspects"]["F"]
    assert metrics["full"]["fmax"] == 0
    assert metrics["curve"][-1]["operational_fp"] == 1
    assert report["predictions"]["preparation_counts"]["remapped_rows"] == 2


def test_header_only_submission_has_defined_zero_metrics(bundle, tmp_path):
    path = _predictions(tmp_path, "")
    report = json.loads(_cli(bundle, path).stdout)
    assert report["metrics"]["aspects"]["F"]["full"]["fmax"] == 0
    assert report["metrics"]["aspects"]["P"]["full"]["fmax"] is None
    assert report["metrics"]["smin_status"].startswith("NOT_COMPUTED")


def test_taxid_filter_has_explicit_empty_denominator(bundle, tmp_path):
    path = _predictions(tmp_path, "T1\tGO:0000001\t0.8\n")
    report = json.loads(_cli(bundle, path, "--taxid", "999999").stdout)
    assert report["status"] == "NO_ELIGIBLE_TARGETS"
    assert report["metrics"]["population_after_filters"]["target_aspects"] == 0
    assert report["metrics"]["aspects"]["F"]["full"]["fmax"] is None
    assert report["predictions"]["preparation_counts"]["submitted_rows"] == 1


def test_cli_records_explicit_grid_and_aspect_selection(bundle, tmp_path):
    path = _predictions(tmp_path, "T1\tGO:0000001\t0.8\n")
    report = json.loads(
        _cli(bundle, path, "--threshold-step", "0.01", "--aspect", "F").stdout
    )
    assert report["threshold_grid_step"] == "0.01"
    assert list(report["metrics"]["aspects"]) == ["F"]
    assert report["metrics"]["aspects"]["F"]["thresholds_examined"] == 101


def test_cli_preserves_pending_scientific_audits(bundle, tmp_path):
    report = json.loads(_cli(bundle, _predictions(tmp_path, "")).stdout)
    source = report["source_identity"]
    assert source["knowledge_classification"].startswith("UNCLASSIFIED")
    assert source["documentary_lookahead_audit"] == "NOT_MEASURABLE_FROM_AGGREGATES"


def test_method_metadata_is_recorded_as_caller_declared(bundle, tmp_path):
    metadata = tmp_path / "method.json"
    metadata.write_text('{"version": "test", "training_cutoff": "unspecified"}')
    report = json.loads(
        _cli(
            bundle, _predictions(tmp_path, ""), "--method-metadata", str(metadata)
        ).stdout
    )
    assert report["method_metadata_status"] == "CALLER_DECLARED"
    assert report["method_metadata"]["version"] == "test"
    assert report["method_metadata_sha256"] == _sha(metadata)


def test_cli_invalid_score_emits_no_metric_report(bundle, tmp_path):
    path = _predictions(tmp_path, "T1\tGO:0000001\tNaN\n")
    result = _cli(bundle, path, check=False)
    assert result.returncode != 0
    assert result.stdout == ""


def test_cli_reads_only_without_mutating_source_bundle(bundle, tmp_path):
    path = _predictions(tmp_path, "T1\tGO:0000001\t0.8\n")

    def snapshot():
        return {str(p): _sha(p) for p in tmp_path.rglob("*") if p.is_file()}

    before = snapshot()
    _cli(bundle, path)
    assert snapshot() == before


def test_api_matches_cli_on_prepared_prediction_scores(bundle, tmp_path):
    path = _predictions(tmp_path, "T1\tGO:0000001\t0.8\n")
    inputs = load_benchmark_inputs(**bundle)
    result = evaluate_scores(
        eligible=inputs.eligible,
        truth=inputs.truth,
        scores=inputs.prepare(path).scores,
        species=inputs.species,
    )
    cli = json.loads(_cli(bundle, path, "--include-curves").stdout)
    assert cli["metrics"] == result
