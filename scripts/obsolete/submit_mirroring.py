#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from hypersonics_cfd.cases import (
    deduplicate_case_names,
    discover_postprocess_cases,
    mach_sort_key,
    prompt_with_default,
    prompt_yes_no,
    resolve_case_path,
)
from hypersonics_cfd.study import StudyPaths, choose_study_paths_interactively
from hypersonics_cfd.workflow.slurm import command_string, submit_sbatch


FLOW_FILENAME = "flow.vtu"
FULL_FLOW_FILENAME = "flow_full.vtu"
DEFAULT_CPUS_PER_TASK = 1
DEFAULT_MEM = ""
DEFAULT_TIME_LIMIT = "02:00:00"


def load_submit_defaults(study_file: Path) -> tuple[int, str, str, str]:
    account = "rrg-jphickey"
    cpus_per_task = DEFAULT_CPUS_PER_TASK
    mem = DEFAULT_MEM
    time_limit = DEFAULT_TIME_LIMIT
    if not study_file.exists():
        return cpus_per_task, mem, time_limit, account

    with study_file.open("rb") as handle:
        matrix = tomllib.load(handle)

    defaults = dict(matrix.get("defaults", {}))
    account = str(defaults.get("job_account", account))
    cpus_per_task = int(defaults.get("mirror_job_cpus_per_task", cpus_per_task))
    mem = str(defaults.get("mirror_job_mem", mem))
    time_limit = str(defaults.get("mirror_job_time", time_limit))
    return cpus_per_task, mem, time_limit, account


def choose_mirror_cases(cases_dir: Path) -> list[str]:
    all_cases, _ = discover_postprocess_cases(cases_dir, FLOW_FILENAME)
    if not all_cases:
        print(f"No active case folders with {FLOW_FILENAME} found under {cases_dir}.")
        return []

    grouped: dict[str, list[str]] = {}
    for case_name in all_cases:
        mach = case_name.split("_", maxsplit=1)[0]
        grouped.setdefault(mach, []).append(case_name)

    menu_items: list[tuple[str, list[str]]] = []
    print("\nSelect half-domain cases to mirror:\n")
    for mach in sorted(grouped, key=mach_sort_key):
        cases = grouped[mach]
        label = f"{mach.upper()} cases ({', '.join(cases)})"
        menu_items.append((label, cases))
        print(f"  {len(menu_items)}) {label}")

    menu_items.append(("All active cases", all_cases))
    print(f"  {len(menu_items)}) All active cases")

    menu_items.append(("CUSTOM", []))
    print(f"  {len(menu_items)}) Custom case name(s)")
    print("\n  q) Quit\n")

    choice = input(f"Case group [1-{len(menu_items)}/q]: ").strip()
    if choice.lower() == "q":
        return []

    try:
        index = int(choice) - 1
        assert 0 <= index < len(menu_items)
    except (ValueError, AssertionError):
        raise SystemExit("Invalid case selection.")

    label, selected = menu_items[index]
    if label != "CUSTOM":
        return selected

    requested = input("Case name(s), separated by spaces: ").split()
    unknown = sorted(set(requested) - set(all_cases))
    if unknown:
        raise SystemExit(f"Unknown active case name(s): {', '.join(unknown)}")
    return requested


def choose_submit_mode() -> bool:
    print("\nChoose mirroring submission mode:\n")
    print("  1) Dry-run (print sbatch commands only)")
    print("  2) Submit jobs now")
    print("\n  q) Quit\n")

    choice = input("Mode [1/2/q]: ").strip().lower()
    if choice == "1":
        return False
    if choice == "2":
        return True
    if choice == "q":
        raise SystemExit(0)
    raise SystemExit("Invalid submission mode.")


def choose_resource_settings(
    default_cpus: int,
    default_mem: str,
    default_time: str,
    default_account: str,
) -> tuple[int, str, str, str]:
    print("\nMirroring resource defaults:")
    print(f"  cpus-per-task: {default_cpus}")
    print(f"  mem:           {default_mem or 'cluster default'}")
    print(f"  time:          {default_time}")
    print(f"  account:       {default_account}")

    if prompt_yes_no("Use these defaults?", default=True):
        return default_cpus, default_mem, default_time, default_account

    cpus_text = prompt_with_default("CPUs per task", str(default_cpus))
    mem = prompt_with_default("Memory request (blank = cluster default)", default_mem)
    time_limit = prompt_with_default("Walltime", default_time)
    account = prompt_with_default("Account", default_account)

    try:
        cpus_per_task = int(cpus_text)
    except ValueError as exc:
        raise SystemExit(f"Invalid CPU count: {cpus_text}") from exc
    if cpus_per_task <= 0:
        raise SystemExit("CPUs per task must be positive.")
    return cpus_per_task, mem, time_limit, account


