"""Guided setup regression against real fresh preparator and real stage00."""

from __future__ import annotations

import csv
import gzip
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from progeny.canonical_v2.fresh_dag import read_recipe
from progeny.canonical_v2.fresh_preparation import RECIPE_FIELDS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/installation/progeny_setup.py"

sys.path.insert(0, str(ROOT / "scripts/installation"))
from progeny_setup import (  # noqa: E402
    NATIVE_DIR,
    NATIVE_TARGETS,
    _verify_native,
    create_project,
)


def fixture_sources(tmp_path: Path) -> dict:
    sources = tmp_path / "biological"
    sources.mkdir()
    target = sources / "targets.fasta"
    target.write_text(">T1\t111\nACDEFGHIKLMNPQRSTVWY\n", encoding="ascii")
    (sources / "go.owl").write_text("<owl/>\n", encoding="ascii")
    releases = {}
    for role, ident in (("START", "2023_01"), ("END", "2026_03")):
        path = sources / role
        path.mkdir()
        for name in ("sprot", "trembl"):
            (path / f"{name}.dat").write_text(
                "ID   SYNTH Reviewed; 20 AA.\nAC   P10001;\n//\n",
                encoding="ascii",
            )
        gaf = path / "goa.gaf"
        gaf.write_text("!gaf-version: 2.2\n", encoding="ascii")
        tax = path / "taxonomy"
        tax.mkdir()
        (tax / "nodes.dmp").write_text(
            "1\t|\t1\t|\tno rank\t|\n111\t|\t1\t|\tspecies\t|\n"
        )
        (tax / "names.dmp").write_text("1\t|\troot\t|\n111\t|\tSpecies\t|\n")
        (tax / "merged.dmp").write_text("")
        (tax / "delnodes.dmp").write_text("")
        releases[role] = {
            "release_id": ident,
            "taxonomy_id": ident,
            "sprot": str(path / "sprot.dat"),
            "trembl": str(path / "trembl.dat"),
            "goa": str(gaf),
            "taxonomy_dir": str(tax),
        }
    return {
        "dataset_dir": str(tmp_path / "dataset"),
        "run_dir": str(tmp_path / "run"),
        "targets_fasta": str(target),
        "ontology": str(sources / "go.owl"),
        "releases": releases,
        "policy_profile": "reference",
        "exact_policy": "same_species_exact",
        "partial_sequence": "allow",
        "documentary_fragment": "report_only",
        "threads": 1,
        "max_pair_cells": 50000000,
        "max_total_cells": 500000000,
        "max_chunk_cells": 50000000,
    }


@pytest.fixture
def configured(tmp_path: Path):
    # Build an entirely separate source checkout; never modify the real
    # checkout or its .pixi native build cache during tests.
    repo = tmp_path / "repo"
    repo.mkdir()
    for directory in ("src", "scripts", "config", "workflow", "cpp", "cmake"):
        shutil.copytree(ROOT / directory, repo / directory)
    for filename in ("pixi.toml", "pixi.lock", "pyproject.toml"):
        shutil.copy2(ROOT / filename, repo / filename)
    root = repo / NATIVE_DIR
    root.mkdir(parents=True)
    for name in NATIVE_TARGETS:
        path = root / name
        if name in (
            "progeny-directional-glocal-bounded-dp-v2",
            "progeny-directional-glocal-linear-dp-v1",
        ):
            version = name.replace("-", "_")
            path.write_text(
                "#!/bin/sh\n"
                'if [ "$1" = "--version" ]; then\n'
                f'  printf "%s\\n" "{version}"\n'
                "  exit 0\n"
                "fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
        else:
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o700)
    yield fixture_sources(tmp_path), repo


