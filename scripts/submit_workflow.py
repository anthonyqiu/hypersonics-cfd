#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import tomllib
from pathlib import Path

from case_selection import (
    choose_managed_case_specs_interactively,
    filter_case_specs,
    prompt_with_default,
    prompt_yes_no,
)
from layout import StudyPaths, choose_study_paths_interactively, get_study_paths
from setup_cases import load_case_setup, stage_case
from slurm_helpers import add_afterok_dependency, command_string, submit_sbatch


HALF_FLOW_FILENAME = "flow.vtu"
FULL_FLOW_FILENAME = "flow_full.vtu"
DEFAULT_POST_CPUS_PER_TASK = 32
DEFAULT_POST_MEM = ""
DEFAULT_POST_STEP_TIMES = {
    "mirror": "00:30:00",
    "slices": "00:30:00",
    "shock": "00:30:00",
}
POSTPROCESS_STEPS = ("mirror", "slices", "shock")
POSTPROCESS_STEP_TIME_KEYS = {
    "mirror": "mirror_job_time",
    "slices": "slices_job_time",
    "shock": "shock_job_time",
}
POSTPROCESS_STEP_JOB_PREFIXES = {
    "mirror": "mirror",
    "slices": "slices",
    "shock": "shock",
}

HELP_TEXT = """\
Submit the Orion CFD workflow interactively.

Usage:
  python3 scripts/submit_workflow.py
  python3 scripts/submit_workflow.py --dry-run --cases m1p5_medium,m1p5_fine --full-workflow
  python3 scripts/submit_workflow.py --submit --cases m1p5_medium --solver --mirror --slices --shock

The workflow can submit:
  solver -> mirror -> slices -> shock

Case selection, dry-run vs submit, restart/resubmit behavior, and postprocess
overwrite behavior are selected from prompts. In dry-run mode, no jobs are
submitted; the sbatch commands are printed.
"""

SOLVER_OUTPUT_PATTERNS = (
    "history.csv",
    "flow.vtu",
    "surface_flow.vtu",
)


def has_solver_outputs(case_dir: Path) -> bool:
    return any(
        candidate.is_file() and candidate.stat().st_size > 0
        for pattern in SOLVER_OUTPUT_PATTERNS
        for candidate in case_dir.glob(pattern)
    )


def complete_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def load_postprocess_defaults(study_file: Path) -> tuple[int, str, dict[str, str], str]:
    cpus_per_task = DEFAULT_POST_CPUS_PER_TASK
    mem = DEFAULT_POST_MEM
    step_times = dict(DEFAULT_POST_STEP_TIMES)
    account = "rrg-jphickey"
    if not study_file.exists():
        return cpus_per_task, mem, step_times, account

    with study_file.open("rb") as handle:
        matrix = tomllib.load(handle)

    defaults = dict(matrix.get("defaults", {}))
    account = str(defaults.get("job_account", account))
    cpus_per_task = int(defaults.get("postprocess_job_cpus_per_task", cpus_per_task))
    mem = str(defaults.get("postprocess_job_mem", mem))
    fallback_time = defaults.get("postprocess_job_time")
    for step, default_time in DEFAULT_POST_STEP_TIMES.items():
        time_key = POSTPROCESS_STEP_TIME_KEYS[step]
        step_times[step] = str(defaults.get(time_key, fallback_time or default_time))
    return cpus_per_task, mem, step_times, account


def postprocess_time_for_step(
    spec: dict[str, object],
    default_step_times: dict[str, str],
    step: str,
) -> str:
    time_key = POSTPROCESS_STEP_TIME_KEYS[step]
    return str(
        spec.get(time_key)
        or spec.get("postprocess_job_time")
        or default_step_times.get(step)
        or DEFAULT_POST_STEP_TIMES[step]
    )


def selected_postprocess_steps(run_mirror: bool, run_slices: bool, run_shock: bool) -> list[str]:
    selected: list[str] = []
    if run_mirror:
        selected.append("mirror")
    if run_slices:
        selected.append("slices")
    if run_shock:
        selected.append("shock")
    return selected


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run or submit the managed solver/postprocess workflow.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_TEXT,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Print sbatch commands without submitting.")
    mode.add_argument("--submit", action="store_true", help="Submit sbatch jobs.")
    parser.add_argument("--study", default="", help="Study name, defaulting to the interactive/default study.")
    parser.add_argument("--cases", default="", help="Comma/space separated managed case names.")
    parser.add_argument("--full-workflow", action="store_true", help="Run solver, mirror, slices, and shock.")
    parser.add_argument("--solver", action="store_true", help="Include the solver step.")
    parser.add_argument("--mirror", action="store_true", help="Include the mirror step.")
    parser.add_argument("--slices", action="store_true", help="Include the flow-slice export step.")
    parser.add_argument("--shock", action="store_true", help="Include the shock extraction step.")
    parser.add_argument("--flow-file", default=FULL_FLOW_FILENAME, help="Flow file used by slice/shock steps.")
    parser.add_argument(
        "--resubmit-existing",
        "--rerun-solver",
        action="store_true",
        dest="resubmit_existing",
        help="Allow solver submission even when solver outputs already exist.",
    )
    parser.add_argument(
        "--overwrite-mirror",
        action="store_true",
        help=f"Allow replacing existing {FULL_FLOW_FILENAME}.",
    )
    return parser


