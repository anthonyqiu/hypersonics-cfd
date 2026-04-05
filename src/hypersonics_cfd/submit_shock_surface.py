#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

from .case_selection import deduplicate_case_names, choose_postprocess_cases_interactively, resolve_case_path
from .layout import get_study_paths


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run or submit overnight shock-surface extraction jobs."
    )
    parser.add_argument(
        "--study",
        default="orion",
        help='Study slug under studies/. Defaults to "orion".',
    )
    parser.add_argument(
        "cases",
        nargs="*",
        help="Optional case names or paths. If omitted, the interactive selector is used.",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_flags",
        default=[],
        help="Select an exact case name. Repeat for multiple cases.",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Actually call sbatch. Without this flag the script only prints commands.",
    )
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="Allow submitting cases that already have both shock_surface outputs.",
    )
    parser.add_argument(
        "--time",
        default="",
        help="SLURM walltime for each extraction job. Defaults to the study's configured job_time.",
    )
    parser.add_argument(
        "--account",
        default="",
        help="SLURM account. Defaults to the study's configured job_account.",
    )
    parser.add_argument(
        "--cpus-per-task",
        type=int,
        default=1,
        help="SLURM CPUs per task. Defaults to 1.",
    )
    parser.add_argument(
        "--mem",
        default=DEFAULT_MEM,
        help=f'SLURM memory request. Defaults to "{DEFAULT_MEM}".',
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable to use inside the batch job. Defaults to the current interpreter.",
    )
    return parser.parse_args()


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
    case_names: list[str],
    args: argparse.Namespace,
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
        str(args.cpus_per_task),
        "--mem",
        str(args.mem),
        "--time",
        str(args.time),
        "--account",
        str(args.account),
        "--output",
        "shock_extract_%j.out",
        "--error",
        "shock_extract_%j.err",
        "--chdir",
        str(repo_root),
        str(run_script),
        str(args.python),
        str(extract_script),
        str(manifest_path),
    ]


def main() -> int:
    args = parse_args()
    paths = get_study_paths(args.study)
    default_account, default_time = load_submit_defaults(paths.study_file)
    if not args.account:
        args.account = default_account
    if not args.time:
        args.time = default_time

    if args.cpus_per_task <= 0:
        raise SystemExit("--cpus-per-task must be positive.")

    python_exe = Path(args.python).expanduser()
    if not python_exe.exists():
        raise SystemExit(f"Python executable not found: {python_exe}")
    args.python = str(python_exe)

    if args.submit and shutil.which("sbatch") is None:
        raise SystemExit("sbatch was not found in PATH. Re-run without --submit for a dry run.")

    extract_script = paths.repo_root / "scripts" / "extract_shock_surface.py"
    paths.ensure_runtime_dirs()

    print("\n╔══════════════════════════════════════════════╗")
    print("║   Shock Surface SLURM Submitter             ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"Study: {paths.study_name}")
    print(f"Run script: {paths.run_shock_batch_script}")
    print(f"Extractor: {extract_script}")
    print(f"Python: {args.python}")
    print(
        f"Resources: nodes=1, ntasks-per-node=1, cpus-per-task={args.cpus_per_task}, mem={args.mem}, "
        f"time={args.time}, account={args.account}"
    )

    requested_cases = list(args.case_flags) + list(args.cases)
    cases = requested_cases or choose_postprocess_cases_interactively(paths.cases_dir, FLOW_FILENAME)
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

        if has_completed_outputs(case_path) and not args.rerun:
            print(f"{case_path.name}: skipped, shock_surface outputs already exist")
            skipped += 1
            continue

        runnable_case_names.append(case_path.name)

    if not runnable_case_names:
        print()
        mode = "submitted" if args.submit else "planned"
        print(f"Summary: {mode}=0, skipped={skipped}, run_script={paths.run_shock_batch_script}")
        return 0

    manifest_path = build_manifest_path(paths.shock_manifest_dir, runnable_case_names, for_submit=args.submit)
    command = build_sbatch_command(
        paths.repo_root,
        paths.run_shock_batch_script,
        extract_script,
        manifest_path,
        runnable_case_names,
        args,
    )
    printable = " ".join(command)

    if not args.submit:
        print(f"[dry-run] {printable}")
        print(f"Manifest: {manifest_path} (created on submit)")
        print(f"Batch contains {len(runnable_case_names)} case(s).")
        print()
        print(f"Summary: planned=1, skipped={skipped}, run_script={paths.run_shock_batch_script}")
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
    print(f"Summary: submitted=1, skipped={skipped}, run_script={paths.run_shock_batch_script}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