def test_guided_creates_complete_fresh_run(configured):
    answers, repo = configured
    output = create_project(answers, repo=repo, build_missing=False)
    assert output["status"] == "READY"
    run = Path(answers["run_dir"])
    data = Path(answers["dataset_dir"])
    shared = data.parent / "PROGENY_SHARED"
    assert run.is_dir()
    parsed = read_recipe(run / "fresh_recipe.json", expected_repo=repo)
    assert parsed.data.keys() >= RECIPE_FIELDS
    assert parsed.data["policy"] == "same_species_exact"
    assert parsed.pipeline["releases"]["START"]["release_id"] == "2023_01"
    assert (data / "config/scientific-identity-inventory.json").is_file()
    summary = json.loads(
        (data / "config/setup-summary.json").read_text(encoding="utf-8")
    )
    assert summary["shared_artifacts_root"] == str(shared)
    assert summary["start_ia_root"] == str(
        shared / "START/2023_01/information_accretion"
    )
    for relative in (
        "START/2023_01/information_accretion",
        "RUNS",
        "native/ia-roaring",
        "scratch/ia-roaring",
    ):
        assert (shared / relative).is_dir()
    assert (data / "targets/00_manifest.json").is_file()
    assert (data / "START_PROGENY.sh").is_file()
    assert "--directory " + str(run) in (data / "START_PROGENY.sh").read_text()
    with pytest.raises(ValueError, match="already exists"):
        create_project(answers, repo=repo, build_missing=False)


def test_refuse_missing_inputs_before_creating_directories(configured):
    answers, repo = configured
    answers["releases"]["END"]["goa"] = "/does/not/exist.gaf"
    with pytest.raises(ValueError, match="missing"):
        create_project(answers, repo=repo, build_missing=False)
    assert not Path(answers["dataset_dir"]).exists()
    assert not Path(answers["run_dir"]).exists()


def test_refuse_unaccepted_or_implicit_scientific_policy(configured):
    answers, repo = configured
    answers["policy_profile"] = "unknown"
    with pytest.raises(ValueError, match="evidence policy"):
        create_project(answers, repo=repo, build_missing=False)
    assert not Path(answers["dataset_dir"]).exists()


def test_gzip_goa_materialization_and_identity(configured):
    answers, repo = configured
    path = Path(answers["releases"]["END"]["goa"])
    gz = path.with_suffix(".gaf.gz")
    with gzip.open(gz, "wb") as stream:
        stream.write(path.read_bytes())
    answers["releases"]["END"]["goa"] = str(gz)
    create_project(answers, repo=repo, build_missing=False)
    run = Path(answers["run_dir"])
    recipe = read_recipe(run / "fresh_recipe.json", expected_repo=repo)
    prepared = Path(recipe.pipeline["releases"]["END"]["goa"])
    assert prepared.read_bytes() == path.read_bytes()


def test_command_line_answers_mode(configured):
    answers, repo = configured
    answers_path = Path(answers["dataset_dir"]).parent / "answers.json"
    answers_path.write_text(json.dumps(answers), encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "src")
    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts/installation/progeny_setup.py"),
            "--answers",
            str(answers_path),
            "--no-build",
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "PROGENY_SETUP=READY" in result.stdout


def test_regular_fasta_single_taxid_mode(configured):
    answers, repo = configured
    original = Path(answers["targets_fasta"])
    original.write_text(">T1 an ordinary FASTA header\nACDEFGHIKLMNPQRSTVWY\n")
    answers["targets_mode"] = "single_species"
    answers["targets_taxid"] = "111"
    create_project(answers, repo=repo, build_missing=False)
    data = Path(answers["dataset_dir"])
    assert (data / "prepared/targets.with_taxid.fasta").read_text() == (
        ">T1\t111\nACDEFGHIKLMNPQRSTVWY\n"
    )
    assert (data / "targets/targets.metadata.tsv").is_file()


def test_multi_species_mapping_must_be_complete(configured):
    answers, repo = configured
    original = Path(answers["targets_fasta"])
    original.write_text(">T1 one\nACDEFGHIKLMNPQRSTVWY\n")
    mapping = original.parent / "taxid-map.tsv"
    mapping.write_text("target_id\tncbi_taxid\nOTHER\t111\n")
    answers["targets_mode"] = "taxid_table"
    answers["targets_taxid_table"] = str(mapping)
    with pytest.raises(ValueError, match="No NCBI TaxID"):
        create_project(answers, repo=repo, build_missing=False)
    assert not Path(answers["run_dir"]).exists()


def test_multi_species_mapping_complete(configured):
    answers, repo = configured
    original = Path(answers["targets_fasta"])
    original.write_text(">T1 annotation\nACDEFGHIKLMNPQRSTVWY\n")
    mapping = original.parent / "taxid-map.tsv"
    mapping.write_text("target_id\tncbi_taxid\nT1\t111\n")
    answers["targets_mode"] = "taxid_table"
    answers["targets_taxid_table"] = str(mapping)
    create_project(answers, repo=repo, build_missing=False)
    assert Path(answers["run_dir"]).is_dir()


