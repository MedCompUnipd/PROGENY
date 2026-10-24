"""Guard the two performance-only SQLite indexes and their query semantics."""

from __future__ import annotations

import inspect
import sqlite3

from progeny.canonical_v2 import release_candidate_boundary, release_workload


def _populate(db: sqlite3.Connection, index: bool) -> None:
    db.execute(
        "CREATE TABLE candidates (role TEXT,target TEXT,rid TEXT,"
        "identity TEXT,channel TEXT,documentary TEXT,seq_sha TEXT,"
        "overlap_verified INTEGER DEFAULT 0,"
        "PRIMARY KEY(role,target,rid))"
    )
    db.execute(
        "CREATE TABLE extra (role TEXT,target TEXT,rid INTEGER,"
        "identity TEXT,species TEXT,PRIMARY KEY(role,target,rid))"
    )
    for role in ("START", "END"):
        for target in range(200):
            for rid in range(1, 9):
                db.execute(
                    "INSERT INTO candidates VALUES (?,?,?,?,?,?,?,0)",
                    (role, f"T{target:04d}", str(rid), "ident", "EXACT", "{}", None),
                )
                db.execute(
                    "INSERT INTO extra VALUES (?,?,?,?,?)",
                    (role, f"T{target:04d}", rid, "ident", None),
                )
    if index:
        db.execute("CREATE INDEX candidates_by_role_rid ON candidates(role,rid)")
        db.execute("CREATE INDEX extra_by_role_rid ON extra(role,rid)")


def _exercise(index: bool) -> tuple[object, ...]:
    with sqlite3.connect(":memory:") as db:
        _populate(db, index)
        rows = db.execute(
            "SELECT identity,seq_sha FROM candidates WHERE role=? AND rid=? "
            "AND channel!='' AND documentary IS NOT NULL",
            ("START", "4"),
        ).fetchall()
        db.execute(
            "UPDATE candidates SET overlap_verified=1 WHERE role=? "
            "AND rid=? AND channel!='' AND documentary IS NOT NULL",
            ("START", "4"),
        )
        db.execute(
            "UPDATE candidates SET seq_sha=COALESCE(seq_sha,?) "
            "WHERE role=? AND rid=? AND channel!=''",
            ("digest", "START", "4"),
        )
        count = db.execute(
            "SELECT COUNT(*) FROM extra WHERE role=? AND rid=?",
            ("END", 4),
        ).fetchone()[0]
        result = db.execute(
            "SELECT role,target,rid,identity,channel,documentary,seq_sha,"
            "overlap_verified FROM candidates ORDER BY role,target,rid"
        ).fetchall()
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT identity,seq_sha FROM candidates "
            "WHERE role=? AND rid=? AND channel!='' "
            "AND documentary IS NOT NULL",
            ("START", "4"),
        ).fetchall()
        extra_plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM extra WHERE role=? AND rid=?",
            ("END", 4),
        ).fetchall()
        return rows, count, result, plan, extra_plan


def test_indexes_do_not_change_rows_or_overlap_flags() -> None:
    baseline = _exercise(False)
    optimized = _exercise(True)
    assert baseline[:3] == optimized[:3]
    assert optimized[1] == 200


def test_query_planner_uses_both_role_rid_columns() -> None:
    _, _, _, first, second = _exercise(True)
    assert any(
        "candidates_by_role_rid (role=? AND rid=?)" in item[-1] for item in first
    )
    assert any("extra_by_role_rid (role=? AND rid=?)" in item[-1] for item in second)


def test_index_creation_is_after_bulk_inserts() -> None:
    boundary = inspect.getsource(
        release_candidate_boundary.prepare_release_candidate_boundary
    )
    workload = inspect.getsource(release_workload.build_release_workload)
    first_import = boundary.index("_validate_evidence(")
    first_index = boundary.index("CREATE INDEX candidates_by_role_rid")
    first_lookup = boundary.index("_verify_overlap_sequence(")
    assert first_import < first_index < first_lookup

    second_import = workload.index("_merged_primary(")
    second_index = workload.index("CREATE INDEX extra_by_role_rid")
    second_lookup = workload.index("_merged_stores(")
    assert second_import < second_index < second_lookup
