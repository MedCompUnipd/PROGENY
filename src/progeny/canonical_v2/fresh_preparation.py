"""Prepare a canonical fresh run without executing scientific producers.

A caller supplies all biological inputs, policies and executable paths in a
complete specification. No previous run is used as a template or baseline.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from progeny.canonical_v2.fresh_dag import SCHEMA, read_recipe
from progeny.canonical_v2.run_isolation import POLICY, create_scratch, scratch_paths
from progeny.workflow.config import PipelineConfig

RECIPE_FIELDS = frozenset(
    {
        "identity_sha256",
        "policy",
        "limits",
        "tools",
        "targets_input",
        "evidence_registry",
        "temporal_policy",
        "large_dp",
    }
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plain_file(value: str, description: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError(f"{description} must be an existing absolute regular file")
    if path.resolve(strict=True) != path:
        raise ValueError(f"{description} must use a physical canonical path")
    return path


def _input_files(pipeline: dict[str, Any], options: dict[str, Any]) -> dict[str, Path]:
    sources = {
        "targets.fasta": pipeline["targets"]["fasta"],
        "targets.metadata": pipeline["targets"]["metadata"],
        "ontology": pipeline["ontology"]["path"],
        "evidence_registry": options["evidence_registry"],
        "temporal_policy": options["temporal_policy"],
    }
    for role in ("START", "END"):
        release = pipeline["releases"][role]
        sources[f"{role}.goa"] = release["goa"]
        for index, value in enumerate(release["uniprot_sources"]):
            sources[f"{role}.uniprot.{index}"] = value
        for name in ("nodes", "names", "merged", "deleted"):
            sources[f"{role}.taxonomy.{name}"] = release["taxonomy"][name]
    return {key: _plain_file(value, key) for key, value in sorted(sources.items())}


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def prepare(
    *,
    repo: Path,
    run: Path,
    spec_path: Path,
    hash_biological_inputs: bool = False,
) -> dict[str, Any]:
    """Create a virgin run's controls; reject existing run roots.

    Identity is supplied, not silently redefined: its origin must be audited
    independently. The optional full-input hashes are a separate attestation.
    """
    repo = repo.resolve(strict=True)
    if not run.is_absolute():
        raise ValueError("run path must be absolute")
    _plain_file(str(spec_path), "specification")
    canonical = repo / "src/progeny/canonical_v2/fresh_dag.py"
    if not repo.is_dir() or not canonical.is_file():
        raise ValueError("repo is not a canonical V2 source checkout")
    if run.exists() or run.is_symlink():
        raise FileExistsError(f"run root already exists: {run}")
    if repo == run or repo in run.parents or run in repo.parents:
        raise ValueError("run and repo trees must not overlap")
    if run.parent.resolve(strict=True) != run.parent:
        raise ValueError("run parent must already exist and be a physical path")

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or set(spec) != {"pipeline", "recipe"}:
        raise ValueError("spec must contain exactly pipeline and recipe mappings")
    pipeline = deepcopy(spec["pipeline"])
    options = deepcopy(spec["recipe"])
    if not isinstance(options, dict) or not isinstance(pipeline, dict):
        raise ValueError("pipeline and recipe must be mappings")
    if not RECIPE_FIELDS - {"large_dp"} <= options.keys():
        raise ValueError("recipe specification is incomplete")
    if set(options) - RECIPE_FIELDS:
        raise ValueError("unknown recipe specification keys")

    pipeline["locations"] = {
        "work": str(run / "work/pipeline-v2"),
        "output": str(run / "results/pipeline-v2"),
        "logs": str(run / "logs/pipeline-v2"),
    }
    validated = PipelineConfig.from_mapping(pipeline).data
    if validated["targets"]["mode"] != "canonical":
        raise ValueError("fresh preparation requires canonical targets")
    if validated["targets"]["metadata"] != options["targets_input"]:
        raise ValueError("recipe targets_input must equal target metadata")
    inputs = _input_files(validated, options)
    for name in ("partial_sequence", "documentary_fragment"):
        configured = validated["annotation_donor"][name]
        if configured != options["limits"][name]:
            raise ValueError(f"annotation_donor.{name} differs from recipe limits")
    expected_ontology = validated["ontology"]["expected_sha256"]
    if expected_ontology is not None:
        actual_ontology = _sha256(inputs["ontology"])
        if actual_ontology.lower() != expected_ontology.lower():
            raise ValueError("ontology.expected_sha256 does not match the source")
    if not isinstance(options["tools"], dict):
        raise ValueError("tools must be a mapping")
    for label, path in options["tools"].items():
        tool = _plain_file(path, f"tool.{label}")
        if not tool.is_relative_to(repo):
            raise ValueError(f"tool {label} is outside checkout")
    if "large_dp" in options:
        if not isinstance(options["large_dp"], dict):
            raise ValueError("large_dp must be a mapping")
        requested = options["large_dp"].get("scratch_root")
        expected = str(scratch_paths(run)[0])
        if requested not in (None, expected):
            raise ValueError("New runs require large_dp.scratch_root=RUN/tmp")
        options["large_dp"]["scratch_root"] = expected
        _plain_file(options["large_dp"]["binary"], "large_dp.binary")
    identity = options["identity_sha256"]
    if not isinstance(identity, str) or len(identity) != 64:
        raise ValueError("identity_sha256 must be an explicit 64-digit digest")

    provenance = {
        "schema": "progeny-fresh-preparation-attestation-v1",
        "identity_origin": "externally supplied; not recomputed",
        "identity_sha256": options["identity_sha256"],
        "scratch_policy": POLICY,
        "scratch_root": str(scratch_paths(run)[0]),
        "spec_sha256": _sha256(spec_path),
        "input_hash_mode": "full" if hash_biological_inputs else "not_computed",
        "biological_inputs": {
            key: {
                "path": str(path),
                "sha256": _sha256(path) if hash_biological_inputs else None,
            }
            for key, path in inputs.items()
        },
    }
    recipe = {
        **options,
        "schema": SCHEMA,
        "repo_root": str(repo),
        "run_root": str(run),
        "pipeline_config": str(run / "pipeline.stage08.collection.yaml"),
    }
    # All validation above is read-only; directory creation is exclusive.
    run.mkdir(mode=0o700)
    try:
        create_scratch(run, identity)
        config_path = run / "pipeline.stage08.collection.yaml"
        yaml_text = yaml.safe_dump(validated, sort_keys=False)
        config_path.write_text(yaml_text, encoding="utf-8")
        recipe_path = run / "fresh_recipe.json"
        recipe_path.write_bytes(_canonical_json(recipe))
        parsed = read_recipe(recipe_path, expected_repo=repo)
        if parsed.data != recipe:
            raise ValueError("canonical parser changed the prepared recipe")
        (run / "preparation.attestation.json").write_bytes(_canonical_json(provenance))
    except BaseException:
        # Only files this function created, in a virgin directory.
        for name in (
            "preparation.attestation.json",
            "fresh_recipe.json",
            "pipeline.stage08.collection.yaml",
        ):
            (run / name).unlink(missing_ok=True)
        root, transient, checkpoints = scratch_paths(run)
        (root / ".progeny-run-scratch.json").unlink(missing_ok=True)
        for directory in (transient, checkpoints, root):
            if directory.is_dir() and not directory.is_symlink():
                directory.rmdir()
        run.rmdir()
        raise
    return {
        "run": str(run),
        "recipe_sha256": _sha256(run / "fresh_recipe.json"),
        "attestation": str(run / "preparation.attestation.json"),
        "source_hashes_complete": hash_biological_inputs,
    }