def test_unknown_taxid_is_not_silently_dropped(configured):
    answers, repo = configured
    answers["targets_mode"] = "single_species"
    answers["targets_taxid"] = "999999999"
    Path(answers["targets_fasta"]).write_text(
        ">T1\nACDEFGHIKLMNPQRSTVWY\n", encoding="ascii"
    )
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        create_project(answers, repo=repo, build_missing=False)
    assert not Path(answers["run_dir"]).exists()


def test_refuses_reuse_of_any_project_directory(configured):
    answers, repo = configured
    Path(answers["run_dir"]).mkdir()
    with pytest.raises(ValueError, match="already exists"):
        create_project(answers, repo=repo, build_missing=False)
    assert not Path(answers["dataset_dir"]).exists()


def test_launch_modes_create_scripts_without_starting_a_job(configured):
    answers, repo = configured
    summary = create_project(answers, repo=repo, build_missing=False)
    dataset = Path(answers["dataset_dir"])
    assert summary["status"] == "READY"
    assert set(summary["launch_options"]["commands"]) == {
        "direct",
        "tmux",
        "nohup",
    }
    assert not (dataset / "SUBMIT_PROGENY.sbatch").exists()
    for name in (
        "START_PROGENY.sh",
        "RUN_PROGENY_TMUX.sh",
        "RUN_PROGENY_NOHUP.sh",
    ):
        script = dataset / name
        assert script.stat().st_mode & 0o100
        subprocess.run(["bash", "-n", str(script)], check=True)
    instructions = (dataset / "HOW_TO_RUN_PROGENY.txt").read_text()
    assert "No computation has been started" in instructions
    assert "tmux attach -t progeny_" in instructions
    assert "NOHUP" in instructions
    assert not (dataset / "logs/progeny-nohup.pid").exists()


def test_slurm_resources_and_submission_are_explicit(configured):
    answers, repo = configured
    answers["threads"] = 4
    answers["execution"] = {
        "slurm": {
            "memory_gb": 96,
            "time": "3-04:00:00",
            "partition": "bigmem",
            "account": "research_lab",
        }
    }
    summary = create_project(answers, repo=repo, build_missing=False)
    dataset = Path(answers["dataset_dir"])
    file = dataset / "SUBMIT_PROGENY.sbatch"
    subprocess.run(["bash", "-n", str(file)], check=True)
    content = file.read_text()
    for expected in (
        "#SBATCH --nodes=1",
        "#SBATCH --ntasks=1",
        "#SBATCH --cpus-per-task=4",
        "#SBATCH --mem=96G",
        "#SBATCH --time=3-04:00:00",
        "#SBATCH --partition=bigmem",
        "#SBATCH --account=research_lab",
    ):
        assert expected in content
    assert "bash " + str(dataset / "START_PROGENY.sh") in content
    assert "sbatch --output=" in summary["launch_options"]["commands"]["slurm"]
    assert "progeny-slurm-%j.log" in (dataset / "HOW_TO_RUN_PROGENY.txt").read_text()
    assert not list((dataset / "logs").iterdir())


@pytest.mark.parametrize(
    "slurm",
    [
        {"memory_gb": 0, "time": "1-00:00:00", "partition": "", "account": ""},
        {"memory_gb": 4, "time": "0:61:00", "partition": "", "account": ""},
        {"memory_gb": 4, "time": "1-48:00:00", "partition": "", "account": ""},
        {"memory_gb": 4, "time": "1-00:00:00", "partition": "p\njob", "account": ""},
        {"memory_gb": 4, "time": "1-00:00:00", "partition": "", "account": ";rm"},
    ],
)
def test_invalid_slurm_settings_rejected_before_creating_anything(
    configured,
    slurm,
):
    answers, repo = configured
    answers["execution"] = {"slurm": slurm}
    with pytest.raises(ValueError, match="SLURM"):
        create_project(answers, repo=repo, build_missing=False)
    assert not Path(answers["dataset_dir"]).exists()
    assert not Path(answers["run_dir"]).exists()


