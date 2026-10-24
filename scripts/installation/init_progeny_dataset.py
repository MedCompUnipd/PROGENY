#!/usr/bin/env python3
"""Initialize and verify external inputs for a virgin PROGENY run.

This is an input-layout utility, not a scientific producer or a run launcher.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import yaml

ROLES = ("START", "END")
SCHEMA = "progeny-external-input-layout-v1"
RELEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
TAXON_FILES = ("nodes.dmp", "names.dmp", "merged.dmp", "delnodes.dmp")


def _absolute(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be an absolute path without '..'")
    if path != path.resolve(strict=False):
        raise ValueError(f"{label} must use a physical, symlink-free path")
    return path


def _disjoint(a: Path, b: Path, label: str) -> None:
    if a == b or a in b.parents or b in a.parents:
        raise ValueError(f"Overlapping paths are forbidden: {label}")


def _file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or symlinked {label}: {path}")


def _input_map(root: Path, options: dict) -> dict:
    result = {
        "source_fasta": str(root / "input/source/targets.raw.fasta"),
        "targets_fasta": str(root / "input/targets/targets.fasta"),
        "targets_metadata": str(root / "input/targets/targets.metadata.tsv"),
        "targets_manifest": str(root / "input/targets/00_manifest.json"),
        "ontology": str(root / "input/ontology/go.owl"),
        "evidence_registry": str(root / "input/policies/evidence_registry.json"),
        "temporal_policy": str(root / "input/policies/temporal_policy.json"),
    }
    for role in ROLES:
        fmt = options["formats"][role]
        for dataset in ("sprot", "trembl"):
            suffix = ".gz" if fmt[dataset] == "gzip" else ""
            key = f"{role}.uniprot_{dataset}"
            result[key] = str(
                root / "input" / role / "uniprot" / f"uniprot_{dataset}.dat{suffix}"
            )
        goa_suffix = ".gz" if fmt["goa"] == "gzip" else ""
        result[f"{role}.goa_raw"] = str(
            root / "input" / role / "goa" / f"goa.gaf{goa_suffix}"
        )
        result[f"{role}.goa_pipeline"] = str(
            root / "prepared" / role / "goa.gaf"
            if goa_suffix
            else root / "input" / role / "goa" / "goa.gaf"
        )
        for filename in TAXON_FILES:
            result[f"{role}.taxonomy.{filename}"] = str(
                root / "input" / role / "taxonomy" / filename
            )
    return result


def _pipeline(template: Path, options: dict, paths: dict) -> dict:
    _file(template, "pipeline config template")
    data = yaml.safe_load(template.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Pipeline template must be a YAML mapping")
    data["targets"] = {
        "mode": "canonical",
        "fasta": paths["targets_fasta"],
        "metadata": paths["targets_metadata"],
        "adapter": None,
    }
    for role in ROLES:
        role_data = data["releases"][role]
        role_data["release_id"] = options["releases"][role]
        role_data["uniprot_sources"] = [
            paths[f"{role}.uniprot_sprot"],
            paths[f"{role}.uniprot_trembl"],
        ]
        role_data["goa"] = paths[f"{role}.goa_pipeline"]
        tax = role_data["taxonomy"]
        tax["snapshot_id"] = options["taxonomies"][role]
        for name, field in (
            ("nodes", "nodes.dmp"),
            ("names", "names.dmp"),
            ("merged", "merged.dmp"),
            ("deleted", "delnodes.dmp"),
        ):
            tax[name] = paths[f"{role}.taxonomy.{field}"]
    data["ontology"]["path"] = paths["ontology"]
    data["ontology"]["expected_sha256"] = None
    run = Path(options["run_root"])
    data["locations"] = {
        "work": str(run / "work/pipeline-v2"),
        "output": str(run / "results/pipeline-v2"),
        "logs": str(run / "logs/pipeline-v2"),
    }
    return data


def _read_layout(root: Path) -> tuple[dict, dict]:
    path = root / "config/dataset-layout.json"
    _file(path, "dataset layout manifest")
    layout = json.loads(path.read_text(encoding="utf-8"))
    if layout.get("schema") != SCHEMA or layout.get("root") != str(root):
        raise ValueError("Foreign or unsupported layout manifest")
    paths = _input_map(root, layout)
    if paths != layout.get("paths"):
        raise ValueError("Layout path contract differs from the manifest")
    return layout, paths


def initialize(args: argparse.Namespace) -> None:
    repo = _absolute(args.repo, "repo")
    root = _absolute(args.dataset_root, "dataset root")
    run = _absolute(args.run_root, "run root")
    if not (repo / "config/pipeline.yaml").is_file():
        raise ValueError("Repository config/pipeline.yaml is missing")
    if not (repo / ".git").exists():
        raise ValueError("Expected an installed Git repository")
    for label, other in (("repo/dataset", repo), ("run/dataset", run)):
        _disjoint(root, other, label)
    _disjoint(repo, run, "repo/run")
    if root.exists() or root.is_symlink():
        raise FileExistsError(f"Dataset root must not exist: {root}")
    if run.exists() or run.is_symlink():
        raise FileExistsError(f"Virgin run root must not exist: {run}")
    if not root.parent.is_dir() or not run.parent.is_dir():
        raise ValueError("Both dataset and run parent directories must exist")
    if args.start_release == args.end_release:
        raise ValueError("START and END release identifiers must differ")
    for name in (
        args.start_release,
        args.end_release,
        args.start_taxonomy,
        args.end_taxonomy,
    ):
        if RELEASE_ID.fullmatch(name) is None:
            raise ValueError(f"Unsafe release or taxonomy identifier: {name}")
    options = {
        "schema": SCHEMA,
        "root": str(root),
        "repo": str(repo),
        "run_root": str(run),
        "releases": {"START": args.start_release, "END": args.end_release},
        "taxonomies": {
            "START": args.start_taxonomy,
            "END": args.end_taxonomy,
        },
        "formats": {
            "START": {
                "sprot": args.start_sprot or args.start_uniprot,
                "trembl": args.start_trembl or args.start_uniprot,
                "goa": args.start_goa,
            },
            "END": {
                "sprot": args.end_sprot or args.end_uniprot,
                "trembl": args.end_trembl or args.end_uniprot,
                "goa": args.end_goa,
            },
        },
    }
    paths = _input_map(root, options)
    options["paths"] = paths
    pipeline = _pipeline(repo / "config/pipeline.yaml", options, paths)
    with tempfile.TemporaryDirectory(
        prefix=".progeny-layout-", dir=root.parent
    ) as temp_name:
        temporary = Path(temp_name)
        folders = [
            "config",
            "input/source",
            "input/ontology",
            "input/policies",
        ]
        for role in ROLES:
            folders.extend(
                (
                    f"input/{role}/uniprot",
                    f"input/{role}/goa",
                    f"input/{role}/taxonomy",
                    f"prepared/{role}",
                )
            )
        folders.append("input")
        for name in folders:
            (temporary / name).mkdir(parents=True, exist_ok=True)
        # input/targets MUST NOT exist: Stage 00 creates it atomically.
        (temporary / "config/dataset-layout.json").write_text(
            json.dumps(options, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (temporary / "config/pipeline.yaml").write_text(
            yaml.safe_dump(pipeline, sort_keys=False), encoding="utf-8"
        )
        if root.exists() or root.is_symlink():
            raise FileExistsError(f"Dataset root appeared during staging: {root}")
        os.rename(temporary, root)
    print(f"LAYOUT_INIT=PASS ROOT={root}")
    print(f"PIPELINE_CONFIG={root / 'config/pipeline.yaml'}")
    print(f"LAYOUT_MANIFEST={root / 'config/dataset-layout.json'}")
    print(f"STAGE00_OUTPUT_DIRECTORY={root / 'input/targets'}")
    print("VIRGIN_RUN_CREATED=NO")


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _gzip_header(path: Path) -> None:
    with path.open("rb") as handle:
        if handle.read(2) != b"\x1f\x8b":
            raise ValueError(f"Expected gzip header: {path}")


def _goa_header(path: Path) -> None:
    with path.open("rb") as handle:
        for _ in range(20):
            line = handle.readline(512)
            if not line:
                break
            if line.startswith(b"!gaf-version: 2"):
                return
    raise ValueError(f"GAF 2.x version header not found: {path}")


def _inflate_goa(source: Path, destination: Path) -> None:
    if destination.is_symlink():
        raise ValueError(f"Prepared GOA cannot be a symlink: {destination}")
    _gzip_header(source)
    if destination.exists():
        _file(destination, "previously prepared GOA")
        with (
            gzip.open(source, "rb") as input_stream,
            destination.open("rb") as output_stream,
        ):
            while True:
                original = input_stream.read(8 * 1024 * 1024)
                prepared = output_stream.read(8 * 1024 * 1024)
                if original != prepared:
                    raise ValueError("Prepared GOA differs from compressed source")
                if not original:
                    break
        _goa_header(destination)
        return
    descriptor, name = tempfile.mkstemp(
        dir=destination.parent, prefix=".goa-gaf-", suffix=".tmp"
    )
    temp = Path(name)
    try:
        with (
            os.fdopen(descriptor, "wb") as output,
            gzip.open(source, "rb") as input_stream,
        ):
            shutil.copyfileobj(input_stream, output, length=8 * 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        _goa_header(temp)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(destination)
        os.rename(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


def check(args: argparse.Namespace) -> None:
    root = _absolute(args.dataset_root, "dataset root")
    layout, paths = _read_layout(root)
    _file(Path(paths["source_fasta"]), "source FASTA")
    for name in ("targets_fasta", "targets_metadata", "targets_manifest"):
        _file(Path(paths[name]), name)
    _file(Path(paths["ontology"]), "pinned GO ontology")
    for label in ("evidence_registry", "temporal_policy"):
        _file(Path(paths[label]), label)
    _file(root / "config/pipeline.yaml", "generated pipeline config")
    prepared = 0
    for role in ROLES:
        fmt = layout["formats"][role]
        for label in ("sprot", "trembl"):
            file = Path(paths[f"{role}.uniprot_{label}"])
            _file(file, f"{role} UniProt {label}")
            if fmt[label] == "gzip":
                _gzip_header(file)
        for filename in TAXON_FILES:
            _file(
                Path(paths[f"{role}.taxonomy.{filename}"]),
                f"{role} taxonomy {filename}",
            )
        goa = Path(paths[f"{role}.goa_raw"])
        _file(goa, f"{role} GOA")
        if fmt["goa"] == "gzip":
            _gzip_header(goa)
            dest = Path(paths[f"{role}.goa_pipeline"])
            if args.materialize_goa:
                newly_prepared = not dest.exists()
                _inflate_goa(goa, dest)
                prepared += int(newly_prepared)
            else:
                _file(dest, f"{role} prepared uncompressed GOA")
                _inflate_goa(goa, dest)
            _goa_header(dest)
        else:
            _goa_header(goa)
    expected = _pipeline(Path(layout["repo"]) / "config/pipeline.yaml", layout, paths)
    actual = yaml.safe_load((root / "config/pipeline.yaml").read_text(encoding="utf-8"))
    if actual["ontology"]["expected_sha256"] is not None:
        expected["ontology"]["expected_sha256"] = actual["ontology"]["expected_sha256"]
    if expected != actual:
        raise ValueError("Generated pipeline config has been altered")
    if Path(layout["run_root"]).exists():
        raise ValueError("The configured virgin run root already exists")
    if args.seal:
        current = actual["ontology"]["expected_sha256"]
        pinned = _digest(Path(paths["ontology"]))
        if current is not None and current != pinned:
            raise ValueError("Refusing to repin a changed GO ontology")
        actual["ontology"]["expected_sha256"] = pinned
        target = root / "config/pipeline.yaml"
        staged = target.with_name(".pipeline-sealed.yaml.tmp")
        if staged.exists():
            raise FileExistsError(staged)
        try:
            staged.write_text(yaml.safe_dump(actual, sort_keys=False), encoding="utf-8")
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
    elif actual["ontology"]["expected_sha256"] is None:
        raise ValueError("Ontology not pinned: run check with --seal")
    elif actual["ontology"]["expected_sha256"] != _digest(Path(paths["ontology"])):
        raise ValueError("Pinned ontology SHA256 does not match the input")
    print(f"EXTERNAL_INPUTS_PREFLIGHT=PASS GOA_MATERIALIZED={prepared}")
    print(f"PIPELINE_CONFIG={root / 'config/pipeline.yaml'}")


def bind(args: argparse.Namespace) -> None:
    root = _absolute(args.dataset_root, "dataset root")
    layout, paths = _read_layout(root)
    template = _absolute(args.template, "complete fresh spec template")
    _file(template, "fresh spec template")
    spec = json.loads(template.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or set(spec) != {"pipeline", "recipe"}:
        raise ValueError("Expected a complete {pipeline, recipe} JSON template")
    if not isinstance(spec["recipe"], dict):
        raise ValueError("Fresh recipe options must be a mapping")
    config = yaml.safe_load((root / "config/pipeline.yaml").read_text(encoding="utf-8"))
    if config["ontology"]["expected_sha256"] is None:
        raise ValueError("Seal and verify biological inputs before binding")
    spec["pipeline"] = config
    spec["recipe"]["targets_input"] = paths["targets_metadata"]
    spec["recipe"]["evidence_registry"] = paths["evidence_registry"]
    spec["recipe"]["temporal_policy"] = paths["temporal_policy"]
    tools = spec["recipe"].get("tools")
    repo = Path(layout["repo"])
    if not isinstance(tools, dict) or not tools:
        raise ValueError("Complete recipe tools mapping is required")
    for label, value in tools.items():
        tool = _absolute(value, f"tool.{label}")
        _file(tool, f"tool.{label}")
        if not tool.is_relative_to(repo):
            raise ValueError(f"Tool {label} is outside the installed repository")
    dest = root / "config/fresh-spec.json"
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(f"Never overwrite a generated fresh spec: {dest}")
    with dest.open("x", encoding="utf-8") as handle:
        json.dump(spec, handle, sort_keys=True, indent=2)
        handle.write("\n")
    print(f"FRESH_SPEC_WRITTEN={dest}")
    print("FRESH_SPEC_VALIDATED_BY_PREPARER=NO")
    print(f"RUN_ROOT_NOT_CREATED={layout['run_root']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    init = sub.add_parser("init", help="create an empty external dataset layout")
    init.add_argument("--repo", required=True)
    init.add_argument("--dataset-root", required=True)
    init.add_argument("--run-root", required=True)
    init.add_argument("--start-release", required=True)
    init.add_argument("--end-release", required=True)
    init.add_argument("--start-taxonomy", required=True)
    init.add_argument("--end-taxonomy", required=True)
    for role in ("start", "end"):
        init.add_argument(
            f"--{role}-uniprot", choices=("gzip", "plain"), default="gzip"
        )
        for dataset in ("sprot", "trembl"):
            init.add_argument(f"--{role}-{dataset}", choices=("gzip", "plain"))
        init.add_argument(f"--{role}-goa", choices=("gzip", "plain"), default="plain")
    check_parser = sub.add_parser("check", help="fail-closed dataset preflight")
    check_parser.add_argument("--dataset-root", required=True)
    check_parser.add_argument("--materialize-goa", action="store_true")
    check_parser.add_argument("--seal", action="store_true")
    bind_parser = sub.add_parser("bind", help="bind a complete fresh specification")
    bind_parser.add_argument("--dataset-root", required=True)
    bind_parser.add_argument("--template", required=True)
    args = parser.parse_args(argv)
    if args.operation == "init":
        initialize(args)
    elif args.operation == "check":
        check(args)
    else:
        bind(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