def parse_case_names(raw_cases: str) -> list[str]:
    return [part.strip() for part in raw_cases.replace(",", " ").split() if part.strip()]


def workflow_steps_from_args(args: argparse.Namespace) -> tuple[bool, bool, bool, bool, bool, str] | None:
    explicit_step = args.full_workflow or args.solver or args.mirror or args.slices or args.shock
    noninteractive_cases = bool(args.cases and (args.dry_run or args.submit))
    if args.full_workflow or (noninteractive_cases and not explicit_step):
        return True, True, True, True, True, args.flow_file
    if explicit_step:
        run_postprocess = args.mirror or args.slices or args.shock
        return args.solver, run_postprocess, args.mirror, args.slices, args.shock, args.flow_file
    return None


def use_prompt_defaults(args: argparse.Namespace) -> bool:
    return bool(args.cases and (args.dry_run or args.submit))


def choose_submit_mode() -> bool:
    print("\nChoose workflow submission mode:\n")
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


def choose_workflow_steps() -> tuple[bool, bool, bool, bool, bool, str]:
    print("\nWorkflow defaults:")
    print("  solver -> mirror half field -> export slices -> extract shock")
    print(f"  postprocess flow file: {FULL_FLOW_FILENAME}")

    if prompt_yes_no("Use the full workflow?", default=True):
        return True, True, True, True, True, FULL_FLOW_FILENAME

    run_solver = prompt_yes_no("Submit solver step?", default=True)
    run_postprocess = prompt_yes_no("Submit postprocess step?", default=True)
    if not run_postprocess:
        return run_solver, False, False, False, False, FULL_FLOW_FILENAME

    run_mirror = prompt_yes_no("Mirror half field?", default=True)
    run_slices = prompt_yes_no("Export flow slices?", default=True)
    run_shock = prompt_yes_no("Run shock extraction?", default=True)
    default_flow = FULL_FLOW_FILENAME if run_mirror else FULL_FLOW_FILENAME
    flow_file = prompt_with_default("Flow file for slices/shock", default_flow)
    return run_solver, True, run_mirror, run_slices, run_shock, flow_file


def build_solver_command(paths: StudyPaths, spec: dict[str, object], case_dir: Path) -> list[str]:
    case_name = str(spec["case_name"])
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
        str(paths.solver_logs_dir(case_name) / "solver_%j.out"),
        "--error",
        str(paths.solver_logs_dir(case_name) / "solver_%j.err"),
        "--chdir",
        str(case_dir),
        str(paths.run_case_script),
        str(paths.generated_config_path(case_name)),
    ]


def postprocess_flags_for_step(step: str, overwrite_mirror: bool) -> tuple[bool, bool, bool, bool]:
    if step == "mirror":
        return True, overwrite_mirror, False, False
    if step == "slices":
        return False, False, True, False
    if step == "shock":
        return False, False, False, True
    raise ValueError(f"unknown postprocess step: {step}")


def build_postprocess_step_command(
    paths: StudyPaths,
    case_name: str,
    *,
    step: str,
    flow_file: str,
    overwrite_mirror: bool,
    cpus_per_task: int,
    mem: str,
    time_limit: str,
    account: str,
) -> list[str]:
    case_path = paths.case_path(case_name)
    log_dir = case_path / "logs" / "postprocess"
    run_script = paths.repo_root / "templates" / "slurm" / "run_postprocess_workflow.sh"
    run_mirror, mirror_overwrite_flag, run_slices, run_shock = postprocess_flags_for_step(
        step,
        overwrite_mirror,
    )
    job_prefix = POSTPROCESS_STEP_JOB_PREFIXES[step]
    command = [
        "sbatch",
        "--export=NONE",
        "--get-user-env",
        "--job-name",
        f"{job_prefix}_{case_name}",
        "--nodes",
        "1",
        "--ntasks",
        "1",
        "--cpus-per-task",
        str(cpus_per_task),
        "--time",
        str(time_limit),
        "--account",
        str(account),
        "--output",
        str(log_dir / f"{job_prefix}_%j.out"),
        "--error",
        str(log_dir / f"{job_prefix}_%j.err"),
        "--chdir",
        str(paths.repo_root),
        str(run_script),
        paths.study_name,
        case_name,
        flow_file,
        "1" if run_mirror else "0",
        "1" if mirror_overwrite_flag else "0",
        "1" if run_slices else "0",
        "1" if run_shock else "0",
    ]
    if mem.strip():
        time_index = command.index("--time")
        command[time_index:time_index] = ["--mem", mem]
    return command


