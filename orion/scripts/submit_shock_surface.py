#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

from case_cli import deduplicate_case_names, choose_postprocess_cases_interactively, resolve_case_path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
CASES_DIR = ROOT / "cases"
CONFIG_MATRIX = ROOT / "config" / "cases.toml"
RUN_SCRIPT = ROOT / "config" / "run_extract_shock_surface.sh"
EXTRACT_SCRIPT = ROOT / "scripts" / "extract_shock_surface.py"
MANIFEST_DIR = ROOT / "config" / "generated" / "shock_manifests"
FLOW_FILENAME = "flow.vtu"
SHOCK_OUTPUTS = ("shock_surface.vtp", "shock_surface.csv")
DEFAULT_MEM = "0"


def load_submit_defaults() -> tuple[str, str]:
    account = "rrg-jphickey"
    time_limit = "18:00:00"
    if not CONFIG_MATRIX.exists():
        return account, time_limit

    with CONFIG_MATRIX.open("rb") as handle:
        matrix = tomllib.load(handle)

    defaults = dict(matrix.get("defaults", {}))
    if defaults.get("job_account"):
        account = str(defaults["job_account"])
    if defaults.get("job_time"):
        time_limit = str(defaults["job_time"])
    return account, time_limit


DEFAULT_ACCOUNT, DEFAULT_TIME = load_submit_defaults()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run or submit overnight shock-surface extraction jobs."
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
        default=DEFAULT_TIME,
        help=f'SLURM walltime for each extraction job. Defaults to "{DEFAULT_TIME}".',
    )
    parser.add_argument(
        "--account",
        default=DEFAULT_ACCOUNT,
        help=f'SLURM account. Defaults to "{DEFAULT_ACCOUNT}".',
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
        help=f'SLURM memory request. Defaults to "{DEFAULT_MEM}" to match Trillium/all-node memory scheduling.',
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable to use inside the batch job. Defaults to the current interpreter.",
    )
    return parser.parse_args()


def has_completed_outputs(case_path: Path) -> bool:
    return all((case_path / name).exists() for name in SHOCK_OUTPUTS)

def build_job_name(case_paths: list[Path]) -> str:
    if len(case_paths) == 1:
        return f"shock_{case_paths[0].name}"
    return f"shock_batch_{len(case_paths)}"


def build_manifest_path(case_paths: list[Path], *, for_submit: bool) -> Path:
    job_name = build_job_name(case_paths)
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S") if for_submit else "preview"
    return MANIFEST_DIR / f"{job_name}_{suffix}.txt"


def write_case_manifest(manifest_path: Path, case_paths: list[Path]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [str(case_path) for case_path in case_paths]
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_sbatch_command(manifest_path: Path, case_paths: list[Path], args: argparse.Namespace) -> list[str]:
    return [
        "sbatch",
        "--export=NONE",
        "--get-user-env=L",
        "--job-name",
        build_job_name(case_paths),
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
        str(ROOT),
        str(RUN_SCRIPT),
        str(args.python),
        str(EXTRACT_SCRIPT),
        str(manifest_path),
    ]


def main() -> int:
    args = parse_args()

    if args.cpus_per_task <= 0:
        raise SystemExit("--cpus-per-task must be positive.")

    python_exe = Path(args.python).expanduser()
    if not python_exe.exists():
        raise SystemExit(f"Python executable not found: {python_exe}")
    args.python = str(python_exe)

    if args.submit and shutil.which("sbatch") is None:
        raise SystemExit("sbatch was not found in PATH. Re-run without --submit for a dry run.")

    print("\n╔══════════════════════════════════════════════╗")
    print("║   Shock Surface SLURM Submitter             ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"Run script: {RUN_SCRIPT}")
    print(f"Python: {args.python}")
    print(
        f"Resources: nodes=1, ntasks-per-node=1, cpus-per-task={args.cpus_per_task}, mem={args.mem}, "
        f"time={args.time}, account={args.account}"
    )

    requested_cases = list(args.case_flags) + list(args.cases)
    cases = requested_cases or choose_postprocess_cases_interactively(CASES_DIR, FLOW_FILENAME)
    cases = deduplicate_case_names(ROOT, CASES_DIR, cases)
    if not cases:
        return 0

    print("Extractor settings: using values defined inside extract_shock_surface.py")

    runnable_case_paths: list[Path] = []
    skipped = 0
    for case in cases:
        case_path = resolve_case_path(ROOT, CASES_DIR, case)
        flow_path = case_path / FLOW_FILENAME
        if not flow_path.exists():
            print(f"{case}: skipped, missing {FLOW_FILENAME}")
            skipped += 1
            continue

        if has_completed_outputs(case_path) and not args.rerun:
            print(f"{case_path.name}: skipped, shock_surface outputs already exist")
            skipped += 1
            continue

        runnable_case_paths.append(case_path)

    if not runnable_case_paths:
        print()
        mode = "submitted" if args.submit else "planned"
        print(f"Summary: {mode}=0, skipped={skipped}, run_script={RUN_SCRIPT}")
        return 0

    manifest_path = build_manifest_path(runnable_case_paths, for_submit=args.submit)
    command = build_sbatch_command(manifest_path, runnable_case_paths, args)
    printable = " ".join(command)

    if not args.submit:
        print(f"[dry-run] {printable}")
        print(f"Manifest: {manifest_path} (created on submit)")
        print(f"Batch contains {len(runnable_case_paths)} case(s).")
        print()
        print(f"Summary: planned=1, skipped={skipped}, run_script={RUN_SCRIPT}")
        return 0

    write_case_manifest(manifest_path, runnable_case_paths)
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

    print(f"{build_job_name(runnable_case_paths)}: {completed.stdout.strip()}")

    print()
    print(f"Summary: submitted=1, skipped={skipped}, run_script={RUN_SCRIPT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
