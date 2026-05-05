#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from case_selection import choose_managed_case_specs_interactively, prompt_yes_no
from layout import StudyPaths, choose_study_paths_interactively
from setup_cases import describe_alias, load_case_setup, stage_case


RESULT_PATTERNS = (
    "history.csv",
    "flow.vtu",
    "surface_flow.vtu",
    "shock.csv",
    "shock_*.csv",
    "shock_*.vtp",
    "logs/solver/solver_*.out",
    "logs/solver/solver_*.err",
    "logs/solver/orion_*.out",
    "logs/solver/orion_*.err",
    "logs/solver/slurm-*.out",
    "solver_*.out",
    "solver_*.err",
    "orion_*.out",
    "orion_*.err",
    "slurm-*.out",
)


class SubmissionAborted(Exception):
    pass


def has_nonrestart_outputs(case_dir: Path) -> bool:
    return any(any(case_dir.glob(pattern)) for pattern in RESULT_PATTERNS)


def build_sbatch_command(paths: StudyPaths, spec: dict[str, object], case_dir: Path) -> list[str]:
    case_name = str(spec["case_name"])
    generated_cfg = paths.generated_config_path(str(spec["case_name"]))
    solver_logs_dir = paths.solver_logs_dir(case_name)
    return [
        "sbatch",
        "--export=NONE",
        "--get-user-env=L",
        "--job-name",
        str(spec["job_name"]),
        "--nodes",
        str(spec["job_nodes"]),
        "--ntasks-per-node",
        str(spec["job_ntasks_per_node"]),
        "--cpus-per-task",
        str(spec["job_cpus_per_task"]),
        "--mem",
        str(spec["job_mem"]),
        "--time",
        str(spec["job_time"]),
        "--account",
        str(spec["job_account"]),
        "--output",
        str(solver_logs_dir / "solver_%j.out"),
        "--error",
        str(solver_logs_dir / "solver_%j.err"),
        "--chdir",
        str(case_dir),
        str(paths.run_case_script),
        str(generated_cfg),
    ]


def resolve_alias_targets(
    selected_specs: list[dict[str, object]],
    all_specs: list[dict[str, object]],
) -> list[dict[str, object]]:
    spec_by_name = {str(spec["case_name"]): spec for spec in all_specs}
    resolved_specs: list[dict[str, object]] = []
    seen_targets: set[str] = set()

    for spec in selected_specs:
        selected_name = str(spec["case_name"])
        target_name = str(spec.get("alias_of") or selected_name)
        if target_name != selected_name:
            alias_note = describe_alias(spec)
            if alias_note and alias_note != target_name:
                print(f"{selected_name}: alias of {alias_note}, using {target_name}")
            else:
                print(f"{selected_name}: alias of {target_name}, using {target_name}")

        if target_name in seen_targets:
            print(f"{selected_name}: skipped, target {target_name} is already covered")
            continue

        seen_targets.add(target_name)
        resolved_specs.append(spec_by_name[target_name])

    return resolved_specs


def choose_submit_mode() -> bool:
    print("\nChoose solver submission mode:\n")
    print("  1) Dry-run (print sbatch commands only)")
    print("  2) Submit jobs now")
    print("\n  q) Quit\n")

    choice = input("Mode [1/2/q]: ").strip().lower()
    if choice == "1":
        return False
    if choice == "2":
        return True
    if choice == "q":
        raise SubmissionAborted("Submission cancelled.")
    raise SubmissionAborted("Invalid selection.")


def confirm_submit_all(selected_count: int, total_count: int, submit_jobs: bool) -> None:
    if not submit_jobs or selected_count != total_count:
        return
    confirm = input('You selected every managed case. Type SUBMIT ALL to continue: ').strip()
    if confirm != "SUBMIT ALL":
        raise SubmissionAborted("Submission cancelled.")


def main() -> int:
    paths = choose_study_paths_interactively()
    _, template_text, all_case_specs = load_case_setup(paths)

    try:
        submit_jobs = choose_submit_mode()
        resubmit_existing = prompt_yes_no(
            "Allow cases with existing solver outputs to be submitted again?",
            default=False,
        )
        case_specs = choose_managed_case_specs_interactively(all_case_specs, action_label="submit")
        if not case_specs:
            return 0
        confirm_submit_all(len(case_specs), len(all_case_specs), submit_jobs)
    except SubmissionAborted as exc:
        print(exc)
        return 1

    case_specs = resolve_alias_targets(case_specs, all_case_specs)

    if submit_jobs and shutil.which("sbatch") is None:
        raise SystemExit("sbatch was not found in PATH. Use the dry-run mode instead.")

    planned = 0
    skipped = 0
    for spec in case_specs:
        case_dir = paths.case_path(str(spec["case_name"]))
        restart_file = case_dir / "restart_flow.dat"

        if spec["restart_sol"] == "YES":
            if not restart_file.exists():
                print(f"{spec['case_name']}: skipped, RESTART_SOL=YES but {restart_file.name} is missing")
                skipped += 1
                continue
        elif has_nonrestart_outputs(case_dir) and not resubmit_existing:
            print(f"{spec['case_name']}: skipped, solver outputs already exist in {case_dir}")
            skipped += 1
            continue

        command = build_sbatch_command(paths, spec, case_dir)
        printable = " ".join(command)

        if not submit_jobs:
            print(f"[dry-run] {printable}")
            planned += 1
            continue

        stage_case(paths, spec, template_text)
        paths.ensure_case_runtime_dirs(str(spec["case_name"]))
        try:
            completed = subprocess.run(command, check=True, text=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            print(f"{spec['case_name']}: submission failed")
            print(f"  command: {' '.join(command)}")
            if exc.stdout.strip():
                print(f"  stdout: {exc.stdout.strip()}")
            if exc.stderr.strip():
                print(f"  stderr: {exc.stderr.strip()}")
            return 1
        except OSError as exc:
            print(f"{spec['case_name']}: failed to launch sbatch: {exc}")
            return 1
        print(f"{spec['case_name']}: {completed.stdout.strip()}")
        planned += 1

    print()
    mode = "submitted" if submit_jobs else "planned"
    print(f"Study: {paths.study_name}")
    print(f"Summary: {mode}={planned}, skipped={skipped}, run_script={paths.run_case_script}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
