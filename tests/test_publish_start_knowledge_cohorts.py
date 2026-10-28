from __future__ import annotations

import sqlite3

from scripts.evaluation.publish_start_knowledge_cohorts import (
    _query_target_score_evidence,
)


def test_query_uses_accepted_target_id_not_donor_accession_equality():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE direct_support ("
        "release TEXT, target_id TEXT, aspect TEXT, source_go TEXT, "
        "evidence_code TEXT, rid TEXT, assertion_id TEXT, "
        "normalized_gaf_line INTEGER, gaf_relation TEXT, gaf_qualifier TEXT, "
        "donor_accession TEXT, polarity TEXT)"
    )
    rows = [
        (
            "START",
            "T1",
            "F",
            "GO:0000001",
            "EXP",
            "1",
            "assertion-1",
            10,
            "enables",
            "",
            "ACCEPTED_DONOR",
            "POSITIVE",
        ),
        (
            "START",
            "T1",
            "F",
            "GO:0000002",
            "IEA",
            "2",
            "assertion-2",
            11,
            "enables",
            "",
            "ANOTHER_DONOR",
            "POSITIVE",
        ),
        (
            "START",
            "T1",
            "F",
            "GO:0000003",
            "EXP",
            "3",
            "assertion-3",
            12,
            "enables",
            "NOT",
            "NOT_DONOR",
            "NEGATIVE",
        ),
        (
            "START",
            "T2",
            "P",
            "GO:0000004",
            "EXP",
            "4",
            "assertion-4",
            13,
            "involved_in",
            "",
            "OTHER_TARGET_DONOR",
            "POSITIVE",
        ),
    ]
    connection.executemany(
        "INSERT INTO direct_support VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )

    evidence = _query_target_score_evidence(
        connection,
        release="START",
        target_identity={"TARGET_ACCESSION": "T1"},
        target_ids={"TARGET_ACCESSION"},
    )

    assert len(evidence) == 1
    assert evidence[0]["original_id"] == "TARGET_ACCESSION"
    assert evidence[0]["internal_target_id"] == "T1"
    assert evidence[0]["donor_accession"] == "ACCEPTED_DONOR"
    connection.close()
