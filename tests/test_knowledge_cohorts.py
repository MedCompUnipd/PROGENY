from __future__ import annotations

import pytest

from progeny.knowledge_cohorts import assign_knowledge_classes, select_eligible_pairs


def _derive(rows):
    eligible = {
        ("A", "F"),
        ("A", "P"),
        ("B", "F"),
        ("C", "C"),
    }
    return assign_knowledge_classes(
        eligible=eligible,
        species={"A": "9606", "B": "10090", "C": "3702"},
        internal_ids={"A": "T1", "B": "T2", "C": "T3"},
        direct_evidence=rows,
        resolve_go=lambda go: ("GO:0000001", "active"),
        go_aspect=lambda _go: "F",
    )


def test_direct_target_score_evidence_assigns_pair_specific_classes():
    cohorts, audit, counts = _derive(
        [
            {
                "original_id": "A",
                "aspect": "F",
                "go_id": "GO:0000001",
                "evidence_code": "EXP",
            }
        ]
    )
    labels = {
        (row["original_id"], row["aspect"]): row["knowledge_class"] for row in cohorts
    }
    assert labels == {
        ("A", "F"): "PK",
        ("A", "P"): "LK",
        ("B", "F"): "NK",
        ("C", "C"): "NK",
    }
    assert len(audit) == 1
    assert counts["F_PK"] == 1
    assert counts["evidence_EXP"] == 1


def test_replaced_go_is_kept_only_when_replacement_stays_in_aspect():
    rows = [
        {
            "original_id": "A",
            "aspect": "F",
            "go_id": "GO:0000009",
            "evidence_code": "IDA",
        }
    ]
    cohorts, audit, _ = assign_knowledge_classes(
        eligible={("A", "F")},
        species={"A": "9606"},
        internal_ids={"A": "T1"},
        direct_evidence=rows,
        resolve_go=lambda _go: ("GO:0000001", "replaced"),
        go_aspect=lambda _go: "F",
    )
    assert cohorts[0]["knowledge_class"] == "PK"
    assert audit[0]["action"] == "KEEP_DIRECT_EVIDENCE"

    cohorts, audit, _ = assign_knowledge_classes(
        eligible={("A", "F")},
        species={"A": "9606"},
        internal_ids={"A": "T1"},
        direct_evidence=rows,
        resolve_go=lambda _go: ("GO:0000002", "replaced"),
        go_aspect=lambda _go: "P",
    )
    assert cohorts[0]["knowledge_class"] == "NK"
    assert audit[0]["action"] == "EXCLUDE_CROSS_ASPECT_REPLACEMENT"


def test_donor_transfer_and_non_score_codes_are_rejected_by_contract():
    with pytest.raises(ValueError, match="outside the SCORE policy"):
        _derive(
            [
                {
                    "original_id": "A",
                    "aspect": "F",
                    "go_id": "GO:0000001",
                    "evidence_code": "IEA",
                }
            ]
        )
    with pytest.raises(ValueError, match="non-benchmark target"):
        _derive(
            [
                {
                    "original_id": "donor",
                    "aspect": "F",
                    "go_id": "GO:0000001",
                    "evidence_code": "EXP",
                }
            ]
        )


def test_cohort_filter_keeps_only_selected_denominator_pairs():
    eligible = {("A", "F"), ("A", "P"), ("B", "F")}
    cohorts = [
        {
            "original_id": "A",
            "aspect": "F",
            "knowledge_class": "PK",
            "species_taxid": "9606",
        },
        {
            "original_id": "A",
            "aspect": "P",
            "knowledge_class": "LK",
            "species_taxid": "9606",
        },
        {
            "original_id": "B",
            "aspect": "F",
            "knowledge_class": "NK",
            "species_taxid": "10090",
        },
    ]
    selected, labels = select_eligible_pairs(
        eligible=eligible,
        cohorts=cohorts,
        knowledge={"NK", "LK"},
        aspects={"F", "P"},
        species={"A": "9606", "B": "10090"},
        taxids={"9606"},
    )
    assert selected == frozenset({("A", "P")})
    assert labels[("A", "P")] == "LK"


@pytest.mark.parametrize(
    "rows",
    [
        [
            {
                "original_id": "A",
                "aspect": "F",
                "knowledge_class": "PK",
                "species_taxid": "9606",
            },
            {
                "original_id": "A",
                "aspect": "F",
                "knowledge_class": "PK",
                "species_taxid": "9606",
            },
        ],
        [
            {
                "original_id": "A",
                "aspect": "F",
                "knowledge_class": "UNKNOWN",
                "species_taxid": "9606",
            }
        ],
    ],
)
def test_filter_rejects_duplicate_or_invalid_cohort_rows(rows):
    with pytest.raises(ValueError):
        select_eligible_pairs(
            eligible={("A", "F")},
            cohorts=rows,
            knowledge=None,
            aspects={"F"},
            species={"A": "9606"},
            taxids=None,
        )


def test_filter_rejects_incomplete_cohort_coverage():
    with pytest.raises(ValueError, match="cover every eligible"):
        select_eligible_pairs(
            eligible={("A", "F"), ("B", "P")},
            cohorts=[
                {
                    "original_id": "A",
                    "aspect": "F",
                    "knowledge_class": "NK",
                    "species_taxid": "9606",
                }
            ],
            knowledge=None,
            aspects={"F"},
            species={"A": "9606", "B": "10090"},
            taxids=None,
        )
