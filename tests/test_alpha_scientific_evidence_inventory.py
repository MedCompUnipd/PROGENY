"""Published M8 evidence inventory is reconciled before reporting."""

from __future__ import annotations

import csv

import pytest
from test_alpha_benchmark_export import _json, _tsv
from test_alpha_scientific_publish import _ready

from progeny.alpha_scientific_publish import publish_scientific_benchmark


def _m8(temporal):
    m8 = temporal.parent / "m8"
    _json(
        m8 / "08_collection_summary.json",
        {
            "by_role": {
                "START": {
                    "release": "2023_01",
                    "retrieved_source_rows": 4,
                    "annotation_links": 7,
                },
                "END": {
                    "release": "2026_03",
                    "retrieved_source_rows": 3,
                    "annotation_links": 5,
                },
            }
        },
    )
    header = (
        "release",
        "evidence_code",
        "aspect",
        "polarity",
        "source_rows",
        "association_links",
    )
    _tsv(
        m8 / "08_start_evidence_inventory.tsv",
        header,
        [("2023_01", "IEA", "F", "POSITIVE", 4, 7)],
    )
    _tsv(
        m8 / "08_end_evidence_inventory.tsv",
        header,
        [("2026_03", "IDA", "F", "POSITIVE", 3, 5)],
    )
    return m8


def test_m8_evidence_inventory_by_release(tmp_path):
    dataset, run, temporal = _ready(tmp_path)
    _m8(temporal)
    output = publish_scientific_benchmark(dataset, run)
    with (output / "evidence_by_release.tsv").open(newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert len(rows) == 2
    assert {row["evidence_code"] for row in rows} == {"IEA", "IDA"}
    assert (
        output.joinpath("statistics.json").read_text().count("CERTIFIED_M8_INVENTORY")
        == 1
    )


def test_m8_inventory_mismatch_is_blocking(tmp_path):
    dataset, run, temporal = _ready(tmp_path)
    m8 = _m8(temporal)
    path = m8 / "08_end_evidence_inventory.tsv"
    path.write_text(path.read_text().replace("\t3\t5", "\t3\t4"))
    with pytest.raises(ValueError, match="association-link totals"):
        publish_scientific_benchmark(dataset, run)
    assert not run.joinpath("results/benchmark").exists()
