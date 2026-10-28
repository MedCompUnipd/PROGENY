#!/usr/bin/env python3
"""Guided, fail-closed PROGENY study setup: no user-written JSON or YAML.

Run from a Pixi-installed PROGENY checkout:
    pixi run python scripts/installation/progeny_setup.py

Expert automated entry point: --answers /absolute/path/to/answers.json.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import yaml

from progeny.alpha_advanced import validate_advanced
from progeny.alpha_identity import preserve_headers
from progeny.canonical_v2.dag_contract import TOOLS
from progeny.canonical_v2.fresh_preparation import prepare
from progeny.stage08_temporal_v2 import load_classes
from progeny.workflow.config import FROZEN_SCIENTIFIC, PipelineConfig

SCHEMA = "progeny-guided-study-setup-v1"
ROLES = ("START", "END")
NATIVE_DIR = ".pixi/build/progeny-native-release-gcc14.4"
NATIVE_TARGETS = (
    "progeny-release-fasta-v2",
    "progeny-goa-normalize-v1",
    "progeny-go-positive-filter-v1",
    "progeny-raw-ox-extract-v1",
    "progeny-primary-candidate-scan-v1",
    "progeny-primary-candidate-scan-v2",
    "progeny-direct-accession-anchors-v1",
    "progeny-candidate-sequence-extract-v1",
    "progeny-onehop-lineage-scan-v1",
    "progeny-directional-glocal-full-dp-v1",
    "progeny-full-exact-cross-strain-v1",
    "progeny-directional-glocal-bounded-dp-v2",
    "progeny-directional-glocal-linear-dp-v1",
)
DP_NATIVE_VERSIONS = {
    "progeny-directional-glocal-bounded-dp-v2": (
        "progeny_directional_glocal_bounded_dp_v2"
    ),
    "progeny-directional-glocal-linear-dp-v1": (
        "progeny_directional_glocal_linear_dp_v1"
    ),
}

CLI_TOOLS = {
    "stage05c2_cli": "05C2_freeze_taxonomy_audit_channel.py",
    "stage06a_cli": "06A_prepare_alignment_jobs.py",
    "nonexact_script": "NONEXACT_select_alignment_jobs.py",
    "finalize_script": "06C1_finalize_directional_glocal.py",
    "collection_cli": "08_collect_annotations.py",
    "m10c_cli": "08_interpret_compact.py",
    "temporal_cli": "08_build_benchmark_v2.py",
}
RELEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z", re.ASCII)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def _physical_file(raw: str, label: str) -> Path:
    path = Path(raw).expanduser().absolute()
    if ".." in path.parts or path.is_symlink() or not path.is_file():
        raise ValueError(f"{label}: missing, symlinked or unsafe file: {path}")
    if path.resolve(strict=True) != path:
        raise ValueError(f"{label}: use a physical path without symlinks: {path}")
    return path


def _physical_new(raw: str, label: str) -> Path:
    path = Path(raw).expanduser().absolute()
    if path == Path("/") or ".." in path.parts:
        raise ValueError(f"{label}: unsafe directory")
    if path.exists() or path.is_symlink():
        raise ValueError(f"{label}: choose a NEW directory (already exists): {path}")
    if not path.parent.is_dir() or path.parent.resolve() != path.parent:
        raise ValueError(f"{label}: create its parent directory first: {path.parent}")
    return path


def _disjoint(a: Path, b: Path, label: str) -> None:
    if a == b or a in b.parents or b in a.parents:
        raise ValueError(f"Overlapping directories forbidden: {label}")


def _name(value: str, label: str) -> str:
    if not isinstance(value, str) or not RELEASE_ID.fullmatch(value):
        raise ValueError(f"{label}: use letters, numbers, '_', '.' or '-'")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label}: must be a positive integer")
    return value


def _choice(value: object, label: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ValueError(f"{label}: choose one of {', '.join(allowed)}")
    return str(value)


def _head(path: Path, gzip_ok: bool = False) -> bytes:
    if path.suffix == ".gz" and gzip_ok:
        with gzip.open(path, "rb") as stream:
            return stream.read(512)
    with path.open("rb") as stream:
        return stream.read(512)


def _launch_settings(options: dict) -> dict:
    """Validate scheduler settings separately from scientific identity."""
    execution = options.get("execution", {})
    if not isinstance(execution, dict) or set(execution) - {"slurm"}:
        raise ValueError("Execution settings may contain only 'slurm'")
    slurm = execution.get("slurm")
    if slurm is None:
        return {}
    required = {"memory_gb", "time", "partition", "account"}
    if not isinstance(slurm, dict) or set(slurm) != required:
        raise ValueError("SLURM needs memory_gb, time, partition and account")
    _integer(slurm["memory_gb"], "SLURM memory in GiB")
    duration = slurm["time"]
    if not isinstance(duration, str) or not re.fullmatch(
        r"(?:[0-9]{1,3}-)?[0-9]{1,2}:[0-5][0-9]:[0-5][0-9]",
        duration,
        re.ASCII,
    ):
        raise ValueError("SLURM time must be HH:MM:SS or D-HH:MM:SS")
    hours, minutes, seconds = map(int, duration.split("-")[-1].split(":"))
    days = int(duration.split("-")[0]) if "-" in duration else 0
    if hours > 23 and "-" in duration:
        raise ValueError("SLURM time hours must be 0-23 with D-HH:MM:SS")
    if days == hours == minutes == seconds == 0:
        raise ValueError("SLURM time must be greater than zero")
    for field in ("partition", "account"):
        value = slurm[field]
        if not isinstance(value, str) or (
            value
            and not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}",
                value,
                re.ASCII,
            )
        ):
            raise ValueError(f"SLURM {field}: invalid name")
    return dict(slurm)


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o700)


def _create_launch_options(
    *,
    dataset: Path,
    launcher: Path,
    options: dict,
    identity: str,
) -> dict:
    """Generate launch-only scripts. Never submit a scientific computation."""
    logs = dataset / "logs"
    logs.mkdir(mode=0o700)
    session = f"progeny_{identity[:12]}"
    quoted_launcher = shlex.quote(str(launcher))
    tmux_log = logs / "progeny-tmux.log"
    nohup_log = logs / "progeny-nohup.log"
    pidfile = logs / "progeny-nohup.pid"
    tmux_path = dataset / "RUN_PROGENY_TMUX.sh"
    nohup_path = dataset / "RUN_PROGENY_NOHUP.sh"
    inner = f"bash {quoted_launcher} 2>&1 | tee -a {shlex.quote(str(tmux_log))}"
    shell_command = f"bash -o pipefail -c {shlex.quote(inner)}"
    _write_executable(
        tmux_path,
        "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
        "command -v tmux >/dev/null || { echo 'tmux is not installed' >&2; exit 1; }\n"
        f"if tmux has-session -t {shlex.quote(session)} 2>/dev/null; then\n"
        "  echo 'This PROGENY study already has an active tmux session' >&2\n"
        "  exit 2\nfi\n"
        f"tmux new-session -d -s {shlex.quote(session)} "
        f"{shlex.quote(shell_command)}\n"
        f"echo 'TMUX_SUBMITTED={session}'\n"
        f"echo 'RECONNECT=tmux attach -t {session}'\n"
        f"echo {shlex.quote(f'LOG={tmux_log}')}\n",
    )
    _write_executable(
        nohup_path,
        "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
        f"pidfile={shlex.quote(str(pidfile))}\n"
        'if [[ -s "$pidfile" ]]; then\n'
        '  old_pid=$(cat "$pidfile")\n'
        '  if [[ "$old_pid" =~ ^[0-9]+$ ]] && '
        'kill -0 "$old_pid" 2>/dev/null; then\n'
        "    echo 'A previous PROGENY nohup process still exists' >&2\n"
        "    exit 2\n  fi\nfi\n"
        f"nohup bash {quoted_launcher} >> {shlex.quote(str(nohup_log))} "
        "2>&1 < /dev/null &\n"
        "child=$!\n"
        'printf \'%s\\n\' "$child" > "$pidfile"\n'
        'echo "NOHUP_SUBMITTED_PID=$child"\n'
        f"echo {shlex.quote(f'LOG={nohup_log}')}\n",
    )
    commands = {
        "direct": f"bash {quoted_launcher}",
        "tmux": f"bash {shlex.quote(str(tmux_path))}",
        "nohup": f"bash {shlex.quote(str(nohup_path))}",
    }
    slurm = _launch_settings(options)
    if slurm:
        sbatch = dataset / "SUBMIT_PROGENY.sbatch"
        directives = [
            "#SBATCH --nodes=1",
            "#SBATCH --ntasks=1",
            f"#SBATCH --cpus-per-task={options['threads']}",
            f"#SBATCH --mem={slurm['memory_gb']}G",
            f"#SBATCH --time={slurm['time']}",
            f"#SBATCH --job-name={session}",
        ]
        for field in ("partition", "account"):
            if slurm[field]:
                directives.append(f"#SBATCH --{field}={slurm[field]}")
        sbatch.write_text(
            "#!/usr/bin/env bash\n"
            + "\n".join(directives)
            + "\nset -Eeuo pipefail\n"
            + f"bash {quoted_launcher}\n",
            encoding="utf-8",
        )
        sbatch.chmod(0o700)
        slurm_log = logs / "progeny-slurm-%j.log"
        commands["slurm"] = (
            f"sbatch --output={shlex.quote(str(slurm_log))} "
            f"--error={shlex.quote(str(slurm_log))} "
            f"{shlex.quote(str(sbatch))}"
        )
    option_file = dataset / "HOW_TO_RUN_PROGENY.txt"
    lines = [
        "PROGENY - HOW TO RUN THIS PREPARED STUDY",
        "No computation has been started by the setup wizard.",
        "Choose ONE of the following launch methods, not multiple.",
        "",
        "DIRECT (foreground, not recommended for multi-day SSH sessions):",
        commands["direct"],
        "",
        "TMUX (recommended for persistent SSH sessions):",
        commands["tmux"],
        f"Reconnect while running: tmux attach -t {session}",
        f"Live log: tail -f {shlex.quote(str(tmux_log))}",
        "",
        "NOHUP (background, persists after SSH disconnect):",
        commands["nohup"],
        f"Live log: tail -f {shlex.quote(str(nohup_log))}",
        f"PID file: {pidfile}",
        "",
    ]
    if "slurm" in commands:
        lines.extend(
            [
                "SLURM (single allocation on ONE compute node):",
                commands["slurm"],
                'Inspect jobs: squeue -u "$USER"',
                "SLURM allocates the selected cores and memory to one Snakemake",
                "controller and its local jobs; stages are NOT spread across nodes.",
                "The cluster must expose PROGENY, Pixi and all input paths to",
                "the allocated compute node. Consult your cluster resource limits.",
            ]
        )
    else:
        lines.extend(
            [
                "SLURM not configured. Re-run the wizard for a new study and",
                "select SLURM to provide memory, walltime and optional account.",
            ]
        )
    lines.extend(
        [
            "",
            "Do not start two methods simultaneously for the same study.",
            "If a job fails, inspect its log before deciding how to resume.",
            "After success, open RUN_ROOT/results/benchmark/report.html.",
            "The benchmark FASTA and GO TSV files use original user FASTA IDs.",
            "Internal T000... IDs are retained in target_identity_map.tsv.",
            "Do not modify fresh_recipe.json or the scientific identity.",
        ]
    )
    option_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"commands": commands, "instructions": str(option_file)}


def _inspect_inputs(options: dict, repo: Path, dataset: Path, run: Path) -> dict:
    if not isinstance(options, dict):
        raise ValueError("Setup answers must be a mapping")
    required = {
        "dataset_dir",
        "run_dir",
        "targets_fasta",
        "ontology",
        "releases",
        "policy_profile",
        "exact_policy",
        "partial_sequence",
        "documentary_fragment",
        "threads",
        "max_pair_cells",
        "max_total_cells",
        "max_chunk_cells",
    }
    supported = required | {
        "targets_mode",
        "targets_taxid",
        "targets_taxid_table",
        "header_ids_are_uniprot_accessions",
        "execution",
        "advanced_config",
    }
    if not required <= set(options) or set(options) - supported:
        raise ValueError(f"Setup needs fields: {sorted(required)}")
    mode = _choice(
        options.get("targets_mode", "already_tagged"),
        "Target identifiers",
        ("already_tagged", "single_species", "taxid_table"),
    )
    accession_ids = options.get("header_ids_are_uniprot_accessions", False)
    if type(accession_ids) is not bool:
        raise ValueError("UniProt accession declaration must be a boolean")
    if mode == "single_species":
        taxid = options.get("targets_taxid")
        if not isinstance(taxid, str) or not re.fullmatch(r"[1-9][0-9]*", taxid):
            raise ValueError("A single positive NCBI TaxID must be supplied")
    if mode == "taxid_table" and not options.get("targets_taxid_table"):
        raise ValueError("Choose a TaxID mapping TSV for multi-species targets")
    _launch_settings(options)
    _disjoint(dataset, run, "dataset/run")
    for path in (dataset, run):
        _disjoint(path, repo, "generated files/source checkout")
    _choice(options["exact_policy"], "EXACT policy", ("strict", "same_species_exact"))
    for key in ("partial_sequence", "documentary_fragment"):
        _choice(options[key], key, ("allow", "report_only"))
    _choice(options["policy_profile"], "evidence policy", ("reference",))
    for field in ("threads", "max_pair_cells", "max_total_cells", "max_chunk_cells"):
        _integer(options[field], field)
    if options["max_chunk_cells"] > options["max_total_cells"]:
        raise ValueError("Chunk budget cannot exceed total DP cell budget")
    if not isinstance(options["releases"], dict) or set(options["releases"]) != set(
        ROLES
    ):
        raise ValueError("Supply START and END release sources")

    files = {
        "targets_raw": _physical_file(options["targets_fasta"], "Target FASTA"),
        "ontology": _physical_file(options["ontology"], "GO ontology"),
    }
    if options.get("advanced_config"):
        files["advanced_config"] = _physical_file(
            options["advanced_config"], "Advanced configuration"
        )
    if mode == "taxid_table":
        files["targets_taxid_table"] = _physical_file(
            options["targets_taxid_table"], "TaxID mapping TSV"
        )
    if files["targets_raw"].suffix == ".gz":
        raise ValueError(
            "Target FASTA must be uncompressed; "
            "use an ID and NCBI TaxID for each sequence"
        )
    if _head(files["targets_raw"]).lstrip()[:1] != b">":
        raise ValueError("Target FASTA is not in FASTA format")
    if files["ontology"].suffix == ".gz":
        raise ValueError("GO ontology must be uncompressed .owl")
    if not (files["ontology"].suffix.lower() == ".owl"):
        raise ValueError("Use a GO OWL ontology file (.owl)")
    release_ids = []
    for role in ROLES:
        record = options["releases"][role]
        fields = {"release_id", "taxonomy_id", "sprot", "trembl", "goa", "taxonomy_dir"}
        if not isinstance(record, dict) or set(record) != fields:
            raise ValueError(
                f"{role} needs release ID, taxonomy ID, Swiss-Prot, "
                "TrEMBL, GOA and taxonomy folder"
            )
        release_ids.append(_name(record["release_id"], f"{role} release ID"))
        _name(record["taxonomy_id"], f"{role} taxonomy ID")
        for label in ("sprot", "trembl", "goa"):
            file = _physical_file(record[label], f"{role} {label}")
            files[f"{role}.{label}"] = file
            suffixes = file.suffixes
            if label in ("sprot", "trembl") and (
                not suffixes or suffixes[-1] not in (".gz", ".dat")
            ):
                raise ValueError(f"{role} {label} must be .dat or .dat.gz")
            if label == "goa":
                numbered_gaf = re.search(r"\.gaf\.[1-9][0-9]*\Z", file.name) is not None
                if not numbered_gaf and (
                    not suffixes or suffixes[-1] not in (".gz", ".gaf")
                ):
                    raise ValueError(f"{role} GOA must be .gaf, .gaf.gz or .gaf.N")
            if file.suffix == ".gz" and _head(file)[:2] != b"\x1f\x8b":
                raise ValueError(f"Invalid gzip header: {file}")
            if label == "goa" and not _head(file, gzip_ok=True).startswith(
                b"!gaf-version: 2"
            ):
                raise ValueError(f"{role}: expected GAF 2.x header: {file}")
        tax = Path(record["taxonomy_dir"]).expanduser().absolute()
        if not tax.is_dir() or tax.is_symlink() or tax.resolve(strict=True) != tax:
            raise ValueError(f"{role}: taxonomy folder must exist without symlinks")
        for filename in ("nodes.dmp", "names.dmp", "merged.dmp", "delnodes.dmp"):
            files[f"{role}.taxonomy.{filename}"] = _physical_file(
                str(tax / filename), f"{role} taxonomy {filename}"
            )
    if release_ids[0] == release_ids[1]:
        raise ValueError("START and END must have different release IDs")
    for label, path in files.items():
        if path == repo or repo in path.parents:
            raise ValueError(f"Biological input cannot be inside checkout: {label}")
        if path == run or run in path.parents:
            raise ValueError(f"Biological input cannot be inside future run: {label}")
        if path == dataset or dataset in path.parents:
            raise ValueError(
                f"Choose a NEW dataset folder, not one holding inputs: {label}"
            )
    return files


def _targets_with_taxids(options: dict, files: dict, dataset: Path) -> Path:
    """Prepare taxon-qualified FASTA from standard FASTA with explicit taxonomy."""
    mode = options.get("targets_mode", "already_tagged")
    if mode == "already_tagged":
        return files["targets_raw"]
    taxids = {}
    if mode == "taxid_table":
        with files["targets_taxid_table"].open(encoding="utf-8", newline="") as stream:
            rows = csv.reader(stream, delimiter="\t")
            if next(rows, None) != ["target_id", "ncbi_taxid"]:
                raise ValueError("TaxID table needs target_id<TAB>ncbi_taxid header")
            for row in rows:
                if len(row) != 2 or not re.fullmatch(r"[1-9][0-9]*", row[1]):
                    raise ValueError("TaxID mapping contains an invalid row")
                if row[0] in taxids:
                    raise ValueError(f"Duplicate target ID in TaxID table: {row[0]}")
                taxids[row[0]] = row[1]
            if not taxids:
                raise ValueError("TaxID table is empty")
    output = dataset / "prepared/targets.with_taxid.fasta"
    output.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    count = 0
    # Source sequence bytes are not altered; only FASTA headers are qualified.
    with (
        files["targets_raw"].open(encoding="ascii") as source,
        output.open("x", encoding="ascii") as target,
    ):
        for line in source:
            if line.startswith(">"):
                label = line[1:].strip().split()
                if not label:
                    raise ValueError("FASTA contains an empty header")
                protein = label[0]
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", protein):
                    raise ValueError(f"Invalid protein ID: {protein}")
                if protein in seen:
                    raise ValueError(f"Duplicate protein ID: {protein}")
                seen.add(protein)
                if mode == "taxid_table":
                    if protein not in taxids:
                        raise ValueError(f"No NCBI TaxID for FASTA ID: {protein}")
                    taxid = taxids[protein]
                else:
                    taxid = options["targets_taxid"]
                target.write(f">{protein}\t{taxid}\n")
                count += 1
            else:
                target.write(line)
    if count == 0 or (mode == "taxid_table" and set(taxids) != seen):
        raise ValueError("FASTA empty or TaxID mapping contains unmatched target IDs")
    return output


def _verify_dp_protocol(binary: Path, expected_version: str) -> None:
    """Reject an incompatible DP executable before preparing a study."""
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError(
            f"Incompatible PROGENY DP executable ({binary.name}): "
            "--version protocol failed"
        ) from exc
    version = result.stdout.strip()
    if version != expected_version:
        raise ValueError(
            f"Incompatible PROGENY DP executable ({binary.name}): "
            f"expected version {expected_version!r}, got {version!r}"
        )


def _verify_native(repo: Path, *, build_missing: bool) -> dict[str, Path]:
    root = repo / NATIVE_DIR
    for name in NATIVE_TARGETS:
        binary = root / name
        if binary.is_file() and os.access(binary, os.X_OK) and not binary.is_symlink():
            continue
        if not build_missing:
            raise FileNotFoundError(
                f"Native executable {name} missing; run setup to build it"
            )
        print(f"  Compiling required PROGENY program: {name}", flush=True)
        subprocess.run(
            [
                "bash",
                str(repo / "scripts/installation/ensure_progeny_native_release.sh"),
                name,
            ],
            cwd=repo,
            check=True,
        )
        if (
            not binary.is_file()
            or not os.access(binary, os.X_OK)
            or binary.is_symlink()
        ):
            raise ValueError(f"Native build did not create a valid executable: {name}")
    tools = {key: repo / "scripts/pipeline" / name for key, name in CLI_TOOLS.items()}
    tools["full_dp_binary"] = root / "progeny-directional-glocal-bounded-dp-v2"
    if set(tools) != TOOLS:
        raise RuntimeError("PROGENY tool contract changed: review the wizard mapping")
    for name, path in tools.items():
        _physical_file(str(path), f"PROGENY tool {name}")
    for native_name, version in DP_NATIVE_VERSIONS.items():
        _verify_dp_protocol(root / native_name, version)
    return tools


def _materialize_gaf(source: Path, destination: Path) -> Path:
    if source.suffix != ".gz":
        return source
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Refusing to overwrite GOA: {destination}")
    try:
        with gzip.open(source, "rb") as reader, destination.open("xb") as writer:
            for block in iter(lambda: reader.read(8 * 1024 * 1024), b""):
                writer.write(block)
        if not _head(destination).startswith(b"!gaf-version: 2"):
            raise ValueError(f"Materialized GOA header invalid: {destination}")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def _copy_policies(
    repo: Path, dataset: Path, custom_policy: Path | None = None
) -> tuple[Path, Path]:
    target = dataset / "policies"
    target.mkdir(parents=True)
    pairs = (
        ("stage08_evidence_registry.example.json", "evidence_registry.json"),
        ("stage08_evidence_classes_v2.example.json", "temporal_policy.json"),
    )
    paths = []
    for source, name in pairs:
        origin = _physical_file(
            str(repo / "config" / source), "PROGENY reference policy"
        )
        destination = target / name
        if name == "temporal_policy.json" and custom_policy is not None:
            destination.write_bytes(custom_policy.read_bytes())
        else:
            destination.write_bytes(origin.read_bytes())
        paths.append(destination)
    # Actual M12 V2 policy validator, not merely a JSON parsing check.
    load_classes(*paths)
    return paths[0], paths[1]


def _identity_inventory(
    repo: Path,
    files: dict,
    policies: tuple[Path, Path],
    options: dict,
    tools: dict,
    pipeline: dict,
) -> dict:
    print(
        "  Computing SHA-256 of biological source files (may take time)...",
        flush=True,
    )
    biological = {}
    for label, file in sorted(files.items()):
        print(f"    Hashing {label}: {file}", flush=True)
        biological[label] = _hash(file)
    source_code = {}
    for folder in (
        "src/progeny",
        "workflow",
        "cpp/src",
        "cmake",
        "scripts/pipeline",
        "scripts/installation",
    ):
        for file in sorted((repo / folder).rglob("*")):
            if (
                file.is_file()
                and not file.is_symlink()
                and file.suffix
                in (".py", ".cpp", ".hpp", ".h", ".smk", ".txt", ".cmake", ".sh")
            ):
                source_code[str(file.relative_to(repo))] = _hash(file)
    for item in ("config/pipeline.yaml", "pixi.toml", "pixi.lock", "pyproject.toml"):
        source_code[item] = _hash(repo / item)
    tool_hashes = {name: _hash(path) for name, path in sorted(tools.items())}
    return {
        "schema": "progeny-guided-content-identity-inventory-v1",
        "input_sha256": biological,
        "policy_sha256": {
            "evidence_registry": _hash(policies[0]),
            "temporal_policy": _hash(policies[1]),
        },
        "tool_sha256": tool_hashes,
        "scientific_source_sha256": source_code,
        "release_identity": {
            role: {
                "release_id": options["releases"][role]["release_id"],
                "taxonomy_id": options["releases"][role]["taxonomy_id"],
            }
            for role in ROLES
        },
        "choices": {
            field: options[field]
            for field in (
                "policy_profile",
                "exact_policy",
                "partial_sequence",
                "documentary_fragment",
                "threads",
                "max_pair_cells",
                "max_total_cells",
                "max_chunk_cells",
            )
        }
        | {
            "targets_mode": options.get("targets_mode", "already_tagged"),
            "targets_taxid": options.get("targets_taxid"),
            "header_ids_are_uniprot_accessions": options.get(
                "header_ids_are_uniprot_accessions", False
            ),
        },
        "pipeline_science": {
            key: pipeline[key]
            for key in (
                "scientific",
                "resolver",
                "annotation_donor",
                "stage08_collection",
            )
        },
    }


def _make_pipeline(
    repo: Path,
    dataset: Path,
    run: Path,
    files: dict,
    options: dict,
    prepared_goa: dict,
) -> dict:
    raw = yaml.safe_load((repo / "config/pipeline.yaml").read_text(encoding="utf-8"))
    raw["targets"] = {
        "mode": "canonical",
        "fasta": str(dataset / "targets/targets.fasta"),
        "metadata": str(dataset / "targets/targets.metadata.tsv"),
        "adapter": None,
    }
    for role in ROLES:
        record = options["releases"][role]
        raw["releases"][role] = {
            "release_id": record["release_id"],
            "uniprot_sources": [
                str(files[f"{role}.sprot"]),
                str(files[f"{role}.trembl"]),
            ],
            "goa": str(prepared_goa[role]),
            "taxonomy": {
                "snapshot_id": record["taxonomy_id"],
                "nodes": str(files[f"{role}.taxonomy.nodes.dmp"]),
                "names": str(files[f"{role}.taxonomy.names.dmp"]),
                "merged": str(files[f"{role}.taxonomy.merged.dmp"]),
                "deleted": str(files[f"{role}.taxonomy.delnodes.dmp"]),
            },
        }
    raw["ontology"] = {
        "path": str(files["ontology"]),
        "expected_sha256": _hash(files["ontology"]),
        "canonical_url": None,
        "original_url": None,
        "retrieval_date": None,
        "version_iri": None,
    }
    raw["locations"] = {
        "work": str(run / "work/pipeline-v2"),
        "output": str(run / "results/pipeline-v2"),
        "logs": str(run / "logs/pipeline-v2"),
    }
    raw["resolver"] = {
        "subtaxon_policy": (
            "strict"
            if options["exact_policy"] == "strict"
            else "include_audited_same_species"
        )
    }
    raw["annotation_donor"] = {
        "partial_sequence": options["partial_sequence"],
        "documentary_fragment": options["documentary_fragment"],
    }
    raw["stage08_collection"] = {"execute_full_scan": True}
    raw["scientific"] = deepcopy(FROZEN_SCIENTIFIC)
    # Preserve the reviewed per-stage requirements, especially Stage 06C0.
    resources = raw["resources"]
    resources["default"]["threads"] = options["threads"]
    for profile in resources["stages"].values():
        profile["threads"] = min(profile["threads"], options["threads"])
    raw["resources"] = resources
    raw["validation"] = {"deep_checksums": True}
    return PipelineConfig.from_mapping(raw).data


def create_project(options: dict, *, repo: Path, build_missing: bool = True) -> dict:
    options = deepcopy(options)
    repo = repo.resolve(strict=True)
    advanced = {}
    policy_override = None
    performance_override = None
    if options.get("advanced_config"):
        advanced, policy_override, performance_override = validate_advanced(
            _physical_file(options["advanced_config"], "Advanced configuration"),
            registry=repo / "config/stage08_evidence_registry.example.json",
            base_cores=options["threads"],
        )
        for key in ("threads", "max_pair_cells", "max_total_cells", "max_chunk_cells"):
            if key in advanced:
                options[key] = advanced[key]

    if not (repo / "src/progeny/canonical_v2/fresh_preparation.py").is_file():
        raise ValueError("This is not a PROGENY checkout")
    dataset = _physical_new(options["dataset_dir"], "Dataset folder")
    run = _physical_new(options["run_dir"], "Run folder")
    inputs = _inspect_inputs(options, repo, dataset, run)
    shared_root = dataset.parent / "PROGENY_SHARED"
    if shared_root.is_symlink() or (shared_root.exists() and not shared_root.is_dir()):
        raise ValueError("PROGENY_SHARED must be a real directory or not exist")
    if shared_root.absolute() != shared_root.resolve(strict=False):
        raise ValueError("PROGENY_SHARED path must not contain symlinks")
    for generated in (dataset, run):
        _disjoint(shared_root, generated, "shared artifacts/generated roots")
    _disjoint(shared_root, repo, "shared artifacts/source checkout")
    for source in inputs.values():
        source_parent = source.parent.resolve(strict=True)
        if shared_root.is_relative_to(source_parent) or source_parent.is_relative_to(
            shared_root
        ):
            raise ValueError(
                "Choose a study base whose PROGENY_SHARED directory is separate "
                f"from biological input directories: {source_parent}"
            )
    print("Input files and scientific choices: initial validation PASS", flush=True)
    tools = _verify_native(repo, build_missing=build_missing)
    dataset.mkdir(mode=0o700)
    try:
        policies = _copy_policies(repo, dataset, policy_override)
        prepared_goa = {
            role: _materialize_gaf(
                inputs[f"{role}.goa"], dataset / "prepared" / role / "goa.gaf"
            )
            for role in ROLES
        }
        # Stage 00 performs literal ID/TaxID validation and emits exact manifests.
        tagged_fasta = _targets_with_taxids(options, inputs, dataset)
        stage00_args = [
            sys.executable,
            str(repo / "scripts/pipeline/00_import_targets.py"),
            "--input",
            str(tagged_fasta),
            "--output-directory",
            str(dataset / "targets"),
            "--taxonomy-nodes",
            str(inputs["START.taxonomy.nodes.dmp"]),
            "--taxonomy-merged",
            str(inputs["START.taxonomy.merged.dmp"]),
            "--minlen",
            "10",
        ]
        if options.get("header_ids_are_uniprot_accessions", False):
            stage00_args.append("--header-ids-are-uniprot-accessions")
        subprocess.run(stage00_args, cwd=repo, check=True)
        stage00 = json.loads(
            (dataset / "targets/00_summary.json").read_text(encoding="utf-8")
        )
        if stage00["rejected_unknown_taxid"]:
            raise ValueError(
                "Unknown TaxID targets cannot be silently excluded. Open "
                f"{dataset / 'targets/targets.rejected.tsv'} to resolve them."
            )
        print(
            "STAGE00_ACCEPTED="
            + str(stage00["accepted_targets"])
            + " BELOW_MINLEN="
            + str(stage00["rejected_below_minlen"])
            + " IDENTICAL_DUPLICATES="
            + str(stage00["deduplicated_identical_records"]),
            flush=True,
        )
        preserve_headers(
            inputs["targets_raw"], dataset / "targets", dataset / "identity"
        )
        pipeline = _make_pipeline(repo, dataset, run, inputs, options, prepared_goa)
        identity_details = _identity_inventory(
            repo, inputs, policies, options, tools, pipeline
        )
        identity = hashlib.sha256(_json_bytes(identity_details)).hexdigest()
        start_gaf_sha = identity_details["input_sha256"]["START.goa"]
        if prepared_goa["START"] != inputs["START.goa"]:
            start_gaf_sha = _hash(prepared_goa["START"])
        shared_root.mkdir(mode=0o700, exist_ok=True)
        start_ia_root = (
            shared_root
            / "START"
            / options["releases"]["START"]["release_id"]
            / "information_accretion"
        )
        start_ia_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        (shared_root / "RUNS").mkdir(mode=0o700, exist_ok=True)
        (shared_root / "native" / "ia-roaring").mkdir(
            mode=0o700, parents=True, exist_ok=True
        )
        (shared_root / "scratch" / "ia-roaring").mkdir(
            mode=0o700, parents=True, exist_ok=True
        )
        limits = {
            field: options[field]
            for field in (
                "threads",
                "max_pair_cells",
                "max_total_cells",
                "max_chunk_cells",
                "partial_sequence",
                "documentary_fragment",
            )
        }
        spec = {
            "pipeline": pipeline,
            "recipe": {
                "identity_sha256": identity,
                "policy": options["exact_policy"],
                "limits": limits,
                "tools": {name: str(path) for name, path in tools.items()},
                "targets_input": pipeline["targets"]["metadata"],
                "evidence_registry": str(policies[0]),
                "temporal_policy": str(policies[1]),
                "large_dp": {
                    "binary": str(
                        repo / NATIVE_DIR / "progeny-directional-glocal-linear-dp-v1"
                    ),
                    "max_dp_memory_bytes": advanced.get(
                        "max_dp_memory_bytes", 2 * 1024 * 1024 * 1024
                    ),
                    "checkpoint_rows": advanced.get("checkpoint_rows", 256),
                    "scratch_root": str(run / "tmp"),
                },
            },
        }
        config = dataset / "config"
        config.mkdir()
        performance_target = None
        if performance_override is not None:
            performance_target = config / "performance.json"
            performance_target.write_bytes(performance_override.read_bytes())
        (config / "scientific-identity-inventory.json").write_bytes(
            _json_bytes(identity_details)
        )
        (config / "pipeline.yaml").write_text(
            yaml.safe_dump(pipeline, sort_keys=False), encoding="utf-8"
        )
        spec_path = config / "fresh-spec.json"
        spec_path.write_bytes(_json_bytes(spec))
        # Genuine existing producer-independent preparator: no workaround.
        result = prepare(
            repo=repo,
            run=run,
            spec_path=spec_path,
            hash_biological_inputs=False,
        )
        launcher_args = [
            "pixi",
            "run",
            "snakemake",
            "all",
            "--snakefile",
            str(repo / "workflow/canonical_v2_fresh.smk"),
            "--directory",
            str(run),
            "--cores",
            str(options["threads"]),
            "--resources",
            "dataset_io=1",
            "--rerun-incomplete",
            "--config",
            f"fresh_recipe={run / 'fresh_recipe.json'}",
        ]
        if performance_target is not None:
            launcher_args.append(f"performance_profile={performance_target}")
        command = " ".join(shlex.quote(arg) for arg in launcher_args)
        export_command = " ".join(
            shlex.quote(arg)
            for arg in (
                "pixi",
                "run",
                "python",
                str(
                    repo / "scripts/installation/publish_progeny_scientific_results.py"
                ),
                "--dataset",
                str(dataset),
                "--run",
                str(run),
            )
        )
        # The validated benchmark adapter executes only after Snakemake success.
        # No canonical scientific publication or Stage 00 mapping is rewritten.
        launcher = dataset / "START_PROGENY.sh"
        launcher.write_text(
            "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
            f"cd {shlex.quote(str(repo))}\n{command}\n{export_command}\n",
            encoding="utf-8",
        )
        launcher.chmod(0o700)
        launch = _create_launch_options(
            dataset=dataset,
            launcher=launcher,
            options=options,
            identity=identity,
        )
        summary = {
            "schema": SCHEMA,
            "status": "READY",
            "dataset": str(dataset),
            "run": str(run),
            "identity_sha256": identity,
            "shared_artifacts_root": str(shared_root),
            "start_ia_root": str(start_ia_root),
            "start_release_id": options["releases"]["START"]["release_id"],
            "start_gaf_sha256": start_gaf_sha,
            "ontology_sha256": pipeline["ontology"]["expected_sha256"],
            "launch_script": str(launcher),
            "launch_options": launch,
            "preparer": result,
            "scientific_choices": identity_details["choices"],
            "user_benchmark_output": str(run / "results/benchmark"),
            "note": (
                "User-provided files and labels are not certified release provenance"
            ),
        }
        (config / "setup-summary.json").write_bytes(_json_bytes(summary))
    except BaseException:
        # Fail closed; preserve the generated directory for diagnosis. Never
        # remove input files or a run created by the canonical preparator.
        print(
            f"SETUP_INCOMPLETE: generated files retained in {dataset}",
            file=sys.stderr,
        )
        raise
    print(f"\nPROGENY_SETUP=READY\nDATASET={dataset}\nRUN={run}")
    print(f"CONTENT_IDENTITY={identity}")
    print(f"SHARED_ARTIFACTS={shared_root}")
    print("NO_JOB_STARTED=YES")
    print(f"LAUNCH_INSTRUCTIONS={launch['instructions']}")
    for mode, command in launch["commands"].items():
        print(f"LAUNCH_{mode.upper()}={command}")
    return summary


def _ask(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if value or default is not None:
            return value or default or ""
        print("  Please provide a value.")


def _menu(title: str, choices: tuple[tuple[str, str], ...]) -> str:
    print("\n" + title)
    for index, (_, description) in enumerate(choices, 1):
        print(f"  {index}. {description}")
    while True:
        selected = input("Enter choice number: ").strip()
        if selected.isdigit() and 1 <= int(selected) <= len(choices):
            return choices[int(selected) - 1][0]
        print("  Enter one of the displayed numbers.")


def interactive_answers() -> dict:
    print("\nPROGENY - New study assistant\n")
    print("You will select existing files. PROGENY never copies the large UniProt")
    print("sources into its code folder or guesses organism identities.\n")
    print("PROGENY can associate each FASTA sequence with its NCBI TaxID.\n")
    base = (
        Path(_ask("Parent folder for study data and results")).expanduser().absolute()
    )
    if not base.is_dir():
        raise ValueError("Parent folder does not exist; create it first")
    study = _name(_ask("Short study name (e.g. my_go_study)"), "study")
    dataset = base / (study + "-dataset")
    run = base / (study + "-run")
    answers = {
        "dataset_dir": str(dataset),
        "run_dir": str(run),
        "targets_fasta": _ask("Existing protein FASTA file (.fasta)"),
        "ontology": _ask("GO OWL ontology (.owl) path"),
        "releases": {},
    }
    answers["targets_mode"] = _menu(
        "How are species assigned to your proteins?",
        (
            ("already_tagged", "Already in FASTA as >protein_ID<TAB>NCBI_TaxID"),
            ("single_species", "All sequences belong to ONE species"),
            ("taxid_table", "I have a two-column TSV of protein IDs and NCBI TaxIDs"),
        ),
    )
    if answers["targets_mode"] == "single_species":
        answers["targets_taxid"] = _ask(
            "NCBI TaxID shared by all sequences (e.g. 9606)"
        )
    elif answers["targets_mode"] == "taxid_table":
        print("  TSV header: target_id<TAB>ncbi_taxid; IDs match the first FASTA word.")
        answers["targets_taxid_table"] = _ask("Path to protein-to-TaxID TSV")
    answers["header_ids_are_uniprot_accessions"] = (
        _menu(
            "Are all original protein IDs actual UniProt accession IDs?",
            (
                ("no", "No / not certain (keep accession field blank)"),
                ("yes", "Yes (validate every ID and preserve as accession)"),
            ),
        )
        == "yes"
    )
    for role in ROLES:
        label = "earlier" if role == "START" else "later"
        print(f"\n{role}: data from the {label} release")
        release = _ask(f"{role} release label (e.g. 2023_01)")
        answers["releases"][role] = {
            "release_id": release,
            "taxonomy_id": _ask(f"{role} taxonomy snapshot label", release),
            "sprot": _ask(f"{role} UniProt Swiss-Prot .dat or .dat.gz"),
            "trembl": _ask(f"{role} UniProt TrEMBL .dat or .dat.gz"),
            "goa": _ask(f"{role} GO annotations .gaf, .gaf.gz or .gaf.N"),
            "taxonomy_dir": _ask(f"{role} folder with NCBI taxonomy *.dmp files"),
        }
    print("\nThe built-in experimental evidence profile is a PROGENY reference")
    print("snapshot (NOT an official ECO policy). Review its classification")
    print("in config/stage08_evidence_classes_v2.example.json before use.")
    print("Default SCORE: EXP IDA IPI IMP IGI IEP HTP HDA HMP HGI HEP")
    print("Default NON_SCORE: IBA IBD IKR IRD IC TAS ISS ISO ISA ISM")
    print("                   IGC RCA IEA")
    print("Default EXCLUDED: NAS ND")
    if _ask("Accept this reference profile? Type YES to confirm") != "YES":
        raise ValueError("Evidence profile not accepted; no changes made")
    answers["policy_profile"] = "reference"
    answers["exact_policy"] = _menu(
        "EXACT donor selection:",
        (
            ("strict", "Strict (only the conservative EXACT donor policy)"),
            ("same_species_exact", "Audited same-species EXACT donors across subtaxa"),
        ),
    )
    answers["partial_sequence"] = _menu(
        "Partial sequence donor handling:",
        (("report_only", "Report only"), ("allow", "Allow eligible partial donors")),
    )
    answers["documentary_fragment"] = _menu(
        "Documentarily supported fragment donors:",
        (("report_only", "Report only"), ("allow", "Allow eligible fragments")),
    )
    print("\nComputing resources (a safe starting point for small studies):")
    answers["threads"] = int(_ask("Maximum number of CPU cores", "1"))
    answers["max_pair_cells"] = 50_000_000
    answers["max_total_cells"] = 500_000_000
    answers["max_chunk_cells"] = 50_000_000
    print("  DP budget defaults are conservative; see README for Power User mode.")
    if (
        _menu(
            "Load a separately validated Power User JSON configuration?",
            (
                ("no", "No, keep the reviewed defaults"),
                ("yes", "Yes, supply an advanced configuration"),
            ),
        )
        == "yes"
    ):
        answers["advanced_config"] = _ask("Absolute path to advanced JSON file")
    if (
        _menu(
            "Will you submit this study through SLURM (sbatch) on an HPC cluster?",
            (
                ("no", "No, I will use tmux or nohup"),
                ("yes", "Yes, also create a SLURM submission script"),
            ),
        )
        == "yes"
    ):
        print("SLURM resources must match your cluster's allowed allocations.")
        print("All stages run within ONE compute-node allocation.")
        answers["execution"] = {
            "slurm": {
                "memory_gb": int(_ask("Memory to request (GiB, e.g. 64)")),
                "time": _ask("Maximum time HH:MM:SS or D-HH:MM:SS"),
                "partition": _ask("Partition (blank = cluster default)", ""),
                "account": _ask("Account (blank = cluster default)", ""),
            }
        }
    print("\nReview selected setup:")
    print(f"  Data: {dataset}\n  Run: {run}")
    print(
        f"  Releases: {answers['releases']['START']['release_id']} -> "
        f"{answers['releases']['END']['release_id']}"
    )
    print(f"  UniProt IDs: {answers['header_ids_are_uniprot_accessions']}")
    print(f"  EXACT: {answers['exact_policy']}")
    print(f"  Partial: {answers['partial_sequence']}")
    print(f"  Documentary fragments: {answers['documentary_fragment']}")
    if _ask("Create and validate this study? Type YES to confirm") != "YES":
        raise ValueError("User cancelled; no changes made")
    return answers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--answers", type=Path, help="Expert automation; users do not need JSON"
    )
    parser.add_argument(
        "--advanced-config",
        type=Path,
        help="Opt-in advanced evidence and runtime configuration JSON",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Expert test mode: require existing binaries",
    )
    args = parser.parse_args(argv)
    if not sys.platform.startswith("linux"):
        parser.error("The native PROGENY guided setup currently requires Linux")
    repo = Path(__file__).resolve().parents[2]
    if args.answers:
        path = _physical_file(str(args.answers), "answers file")
        options = json.loads(path.read_text(encoding="utf-8"))
    else:
        if not sys.stdin.isatty():
            parser.error(
                "Interactive terminal required, or use --answers for automation"
            )
        options = interactive_answers()
    if args.advanced_config:
        if options.get("advanced_config"):
            parser.error("Specify advanced config once, not in both places")
        options["advanced_config"] = str(args.advanced_config)
    create_project(options, repo=repo, build_missing=not args.no_build)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"\nPROGENY setup did not complete: {error}", file=sys.stderr)
        raise SystemExit(2) from None