def test_nohup_launcher_detaches_a_dummy_job_and_saves_log(configured):
    answers, repo = configured
    create_project(answers, repo=repo, build_missing=False)
    dataset = Path(answers["dataset_dir"])
    # Replace the launcher ONLY in this isolated test directory, never
    # invoke the scientific workflow from the wrapper regression test.
    (dataset / "START_PROGENY.sh").write_text(
        "#!/usr/bin/env bash\necho USER_JOB_TEST_ONLY\n", encoding="utf-8"
    )
    result = subprocess.run(
        ["bash", str(dataset / "RUN_PROGENY_NOHUP.sh")],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "NOHUP_SUBMITTED_PID=" in result.stdout
    pid = int((dataset / "logs/progeny-nohup.pid").read_text())
    assert pid > 0
    log = dataset / "logs/progeny-nohup.log"
    import time

    for _ in range(60):
        if log.exists() and "USER_JOB_TEST_ONLY" in log.read_text():
            break
        time.sleep(0.05)
    assert "USER_JOB_TEST_ONLY" in log.read_text()


def test_snakemake_launcher_target_is_not_swallowed_by_config(configured):
    """Check argv in the generated, executable user launcher."""
    answers, repo = configured
    create_project(answers, repo=repo, build_missing=False)
    launcher = Path(answers["dataset_dir"]) / "START_PROGENY.sh"
    lines = launcher.read_text(encoding="utf-8").splitlines()
    assert "set -Eeuo pipefail" in lines
    # The exporter is now the final command; Snakemake must run first.
    commands = [shlex.split(line) for line in lines if line.startswith("pixi run ")]
    assert len(commands) == 2
    argv, export_argv = commands
    assert argv[:4] == ["pixi", "run", "snakemake", "all"]
    assert argv.count("all") == 1
    position = argv.index("--config")
    assert position == len(argv) - 2
    assert argv[position + 1] == (
        f"fresh_recipe={Path(answers['run_dir']) / 'fresh_recipe.json'}"
    )
    assert export_argv[:3] == ["pixi", "run", "python"]
    assert Path(export_argv[3]).name == "publish_progeny_scientific_results.py"
    assert export_argv[4:] == [
        "--dataset",
        answers["dataset_dir"],
        "--run",
        answers["run_dir"],
    ]


@pytest.mark.parametrize(
    "binary_name",
    (
        "progeny-directional-glocal-bounded-dp-v2",
        "progeny-directional-glocal-linear-dp-v1",
    ),
)
@pytest.mark.parametrize(
    "body",
    (
        "#!/bin/sh\nexit 2\n",
        "#!/bin/sh\nprintf 'wrong_version\\n'\n",
    ),
)
def test_guided_rejects_incompatible_dp_protocol(configured, binary_name, body):
    _inputs, repo = configured
    binary = repo / NATIVE_DIR / binary_name
    binary.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="Incompatible PROGENY DP executable"):
        _verify_native(repo, build_missing=False)


def test_guided_maps_bounded_and_linear_dp_roles(configured):
    _inputs, repo = configured
    tools = _verify_native(repo, build_missing=False)
    assert tools["full_dp_binary"].name == ("progeny-directional-glocal-bounded-dp-v2")
    assert (repo / NATIVE_DIR / "progeny-directional-glocal-linear-dp-v1").is_file()


def test_alpha_original_header_ledger_and_export_launcher(configured):
    answers, repo = configured
    source = Path(answers["targets_fasta"])
    source.write_text(
        ">USER_ID_1 full original description for a researcher\nACDEFGHIKLMNPQRSTVWY\n",
        encoding="ascii",
    )
    answers["targets_mode"] = "single_species"
    answers["targets_taxid"] = "111"
    create_project(answers, repo=repo, build_missing=False)
    dataset = Path(answers["dataset_dir"])
    original = (dataset / "identity/original_headers.tsv").read_text()
    assert "USER_ID_1 full original description for a researcher" in original
    assert "T000000001" in original
    assert (dataset / "identity/manifest.json").is_file()
    launch = (dataset / "START_PROGENY.sh").read_text()
    assert "publish_progeny_scientific_results.py" in launch
    assert launch.index("snakemake all") < launch.index(
        "publish_progeny_scientific_results.py"
    )
    assert not (Path(answers["run_dir"]) / "results/benchmark").exists()


