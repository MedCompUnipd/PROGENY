"""R7 runtime profile, executable worker dispatch and sealed provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from progeny.canonical_v2 import dag_execution, fresh_publication
from progeny.canonical_v2.dag_contract import destination
from progeny.canonical_v2.runtime_resources import (
    SCHEMA,
    read_runtime_profile,
    validate_execution_resources,
)


def _profile() -> dict:
    return {
        "schema": SCHEMA,
        "m8_workers": 2,
        "temporal_workers": 16,
        "m8_mem_mb": 16384,
        "m10c_mem_mb": 32768,
        "temporal_mem_mb": 65536,
    }


def test_default_is_strictly_serial_outside_dp() -> None:
    value = read_runtime_profile(None)
    assert value.m8_workers == value.temporal_workers == 1
    assert value.requested_threads("workload", 32) == 1
    assert value.requested_threads("m10c", 32) == 1
    assert value.requested_threads("alignment", 32) == 32
    assert value.sha256 == "DEFAULT_SERIAL"


def test_profile_reservations_do_not_override_dp(tmp_path: Path) -> None:
    path = tmp_path / "resources.json"
    raw = json.dumps(_profile(), sort_keys=True).encode()
    path.write_bytes(raw)
    profile = read_runtime_profile(str(path))
    assert profile.sha256 == hashlib.sha256(raw).hexdigest()
    assert profile.requested_threads("m8", 8) == 2
    assert profile.requested_threads("temporal", 8) == 16
    assert profile.requested_threads("alignment", 8) == 8
    assert profile.reserved_memory("temporal", 512) == 65536
    assert profile.reserved_memory("alignment", 512) == 512


@pytest.mark.parametrize(
    "field,value",
    [
        ("m8_workers", 3),
        ("temporal_workers", 129),
        ("m8_workers", True),
        ("temporal_mem_mb", -1),
        ("m10c_mem_mb", 1_048_577),
    ],
)
def test_invalid_profile_values_fail_closed(tmp_path: Path, field, value):
    path = tmp_path / "bad.json"
    profile = _profile()
    profile[field] = value
    path.write_text(json.dumps(profile))
    with pytest.raises(ValueError, match="Invalid runtime resource"):
        read_runtime_profile(str(path))


def test_foreign_keys_and_symlinks_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "resources.json"
    profile = _profile()
    profile["scientific_override"] = True
    path.write_text(json.dumps(profile))
    with pytest.raises(ValueError, match="complete and exact"):
        read_runtime_profile(str(path))
    profile.pop("scientific_override")
    path.write_text(json.dumps(profile))
    link = tmp_path / "symlink.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="non-symlink"):
        read_runtime_profile(str(link))
    with pytest.raises(ValueError, match="absolute"):
        read_runtime_profile("resources.json")


def test_resource_schema_is_constrained() -> None:
    value = {"workers": 8, "mem_mb": 65536, "profile_sha256": "a" * 64}
    assert validate_execution_resources("temporal", value) == value
    with pytest.raises(ValueError, match="not supported"):
        validate_execution_resources("m10c", value)
    with pytest.raises(ValueError, match="effective worker"):
        validate_execution_resources("m8", value)
    with pytest.raises(ValueError, match="keys"):
        validate_execution_resources("temporal", {"workers": 8})
    with pytest.raises(ValueError, match="profile identity"):
        validate_execution_resources("temporal", {**value, "profile_sha256": "invalid"})


def test_fresh_intent_pins_actual_workers_and_profile(tmp_path: Path) -> None:
    from test_canonical_v2_fresh_publication import RECIPE, ReceiptFixture

    spec = ReceiptFixture(tmp_path).spec
    resources = {"workers": 2, "mem_mb": 16384, "profile_sha256": "a" * 64}
    bundle = destination(spec, "m8")
    bundle.parent.mkdir(parents=True, exist_ok=True)
    intent = fresh_publication._intent(
        spec=spec,
        stage="m8",
        role=None,
        recipe_sha256=RECIPE,
        runtime_resources=resources,
    )
    assert intent["runtime_resources"] == resources
    path = Path(f"{bundle}.fresh.intent.json")
    path.write_text(json.dumps(intent))
    receipt = fresh_publication._receipt(
        spec=spec,
        stage="m8",
        role=None,
        recipe_sha256=RECIPE,
        payload={},
    )
    fresh_publication.receipt_path(bundle).write_text(json.dumps(receipt))
    with patch.object(fresh_publication, "validate_publication", return_value={}):
        assert (
            fresh_publication.validate_node_receipt(
                spec=spec, stage="m8", role=None, recipe_sha256=RECIPE
            )
            == receipt
        )
        with pytest.raises(ValueError, match="intent differs"):
            fresh_publication.validate_node_receipt(
                spec=spec,
                stage="m8",
                role=None,
                recipe_sha256=RECIPE,
                runtime_resources={**resources, "workers": 1},
            )
    intent["runtime_resources"]["workers"] = 129
    path.write_text(json.dumps(intent))
    with (
        patch.object(fresh_publication, "validate_publication", return_value={}),
        pytest.raises(ValueError, match="effective worker"),
    ):
        fresh_publication.validate_node_receipt(
            spec=spec, stage="m8", role=None, recipe_sha256=RECIPE
        )


def test_dispatch_forwarding_is_real_not_decorative(tmp_path: Path) -> None:
    from test_canonical_v2_dag_contract import _spec

    spec = _spec(tmp_path)
    spec["mode"] = "execute"
    with patch.object(dag_execution, "_run_command") as command:
        for stage, workers in (("m8", 2), ("temporal", 8)):
            dag_execution.dispatch(
                spec=spec,
                stage=stage,
                target=destination(spec, stage),
                runtime_workers=workers,
            )
            argv = command.call_args.args[1]
            assert argv[argv.index("--workers") + 1] == str(workers)
            assert argv[-1] == "--execute"
    for stage, workers in (("m8", 3), ("m10c", 2), ("temporal", 129)):
        with pytest.raises(ValueError, match="worker"):
            dag_execution.dispatch(
                spec=spec,
                stage=stage,
                target=destination(spec, stage),
                runtime_workers=workers,
            )