def submit_or_print(command: list[str], *, submit_jobs: bool, label: str) -> str:
    printable = command_string(command)
    if not submit_jobs:
        print(f"[dry-run] {printable}")
        return "<" + label.replace(":", "").replace(" ", "_") + ">"

    try:
        stdout, job_id = submit_sbatch(command)
    except subprocess.CalledProcessError as exc:
        print(f"{label}: submission failed")
        print(f"  command: {printable}")
        if exc.stdout.strip():
            print(f"  stdout: {exc.stdout.strip()}")
        if exc.stderr.strip():
            print(f"  stderr: {exc.stderr.strip()}")
        raise SystemExit(1) from exc
    except OSError as exc:
        print(f"{label}: failed to launch sbatch: {exc}")
        raise SystemExit(1) from exc

    print(f"{label}: {stdout}")
    if not job_id:
        print(f"{label}: could not parse SLURM job id from sbatch output")
        raise SystemExit(1)
    return job_id


def solver_can_be_submitted(spec: dict[str, object], case_dir: Path, resubmit_existing: bool) -> bool:
    restart_file = case_dir / "restart_flow.dat"
    if has_solver_outputs(case_dir) and not resubmit_existing:
        print(f"{spec['case_name']}: skip solver, solver outputs already exist")
        return False
    if spec["restart_sol"] == "YES" and not restart_file.exists():
        print(f"{spec['case_name']}: skip solver, RESTART_SOL=YES but {restart_file.name} is missing")
        return False
    return True


def postprocess_step_outputs_complete(
    case_dir: Path,
    step: str,
    *,
    overwrite_mirror: bool,
) -> bool:
    if step == "mirror":
        return complete_file(case_dir / FULL_FLOW_FILENAME) and not overwrite_mirror
    if step == "slices":
        return complete_file(case_dir / "flow_slice_xy.vtp") and complete_file(case_dir / "flow_slice_xz.vtp")
    if step == "shock":
        return complete_file(case_dir / "shock_surface.csv") and complete_file(case_dir / "shock_surface.vtp")
    raise ValueError(f"unknown postprocess step: {step}")


def postprocess_step_inputs_ready(
    case_name: str,
    case_dir: Path,
    *,
    step: str,
    flow_file: str,
    dependencies: list[str],
) -> bool:
    if dependencies:
        return True

    if step == "mirror":
        if complete_file(case_dir / HALF_FLOW_FILENAME):
            return True
        print(f"{case_name}: skip postprocess, missing {HALF_FLOW_FILENAME}")
        return False

    if complete_file(case_dir / flow_file):
        return True
    print(f"{case_name}: skip {step}, missing {flow_file}")
    return False


