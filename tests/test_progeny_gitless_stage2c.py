"""Isolated synthetic tests for Stage 2C provenance with/without .git."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

MODULES = ("progeny.stage2c_discovery", "progeny.stage2c_full_exact")


def prepare(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str):
    module = importlib.import_module(name)
    repo = tmp_path / "source_checkout"
    run = tmp_path / "run"
    repo.mkdir()
    run.mkdir()
    for filename in module.CODE_FILES:
        path = repo / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test-science-source\n", encoding="utf-8")
    if name.endswith("stage2c_discovery"):
        binary = module._binary(repo)
        monkeypatch.setattr(
            module,
            "_release_sources",
            lambda root, role: {"role": role, "source": "fixture"},
        )
        monkeypatch.setattr(
            module,
            "_scan_parameters",
            lambda root: {"fragment_policy": "exclude", "k": 3},
        )
    else:
        binary = repo / module.BINARY
        monkeypatch.setattr(
            module,
            "_sources",
            lambda root, role: {"role": role, "source": "fixture"},
        )
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"synthetic-native-binary\n")
    return module, repo, run


@pytest.mark.parametrize("name", MODULES)
def test_gitless_plan_is_pinned_and_does_not_call_git(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    module, repo, run = prepare(monkeypatch, tmp_path, name)
    with patch.object(
        module.subprocess, "run", side_effect=AssertionError("Git invoked")
    ):
        first = module.build_plan(repo, run)
        second = module.build_plan(repo, run)
    assert first == second
    assert first["git_head_at_creation"] is None
    assert len(first["key"]) == 64
    assert len(first["binary_sha256"]) == 64
    assert set(first["code"]) == set(module.CODE_FILES)
    assert first["paths"]["START"] != first["paths"]["END"]


@pytest.mark.parametrize("name", MODULES)
def test_git_checkout_preserves_real_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    module, repo, run = prepare(monkeypatch, tmp_path, name)
    (repo / ".git").mkdir()
    head = "a" * 40
    commands = []

    def fake_run(argv, **kwargs):
        commands.append(argv[-1])
        assert kwargs["check"] is True
        return SimpleNamespace(
            stdout="true\n" if argv[-1] == "--is-inside-work-tree" else head + "\n"
        )

    with patch.object(module.subprocess, "run", side_effect=fake_run):
        plan = module.build_plan(repo, run)
    assert commands == ["--is-inside-work-tree", "HEAD"]
    assert plan["git_head_at_creation"] == head


@pytest.mark.parametrize("name", MODULES)
def test_failed_git_identity_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    module, repo, run = prepare(monkeypatch, tmp_path, name)
    (repo / ".git").mkdir()
    with (
        patch.object(
            module.subprocess,
            "run",
            return_value=SimpleNamespace(stdout="false\n"),
        ),
        pytest.raises(ValueError, match="Not a Git worktree"),
    ):
        module.build_plan(repo, run)


@pytest.mark.parametrize("name", MODULES)
def test_git_metadata_symlink_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    module, repo, run = prepare(monkeypatch, tmp_path, name)
    (repo / ".git").symlink_to(run, target_is_directory=True)
    with pytest.raises(ValueError, match="Symlinked Git metadata"):
        module.build_plan(repo, run)


@pytest.mark.parametrize("name", MODULES)
def test_changed_planner_code_changes_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    module, repo, run = prepare(monkeypatch, tmp_path, name)
    before = module.build_plan(repo, run)
    source = repo / module.CODE_FILES[0]
    source.write_text("modified-science-source\n", encoding="utf-8")
    after = module.build_plan(repo, run)
    assert before["key"] != after["key"]
    assert before["code"] != after["code"]