def build_sbatch_command(
    paths: StudyPaths,
    run_script: Path,
    mirror_script: Path,
    case_path: Path,
    *,
    cpus_per_task: int,
    mem: str,
    time_limit: str,
    account: str,
    overwrite: bool,
) -> list[str]:
    log_dir = case_path / "logs" / "mirroring"
    command = [
        "sbatch",
        "--export=NONE",
        "--get-user-env",
        "--job-name",
        f"mirror_{case_path.name}",
        "--nodes",
        "1",
        "--ntasks",
        "1",
        "--cpus-per-task",
        str(cpus_per_task),
        "--time",
        time_limit,
        "--account",
        account,
        "--output",
        str(log_dir / "mirror_%j.out"),
        "--error",
        str(log_dir / "mirror_%j.err"),
        "--chdir",
        str(paths.repo_root),
        str(run_script),
        str(mirror_script),
        str(case_path),
        "1" if overwrite else "0",
    ]
    if mem.strip():
        time_index = command.index("--time")
        command[time_index:time_index] = ["--mem", mem]
    return command


def main() -> int:
    paths = choose_study_paths_interactively()
    submit_jobs = choose_submit_mode()
    overwrite = prompt_yes_no(
        f"Allow an existing {FULL_FLOW_FILENAME} to be replaced after a successful rerun?",
        default=False,
    )
    defaults = load_submit_defaults(paths.study_file)
    cpus_per_task, mem, time_limit, account = choose_resource_settings(*defaults)

    if submit_jobs and shutil.which("sbatch") is None:
        raise SystemExit("sbatch was not found in PATH. Use the dry-run mode instead.")

    cases = choose_mirror_cases(paths.cases_dir)
    cases = deduplicate_case_names(paths.study_root, paths.cases_dir, cases)
    if not cases:
        return 0

    run_script = paths.repo_root / "templates" / "slurm" / "run_mirror_sym_flow.sh"
    mirror_script = paths.repo_root / "scripts" / "mirror_sym_flow.py"
    if not run_script.exists():
        raise SystemExit(f"Missing SLURM run script: {run_script}")
    if not mirror_script.exists():
        raise SystemExit(f"Missing mirroring script: {mirror_script}")

    planned = 0
    skipped = 0
    for case_name in cases:
        case_path = resolve_case_path(paths.study_root, paths.cases_dir, case_name)
        source = case_path / FLOW_FILENAME
        destination = case_path / FULL_FLOW_FILENAME

        if not source.exists():
            print(f"{case_name}: skipped, missing {FLOW_FILENAME}")
            skipped += 1
            continue
        if destination.exists() and not overwrite:
            print(f"{case_name}: skipped, {FULL_FLOW_FILENAME} already exists")
            skipped += 1
            continue

        command = build_sbatch_command(
            paths,
            run_script,
            mirror_script,
            case_path,
            cpus_per_task=cpus_per_task,
            mem=mem,
            time_limit=time_limit,
            account=account,
            overwrite=overwrite,
        )
        printable = command_string(command)
        if not submit_jobs:
            print(f"[dry-run] {printable}")
            planned += 1
            continue

        (case_path / "logs" / "mirroring").mkdir(parents=True, exist_ok=True)
        try:
            stdout, _ = submit_sbatch(command)
        except subprocess.CalledProcessError as exc:
            print(f"{case_name}: submission failed")
            print(f"  command: {printable}")
            if exc.stdout.strip():
                print(f"  stdout: {exc.stdout.strip()}")
            if exc.stderr.strip():
                print(f"  stderr: {exc.stderr.strip()}")
            return 1
        except OSError as exc:
            print(f"{case_name}: failed to launch sbatch: {exc}")
            return 1

        print(f"{case_name}: {stdout}")
        planned += 1

    print()
    mode = "submitted" if submit_jobs else "planned"
    print(f"Study: {paths.study_name}")
    print(f"Summary: {mode}={planned}, skipped={skipped}, run_script={run_script}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
