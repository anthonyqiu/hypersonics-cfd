#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

from case_selection import (
    choose_postprocess_cases_interactively,
    deduplicate_case_names,
    prompt_with_default,
    prompt_yes_no,
    resolve_case_path,
)
from layout import choose_study_paths_interactively


FLOW_FILENAME = "flow.vtu"
SHOCK_OUTPUTS = ("shock_surface.vtp", "shock_surface.csv")
DEFAULT_MEM = "0"


def load_submit_defaults(study_file: Path) -> tuple[str, str]:
    account = "rrg-jphickey"
    time_limit = "18:00:00"
    if not study_file.exists():
        return account, time_limit

    with study_file.open("rb") as handle:
        matrix = tomllib.load(handle)

    defaults = dict(matrix.get("defaults", {}))
    if defaults.get("job_account"):
        account = str(defaults["job_account"])
    if defaults.get("job_time"):
        time_limit = str(defaults["job_time"])
    return account, time_limit


def has_completed_outputs(case_path: Path) -> bool:
    return all((case_path / name).exists() for name in SHOCK_OUTPUTS)


def build_job_name(case_names: list[str]) -> str:
    if len(case_names) == 1:
        return f"shock_{case_names[0]}"
    return f"shock_batch_{len(case_names)}"


def build_manifest_path(manifest_dir: Path, case_names: list[str], *, for_submit: bool) -> Path:
    job_name = build_job_name(case_names)
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S") if for_submit else "preview"
    return manifest_dir / f"{job_name}_{suffix}.txt"


