#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hypersonics_cfd.cases import filter_case_specs
from hypersonics_cfd.study import get_study_paths

from .setup import load_case_setup


STEPS = ("solver", "yplus", "mirror", "slices", "shock")
LOG_TAIL_BYTES = 256_000


def complete_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def fresh_outputs(input_path: Path, output_paths: list[Path]) -> bool:
    if not complete_file(input_path):
        return False
    input_mtime = input_path.stat().st_mtime
    return all(complete_file(path) and path.stat().st_mtime >= input_mtime for path in output_paths)


def parse_case_names(raw_cases: str) -> list[str]:
    return [part.strip() for part in raw_cases.replace(",", " ").split() if part.strip()]


def solver_complete(case_dir: Path) -> bool:
    return complete_file(case_dir / "history.csv") and complete_file(case_dir / "flow.vtu")


def solver_partial(case_dir: Path) -> bool:
    return any(complete_file(case_dir / name) for name in ("history.csv", "flow.vtu", "surface_flow.vtu"))


def latest_file(paths: list[Path]) -> Path | None:
    existing = [path for path in paths if path.is_file()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def read_tail(path: Path, max_bytes: int = LOG_TAIL_BYTES) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
        return handle.read().decode("utf-8", errors="replace")


def latest_solver_log_status(case_dir: Path) -> str:
    log_dir = case_dir / "logs" / "solver"
    latest = latest_file(list(log_dir.glob("solver_*.out")) + list(log_dir.glob("solver_*.err")))
    if latest is None:
        return ""

    job_id = latest.stem.split("_")[-1]
    text_parts = []
    for suffix in ("out", "err"):
        path = log_dir / f"solver_{job_id}.{suffix}"
        if path.is_file():
            text_parts.append(read_tail(path))
    text = "\n".join(text_parts)

    if "DUE TO TIME LIMIT" in text or "Reason=TimeLimit" in text:
        return "time_limit"
    if "NonZeroExitCode" in text:
        return "failed"
    if "Exit Success (SU2_CFD)" in text or "All convergence criteria satisfied" in text:
        return "success"
    return ""


def mirror_complete(case_dir: Path) -> bool:
    return complete_file(case_dir / "flow_full.vtu")


def yplus_complete(case_dir: Path) -> bool:
    return complete_file(case_dir / "orion_yplus.vtp") and complete_file(
        case_dir / "yplus_summary.csv"
    )


def slices_complete(case_dir: Path) -> bool:
    return complete_file(case_dir / "flow_slice_xy.vtp") and complete_file(case_dir / "flow_slice_xz.vtp")


def shock_complete(case_dir: Path) -> bool:
    return complete_file(case_dir / "shock_surface.csv") and complete_file(case_dir / "shock_surface.vtp")


def output_status(case_dir: Path, step: str) -> str:
    if step == "solver":
        log_status = latest_solver_log_status(case_dir)
        if log_status == "time_limit":
            return "partial:time_limit" if solver_partial(case_dir) else "failed:time_limit"
        if log_status == "failed":
            return "partial:failed" if solver_partial(case_dir) else "failed"
        if solver_complete(case_dir):
            return "done"
        if solver_partial(case_dir):
            return "partial"
        return "missing"
    if step == "yplus":
        if not yplus_complete(case_dir):
            return "missing"
        input_path = latest_file(
            [case_dir / "restart_flow.dat", case_dir / "surface_flow.vtu"]
        )
        if input_path is None:
            return "done"
        return (
            "done"
            if fresh_outputs(
                input_path,
                [case_dir / "orion_yplus.vtp", case_dir / "yplus_summary.csv"],
            )
            else "stale"
        )
    if step == "mirror":
        if not mirror_complete(case_dir):
            return "missing"
        flow_path = case_dir / "flow.vtu"
        full_flow_path = case_dir / "flow_full.vtu"
        return "stale" if complete_file(flow_path) and full_flow_path.stat().st_mtime < flow_path.stat().st_mtime else "done"
    if step == "slices":
        if not slices_complete(case_dir):
            return "missing"
        return (
            "done"
            if fresh_outputs(case_dir / "flow_full.vtu", [case_dir / "flow_slice_xy.vtp", case_dir / "flow_slice_xz.vtp"])
            else "stale"
        )
    if step == "shock":
        if not shock_complete(case_dir):
            return "missing"
        return (
            "done"
            if fresh_outputs(case_dir / "flow_full.vtu", [case_dir / "shock_surface.csv", case_dir / "shock_surface.vtp"])
            else "stale"
        )
    raise ValueError(f"unknown step: {step}")


def parse_job_name(job_name: str, case_names: set[str]) -> tuple[str, str] | None:
    for step in ("yplus", "mirror", "slices", "shock"):
        prefix = f"{step}_"
        if job_name.startswith(prefix):
            case_name = job_name[len(prefix):]
            if case_name in case_names:
                return case_name, step
    if job_name in case_names:
        return job_name, "solver"
    return None


def read_squeue(case_names: set[str]) -> dict[tuple[str, str], str]:
    if shutil.which("squeue") is None:
        return {}

    user = os.environ.get("USER", "")
    command = ["squeue", "-h", "-o", "%i|%j|%T|%M|%L|%R"]
    if user:
        command[2:2] = ["-u", user]

    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    if completed.returncode != 0:
        return {}

    jobs: dict[tuple[str, str], str] = {}
    for line in completed.stdout.splitlines():
        parts = line.split("|", 5)
        if len(parts) != 6:
            continue
        job_id, job_name, state, elapsed, remaining, reason = parts
        parsed = parse_job_name(job_name.strip(), case_names)
        if parsed is None:
            continue
        label = f"{state.lower()}:{job_id.strip()}"
        clean_reason = reason.strip()
        if clean_reason:
            if clean_reason.startswith("(") and clean_reason.endswith(")"):
                label += clean_reason
            else:
                label += f"({clean_reason})"
        elif elapsed.strip():
            label += f"({elapsed.strip()})"
        jobs[parsed] = label
    return jobs


def read_latest_timings(case_dir: Path) -> dict[str, str]:
    path = case_dir / "logs" / "workflow_timings.csv"
    if not path.exists():
        return {}

    latest: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            step = str(row.get("step", "")).strip()
            if step not in STEPS:
                continue
            elapsed = str(row.get("elapsed_hms", "")).strip()
            status = str(row.get("status", "")).strip()
            latest[step] = f"{elapsed}/{status}" if elapsed and status else elapsed or status
    return latest


def format_timings(timings: dict[str, str]) -> str:
    parts = [f"{step}={timings[step]}" for step in STEPS if timings.get(step)]
    return ", ".join(parts) if parts else "-"


def display_status(case_dir: Path, step: str, jobs: dict[tuple[str, str], str], case_name: str) -> str:
    if (case_name, step) in jobs:
        return jobs[(case_name, step)]
    return output_status(case_dir, step)


def print_table(rows: list[dict[str, str]]) -> None:
    if not rows:
        print("No cases selected.")
        return

    columns = ["case", "mesh", "solver", "yplus", "mirror", "slices", "shock", "timings"]
    widths = {
        column: max(len(column), *(len(row[column]) for row in rows))
        for column in columns
    }
    header = "  ".join(column.ljust(widths[column]) for column in columns)
    print(header)
    print("  ".join("-" * widths[column] for column in columns))
    for row in rows:
        print("  ".join(row[column].ljust(widths[column]) for column in columns))


def build_rows(specs: list[dict[str, Any]], jobs: dict[tuple[str, str], str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for spec in specs:
        case_name = str(spec["case_name"])
        alias_of = str(spec.get("alias_of", ""))
        mesh = str(spec["mesh_level"])
        if alias_of:
            rows.append(
                {
                    "case": case_name,
                    "mesh": mesh,
                    "solver": f"alias->{alias_of}",
                    "yplus": "alias",
                    "mirror": "alias",
                    "slices": "alias",
                    "shock": "alias",
                    "timings": "-",
                }
            )
            continue

        case_dir = Path(spec["case_path"]) if "case_path" in spec else None
        if case_dir is None:
            raise KeyError("case_path missing from status spec")
        timings = read_latest_timings(case_dir)
        rows.append(
            {
                "case": case_name,
                "mesh": mesh,
                "solver": display_status(case_dir, "solver", jobs, case_name),
                "yplus": display_status(case_dir, "yplus", jobs, case_name),
                "mirror": display_status(case_dir, "mirror", jobs, case_name),
                "slices": display_status(case_dir, "slices", jobs, case_name),
                "shock": display_status(case_dir, "shock", jobs, case_name),
                "timings": format_timings(timings),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Show managed workflow status by case.")
    parser.add_argument("--study", default="orion")
    parser.add_argument("--cases", default="", help="Comma/space separated managed case names.")
    parser.add_argument("--no-squeue", action="store_true", help="Do not query SLURM.")
    args = parser.parse_args()

    paths = get_study_paths(args.study)
    _, _, specs = load_case_setup(paths)
    for spec in specs:
        spec["case_path"] = paths.case_path(str(spec["case_name"]))

    requested_cases = parse_case_names(args.cases)
    if requested_cases:
        specs = filter_case_specs(specs, requested_cases, [], [], [], [])

    case_names = {str(spec["case_name"]) for spec in specs}
    jobs = {} if args.no_squeue else read_squeue(case_names)
    rows = build_rows(specs, jobs)
    print_table(rows)
    return 0
