"""Exact GO/NOT support oracle for the per-target M10C RAM reducer."""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from progeny import stage08_compact_interpretation as interpretation
from progeny.stage08_go_closure import GoClosureIndex


def _graph() -> GoClosureIndex:
    aspects = {f"GO:{i:07d}": "F" for i in range(1, 25)}
    edges = [(f"GO:{i:07d}", "is_a", f"GO:{i - 1:07d}") for i in range(2, 25)]
    return GoClosureIndex(aspects, edges)


def _input(conn: sqlite3.Connection, targets: int):
    records = []
    for release in ("2023_01", "2026_03"):
        for target in range(targets):
            for go in (5, 8, 11, 14, 17, 20):
                for polarity in ("POSITIVE", "NOT"):
                    for code in ("EXP", "IEA"):
                        for rid in range(2):
                            assertion = f"{go}:{polarity}:{code}"
                            records.append(
                                (
                                    release,
                                    f"T{target:03d}",
                                    "F",
                                    f"GO:{go:07d}",
                                    polarity,
                                    code,
                                    f"RID{rid}",
                                    assertion,
                                    go,
                                    "P1",
                                    "is_a",
                                    "NOT" if polarity == "NOT" else "",
                                )
                            )
    conn.executemany(
        "INSERT INTO direct_support VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        records,
    )
    conn.commit()
    return records


@pytest.mark.parametrize("targets", [1, 2, 8])
@pytest.mark.parametrize("max_keys", [1, 7, 32768])
def test_exact_supports_with_forced_memory_spill(
    tmp_path: Path,
    monkeypatch,
    targets: int,
    max_keys: int,
):
    monkeypatch.setattr(interpretation, "_M10C_MAX_AGGREGATE_KEYS", max_keys)
    graph = _graph()
    conn = interpretation._database(tmp_path / "m10c.sqlite3")
    rows = _input(conn, targets)
    oracle: Counter = Counter()
    direct_oracle: Counter = Counter()
    for release, target, aspect, source_go, polarity, code, *_ in rows:
        closure = (
            graph.ancestors(source_go)
            if polarity == "POSITIVE"
            else graph.descendants(source_go)
        )
        for go in closure:
            key = (release, target, aspect, go, polarity, code)
            oracle[key] += 1
            if go == source_go:
                direct_oracle[key] += 1
    groups, expanded = interpretation._propagate_unique_groups(conn, graph)
    actual = {
        tuple(row[:6]): (row[6], row[7])
        for row in conn.execute("""
            SELECT release, target_id, aspect, go_id, polarity,
                   evidence_code, support_count, direct_count
            FROM term_code_support
        """)
    }
    assert actual == {
        key: (supports, direct_oracle[key]) for key, supports in oracle.items()
    }
    assert expanded == sum(oracle.values()) // 2
    assert groups == len(rows) // 2
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    result = tmp_path / "terms.tsv"
    terms, conflicts = interpretation._write_term_summary(conn, result)
    assert terms > 0 and conflicts > 0
    assert result.read_text().splitlines()[0].startswith("release\t")
    conn.close()