def write_case_manifest(manifest_path: Path, case_names: list[str]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("\n".join(case_names) + "\n", encoding="utf-8")


def build_sbatch_command(
    repo_root: Path,
    run_script: Path,
    extract_script: Path,
    manifest_path: Path,
    log_dir: Path,
    case_names: list[str],
    *,
    cpus_per_task: int,
    mem: str,
    time_limit: str,
    account: str,
    python_executable: str,
) -> list[str]:
    return [
        "sbatch",
        "--export=NONE",
        "--get-user-env=L",
        "--job-name",
        build_job_name(case_names),
        "--nodes",
        "1",
        "--ntasks-per-node",
        "1",
        "--cpus-per-task",
        str(cpus_per_task),
        "--mem",
        str(mem),
        "--time",
        str(time_limit),
        "--account",
        str(account),
        "--output",
        str(log_dir / "shock_extract_%j.out"),
        "--error",
        str(log_dir / "shock_extract_%j.err"),
        "--chdir",
        str(repo_root),
        str(run_script),
        str(python_executable),
        str(extract_script),
        str(manifest_path),
    ]


def choose_submit_mode() -> bool:
    print("\nChoose shock-extraction submission mode:\n")
    print("  1) Dry-run (print sbatch command only)")
    print("  2) Submit batch job now")
    print("\n  q) Quit\n")

    choice = input("Mode [1/2/q]: ").strip().lower()
    if choice == "1":
        return False
    if choice == "2":
        return True
    if choice == "q":
        raise SystemExit(0)
    raise SystemExit("Invalid submission mode.")


def choose_resource_settings(default_account: str, default_time: str) -> tuple[int, str, str, str, str]:
    print("\nShock extraction resource defaults:")
    print(f"  cpus-per-task: 1")
    print(f"  mem:           {DEFAULT_MEM}")
    print(f"  time:          {default_time}")
    print(f"  account:       {default_account}")
    print(f"  python:        {sys.executable}")

    if prompt_yes_no("Use these defaults?", default=True):
        return 1, DEFAULT_MEM, default_time, default_account, sys.executable

    cpus_text = prompt_with_default("CPUs per task", "1")
    mem = prompt_with_default("Memory request", DEFAULT_MEM)
    time_limit = prompt_with_default("Walltime", default_time)
    account = prompt_with_default("Account", default_account)
    python_executable = prompt_with_default("Python executable", sys.executable)

    try:
        cpus_per_task = int(cpus_text)
    except ValueError as exc:
        raise SystemExit(f"Invalid CPU count: {cpus_text}") from exc

    if cpus_per_task <= 0:
        raise SystemExit("CPUs per task must be positive.")

    python_path = Path(python_executable).expanduser()
    if not python_path.exists():
        raise SystemExit(f"Python executable not found: {python_path}")

    return cpus_per_task, mem, time_limit, account, str(python_path)


def main() -> int:
    paths = choose_study_paths_interactively()
    default_account, default_time = load_submit_defaults(paths.study_file)
    submit_jobs = choose_submit_mode()
    rerun_existing = prompt_yes_no(
        "Allow cases that already have shock_surface outputs to be included again?",
        default=False,
    )
    cpus_per_task, mem, time_limit, account, python_executable = choose_resource_settings(
        default_account,
        default_time,
    )

    if submit_jobs and shutil.which("sbatch") is None:
        raise SystemExit("sbatch was not found in PATH. Use the dry-run mode instead.")

    extract_script = paths.repo_root / "scripts" / "extract_shock_surface.py"
    paths.ensure_runtime_dirs()

    print("\n╔══════════════════════════════════════════════╗")
    print("║   Shock Extraction SLURM Submitter          ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"Study: {paths.study_name}")
    print(f"Run script: {paths.run_shock_extraction_script}")
    print(f"Extractor: {extract_script}")
    print(f"Python: {python_executable}")
    print(
        f"Resources: nodes=1, ntasks-per-node=1, cpus-per-task={cpus_per_task}, mem={mem}, "
        f"time={time_limit}, account={account}"
    )

    cases = choose_postprocess_cases_interactively(paths.cases_dir, FLOW_FILENAME)
    cases = deduplicate_case_names(paths.study_root, paths.cases_dir, cases)
    if not cases:
        return 0

    runnable_case_names: list[str] = []
    skipped = 0
    for case in cases:
        case_path = resolve_case_path(paths.study_root, paths.cases_dir, case)
        flow_path = case_path / FLOW_FILENAME
        if not flow_path.exists():
            print(f"{case}: skipped, missing {FLOW_FILENAME}")
            skipped += 1
            continue

        if has_completed_outputs(case_path) and not rerun_existing:
            print(f"{case_path.name}: skipped, shock_surface outputs already exist")
            skipped += 1
            continue

        runnable_case_names.append(case_path.name)

    if not runnable_case_names:
        print()
        mode = "submitted" if submit_jobs else "planned"
        print(f"Summary: {mode}=0, skipped={skipped}, run_script={paths.run_shock_extraction_script}")
        return 0

    manifest_path = build_manifest_path(paths.shock_manifest_dir, runnable_case_names, for_submit=submit_jobs)
    command = build_sbatch_command(
        paths.repo_root,
        paths.run_shock_extraction_script,
        extract_script,
        manifest_path,
        paths.shock_batch_log_dir,
        runnable_case_names,
        cpus_per_task=cpus_per_task,
        mem=mem,
        time_limit=time_limit,
        account=account,
        python_executable=python_executable,
    )
    printable = " ".join(command)

    if not submit_jobs:
        print(f"[dry-run] {printable}")
        print(f"Manifest: {manifest_path} (created on submit)")
        print(f"Batch contains {len(runnable_case_names)} case(s).")
        print()
        print(f"Summary: planned=1, skipped={skipped}, run_script={paths.run_shock_extraction_script}")
        return 0

    write_case_manifest(manifest_path, runnable_case_names)
    try:
        completed = subprocess.run(command, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        print("shock batch submission failed")
        print(f"  command: {' '.join(command)}")
        if exc.stdout.strip():
            print(f"  stdout: {exc.stdout.strip()}")
        if exc.stderr.strip():
            print(f"  stderr: {exc.stderr.strip()}")
        return 1
    except OSError as exc:
        print(f"failed to launch sbatch: {exc}")
        return 1

    print(f"{build_job_name(runnable_case_names)}: {completed.stdout.strip()}")
    print()
    print(f"Summary: submitted=1, skipped={skipped}, run_script={paths.run_shock_extraction_script}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