def test_alpha_advanced_config_applies_policy_and_runtime(configured):
    answers, repo = configured
    parent = Path(answers["targets_fasta"]).parent
    original_policy = repo / "config/stage08_evidence_classes_v2.example.json"
    custom_policy = parent / "custom-evidence-policy.json"
    custom_policy.write_bytes(original_policy.read_bytes())
    runtime_path = parent / "runtime.json"
    runtime_path.write_text(
        json.dumps(
            {
                "schema": "progeny-fresh-runtime-resources-v1",
                "m8_workers": 2,
                "temporal_workers": 3,
                "m8_mem_mb": 1024,
                "m10c_mem_mb": 2048,
                "temporal_mem_mb": 4096,
            }
        )
    )
    cfg = parent / "advanced.json"
    cfg.write_text(
        json.dumps(
            {
                "schema": "progeny-guided-advanced-v1",
                "threads": 4,
                "temporal_policy": str(custom_policy),
                "performance_profile": str(runtime_path),
                "checkpoint_rows": 128,
            }
        )
    )
    answers["advanced_config"] = str(cfg)
    create_project(answers, repo=repo, build_missing=False)
    dataset = Path(answers["dataset_dir"])
    assert (
        dataset / "policies/temporal_policy.json"
    ).read_bytes() == custom_policy.read_bytes()
    assert (
        dataset / "config/performance.json"
    ).read_bytes() == runtime_path.read_bytes()
    script = (dataset / "START_PROGENY.sh").read_text()
    assert "--cores 4" in script
    assert "performance_profile=" in script
    spec = json.loads((dataset / "config/fresh-spec.json").read_text())
    assert spec["recipe"]["large_dp"]["checkpoint_rows"] == 128


def test_cafa5_tagged_fasta_expected_rejections_and_accessions(configured):
    answers, repo = configured
    source = Path(answers["targets_fasta"])
    sequence = "ACDEFGHIKLMNPQRSTVWY"
    source.write_text(
        f">P10001\t111\n{sequence}\n"
        f">P10001\t111\n{sequence}\n"
        ">P20001\t111\nACDEF\n"
        f">P30001\t111\n{sequence}\n",
        encoding="ascii",
    )
    answers["header_ids_are_uniprot_accessions"] = True
    create_project(answers, repo=repo, build_missing=False)
    dataset = Path(answers["dataset_dir"])
    summary = json.loads((dataset / "targets/00_summary.json").read_text())
    assert summary["accepted_targets"] == 2
    assert summary["deduplicated_identical_records"] == 1
    assert summary["rejected_below_minlen"] == 1
    assert summary["rejected_unknown_taxid"] == 0
    with (dataset / "targets/targets.rejected.tsv").open(newline="") as handle:
        reasons = [row["reason"] for row in csv.DictReader(handle, delimiter="\t")]
    assert reasons == ["DUPLICATE_IDENTICAL_RECORD", "BELOW_MINLEN"]
    with (dataset / "targets/targets.metadata.tsv").open(newline="") as handle:
        records = list(csv.DictReader(handle, delimiter="\t"))
    assert [row["uniprot_accession"] for row in records] == ["P10001", "P30001"]
    ledger = (dataset / "identity/original_headers.tsv").read_text()
    assert "P10001\t111" in ledger
    assert "P30001\t111" in ledger
    assert "P20001" not in ledger
    spec = json.loads(
        (dataset / "config/scientific-identity-inventory.json").read_text()
    )
    assert spec["choices"]["header_ids_are_uniprot_accessions"] is True


def test_cafa5_numbered_uncompressed_gaf_direct_reference(configured):
    answers, repo = configured
    source = Path(answers["releases"]["START"]["goa"])
    numbered = source.with_name("goa.gaf.213")
    source.rename(numbered)
    answers["releases"]["START"]["goa"] = str(numbered)
    create_project(answers, repo=repo, build_missing=False)
    recipe = read_recipe(
        Path(answers["run_dir"]) / "fresh_recipe.json", expected_repo=repo
    )
    assert Path(recipe.pipeline["releases"]["START"]["goa"]) == numbered
    assert numbered.exists()
    assert not (Path(answers["dataset_dir"]) / "prepared/START/goa.gaf").exists()


def test_cafa5_uniprot_accession_flag_must_be_explicit(configured):
    answers, repo = configured
    answers["header_ids_are_uniprot_accessions"] = "yes"
    with pytest.raises(ValueError, match="declaration must be a boolean"):
        create_project(answers, repo=repo, build_missing=False)
    assert not Path(answers["dataset_dir"]).exists()


def test_cafa5_malformed_uniprot_accession_fails_closed(configured):
    answers, repo = configured
    answers["header_ids_are_uniprot_accessions"] = True
    with pytest.raises(subprocess.CalledProcessError):
        create_project(answers, repo=repo, build_missing=False)
    assert not Path(answers["run_dir"]).exists()
