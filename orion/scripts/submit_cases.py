#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from case_cli import add_managed_case_filter_args, filter_case_specs
from setup_cases import CASES_DIR, GENERATED_CONFIG_DIR, ROOT, apply_alias_map, describe_alias, expand_cases, load_toml, stage_case


CONFIG_MATRIX = ROOT / "config" / "cases.toml"
CONFIG_TEMPLATE = ROOT / "config" / "base.cfg"
RUN_SCRIPT = ROOT / "config" / "run.sh"
RESULT_PATTERNS = (
    "history.csv",
    "flow.vtu",
    "surface_flow.vtu",
    "shock.csv",
    "orion_*.out",
    "orion_*.err",
    "slurm-*.out",
)


class SubmissionAborted(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run or submit Orion cases using the shared batch script."
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Actually call sbatch. Without this flag the script only prints commands.",
    )
    parser.add_argument(
        "--resubmit",
        action="store_true",
        help="Allow submitting non-restart cases that already have solver outputs.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Target all managed cases. Requires extra confirmation together with --submit.",
    )
    parser.add_argument(
        "--confirm-all",
        default="",
        help="Must be exactly SUBMIT ALL when using --all --submit.",
    )
    add_managed_case_filter_args(parser)
    return parser.parse_args()


def has_nonrestart_outputs(case_dir: Path) -> bool:
    for pattern in RESULT_PATTERNS:
        if any(case_dir.glob(pattern)):
            return True
    return False


def build_sbatch_command(spec: dict[str, object], case_dir: Path) -> list[str]:
    generated_cfg = GENERATED_CONFIG_DIR / f"{spec['case_name']}.cfg"
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
        "orion_%j.out",
        "--error",
        "orion_%j.err",
        "--chdir",
        str(case_dir),
        str(RUN_SCRIPT),
        str(generated_cfg),
    ]


def resolve_alias_targets(
    selected_specs: list[dict[str, object]], all_specs: list[dict[str, object]]
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


def interactive_select(case_specs: list[dict[str, object]]) -> list[dict[str, object]]:
    print("\nSelect cases to target:\n")
    print("  1) AoA study: Mach 3 cases")
    print("  2) AoA study: Mach 6 cases")
    print("  3) AoA study: Mach 9 cases")
    print("  4) AoA study: high AoA cases (40, 50, 60)")
    print("  5) Refinement study: Mach 6 cases")
    print("  6) Refinement study: Mach 9 cases")
    print("  7) All refinement cases")
    print("  8) Custom case names")
    print("  9) All managed cases")
    print("\n  q) Quit\n")

    choice = input("Selection: ").strip().lower()
    if choice == "q":
        raise SubmissionAborted("Submission cancelled.")

    if choice == "1":
        return [spec for spec in case_specs if spec["study"] == "aoa" and spec["mach_token"] == "3"]
    if choice == "2":
        return [spec for spec in case_specs if spec["study"] == "aoa" and spec["mach_token"] == "6"]
    if choice == "3":
        return [spec for spec in case_specs if spec["study"] == "aoa" and spec["mach_token"] == "9"]
    if choice == "4":
        return [spec for spec in case_specs if spec["study"] == "aoa" and spec["aoa"] in {"40", "50", "60"}]
    if choice == "5":
        return [spec for spec in case_specs if spec["study"] == "refinement" and spec["mach_token"] == "6"]
    if choice == "6":
        return [spec for spec in case_specs if spec["study"] == "refinement" and spec["mach_token"] == "9"]
    if choice == "7":
        return [spec for spec in case_specs if spec["study"] == "refinement"]
    if choice == "8":
        raw = input("Case names (comma separated): ").strip()
        requested = [part.strip() for part in raw.split(",") if part.strip()]
        return filter_case_specs(case_specs, requested, [], [], [], [])
    if choice == "9":
        confirm = input('Type SUBMIT ALL to continue: ').strip()
        if confirm != "SUBMIT ALL":
            raise SubmissionAborted("Submission cancelled.")
        return case_specs

    raise SubmissionAborted("Invalid selection.")


def select_cases(args: argparse.Namespace, case_specs: list[dict[str, object]]) -> list[dict[str, object]]:
    explicit_filters = bool(args.cases or args.study or args.mach or args.aoa or args.mesh_level)

    if args.all and explicit_filters:
        raise SystemExit("Use either --all or explicit filters, not both.")

    if args.all:
        if args.submit and args.confirm_all != "SUBMIT ALL":
            raise SystemExit('Submitting all cases requires --confirm-all "SUBMIT ALL".')
        return case_specs

    if explicit_filters:
        return filter_case_specs(
            case_specs,
            args.cases,
            args.study,
            args.mach,
            args.aoa,
            args.mesh_level,
        )

    if args.submit:
        if not sys.stdin.isatty():
            raise SystemExit("Submitting without filters requires an interactive terminal or --all.")
        return interactive_select(case_specs)

    return case_specs


def main() -> int:
    args = parse_args()
    matrix = load_toml(CONFIG_MATRIX)
    template_text = CONFIG_TEMPLATE.read_text(encoding="utf-8")
    all_case_specs = expand_cases(matrix)
    all_case_specs = apply_alias_map(all_case_specs, matrix, template_text)
    case_specs = all_case_specs

    try:
        case_specs = select_cases(args, case_specs)
    except SubmissionAborted as exc:
        print(exc)
        return 1

    case_specs = resolve_alias_targets(case_specs, all_case_specs)

    if args.submit and shutil.which("sbatch") is None:
        raise SystemExit("sbatch was not found in PATH. Re-run without --submit for a dry run.")

    planned = skipped = 0
    for spec in case_specs:
        case_dir = CASES_DIR / spec["case_name"]
        restart_file = case_dir / "restart_flow.dat"

        if spec["restart_sol"] == "YES":
            if not restart_file.exists():
                print(f"{spec['case_name']}: skipped, RESTART_SOL=YES but {restart_file.name} is missing")
                skipped += 1
                continue
        elif has_nonrestart_outputs(case_dir) and not args.resubmit:
            print(f"{spec['case_name']}: skipped, solver outputs already exist in {case_dir}")
            skipped += 1
            continue

        command = build_sbatch_command(spec, case_dir)
        printable = " ".join(command)

        if not args.submit:
            print(f"[dry-run] {printable}")
            planned += 1
            continue

        stage_case(spec, template_text)
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
    mode = "submitted" if args.submit else "planned"
    print(f"Summary: {mode}={planned}, skipped={skipped}, run_script={RUN_SCRIPT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