def main() -> int:
    args = build_arg_parser().parse_args()

    paths = get_study_paths(args.study) if args.study else choose_study_paths_interactively()
    _, template_text, all_case_specs = load_case_setup(paths)
    if not all_case_specs:
        print("No managed cases were found in study.toml.")
        return 1

    if args.dry_run:
        submit_jobs = False
    elif args.submit:
        submit_jobs = True
    else:
        submit_jobs = choose_submit_mode()

    workflow_steps = workflow_steps_from_args(args)
    if workflow_steps is None:
        run_solver, run_postprocess, run_mirror, run_slices, run_shock, flow_file = choose_workflow_steps()
    else:
        run_solver, run_postprocess, run_mirror, run_slices, run_shock, flow_file = workflow_steps

    if args.resubmit_existing:
        resubmit_existing = True
    elif use_prompt_defaults(args):
        resubmit_existing = False
    else:
        resubmit_existing = prompt_yes_no("Allow solver jobs with existing outputs?", default=False)

    overwrite_mirror = False
    if run_postprocess and run_mirror:
        if args.overwrite_mirror:
            overwrite_mirror = True
        elif use_prompt_defaults(args):
            overwrite_mirror = False
        else:
            overwrite_mirror = prompt_yes_no(f"Allow replacing existing {FULL_FLOW_FILENAME}?", default=False)

    if not run_solver and not run_postprocess:
        print("No workflow steps selected.")
        return 0
    if run_postprocess and not run_mirror and not run_slices and not run_shock:
        print("No postprocess steps selected.")
        return 0

    if submit_jobs and shutil.which("sbatch") is None:
        raise SystemExit("sbatch was not found in PATH. Use dry-run mode instead.")

    post_cpus, post_mem, default_post_step_times, post_account = load_postprocess_defaults(paths.study_file)
    post_steps = selected_postprocess_steps(run_mirror, run_slices, run_shock)

    print("\nWorkflow:")
    print(f"  Study:      {paths.study_name}")
    print(f"  Steps:      solver={run_solver}, postprocess={run_postprocess}")
    if run_postprocess:
        print(
            f"  Postprocess: mirror={run_mirror}, slices={run_slices}, shock={run_shock}, "
            f"flow_file={flow_file}"
        )
        default_step_summary = ", ".join(
            f"{step}={default_post_step_times[step]}" for step in post_steps
        )
        print(
            f"  Postprocess resources: cpus-per-task={post_cpus}, "
            f"mem={post_mem or 'not requested'}, default times=({default_step_summary}), "
            f"account={post_account}"
        )

    requested_cases = parse_case_names(args.cases)
    if requested_cases:
        selected_specs = filter_case_specs(all_case_specs, requested_cases, [], [], [], [])
    else:
        selected_specs = choose_managed_case_specs_interactively(
            all_case_specs,
            action_label="run through the workflow",
            custom_example="m9_aoa0",
        )
    if not selected_specs:
        return 0

    postprocess_run_script = paths.repo_root / "templates" / "slurm" / "run_postprocess_workflow.sh"
    mirror_script = paths.repo_root / "scripts" / "mirror_sym_flow.py"
    if run_postprocess:
        for required in (postprocess_run_script,):
            if not required.exists():
                raise SystemExit(f"Missing workflow file: {required}")
        if run_mirror and not mirror_script.exists():
            raise SystemExit(f"Missing workflow file: {mirror_script}")

    planned_solver = 0
    planned_post = {step: 0 for step in POSTPROCESS_STEPS}
    already_complete = 0
    skipped = 0

    for spec in selected_specs:
        case_name = str(spec["case_name"])
        alias_of = str(spec.get("alias_of", ""))
        case_dir = paths.case_path(case_name)
        dependencies: list[str] = []
        print(f"\n-> {case_name}")

        if alias_of:
            if submit_jobs:
                stage_case(paths, spec, template_text)
            print(f"{case_name}: alias of {alias_of}; workflow is handled by the target case")
            skipped += 1
            continue

        if run_solver and solver_can_be_submitted(spec, case_dir, resubmit_existing):
            if submit_jobs:
                stage_case(paths, spec, template_text)
                paths.ensure_case_runtime_dirs(case_name)
            solver_command = build_solver_command(paths, spec, case_dir)
            solver_job = submit_or_print(solver_command, submit_jobs=submit_jobs, label=f"{case_name}: solver")
            dependencies = [solver_job]
            planned_solver += 1
        elif run_solver:
            skipped += 1

        if run_postprocess:
            for step in post_steps:
                if postprocess_step_outputs_complete(
                    case_dir,
                    step,
                    overwrite_mirror=overwrite_mirror,
                ):
                    print(f"{case_name}: skip {step}, outputs already complete")
                    already_complete += 1
                    continue

                if not postprocess_step_inputs_ready(
                    case_name,
                    case_dir,
                    step=step,
                    flow_file=flow_file,
                    dependencies=dependencies,
                ):
                    skipped += 1
                    break

                if submit_jobs:
                    (case_dir / "logs" / "postprocess").mkdir(parents=True, exist_ok=True)
                post_command = build_postprocess_step_command(
                    paths,
                    case_name,
                    step=step,
                    flow_file=flow_file,
                    overwrite_mirror=overwrite_mirror,
                    cpus_per_task=post_cpus,
                    mem=post_mem,
                    time_limit=postprocess_time_for_step(spec, default_post_step_times, step),
                    account=post_account,
                )
                post_command = add_afterok_dependency(post_command, dependencies)
                post_job = submit_or_print(
                    post_command,
                    submit_jobs=submit_jobs,
                    label=f"{case_name}: {step}",
                )
                dependencies = [post_job]
                planned_post[step] += 1

    mode = "submitted" if submit_jobs else "planned"
    post_summary = ", ".join(f"{step}={planned_post[step]}" for step in POSTPROCESS_STEPS)
    print()
    print(
        f"Summary: {mode} solver={planned_solver}, postprocess({post_summary}), "
        f"already_complete={already_complete}, skipped={skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
