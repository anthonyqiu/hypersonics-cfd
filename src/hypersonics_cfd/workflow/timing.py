#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import fcntl
import os
from datetime import datetime, timezone
from pathlib import Path


FIELDNAMES = [
    "timestamp_utc",
    "study",
    "case",
    "step",
    "status",
    "elapsed_seconds",
    "elapsed_hms",
    "slurm_job_id",
    "slurm_job_name",
    "slurm_nodelist",
    "slurm_ntasks",
    "slurm_cpus_per_task",
    "note",
]


def elapsed_hms(elapsed_seconds: float) -> str:
    total = max(0, int(round(elapsed_seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def find_study_root(case_dir: Path) -> Path | None:
    for candidate in [case_dir, *case_dir.parents]:
        if (candidate / "study.toml").exists():
            return candidate
    return None


def append_locked(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        needs_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
            if needs_header:
                writer.writeheader()
            writer.writerow(row)
        fcntl.flock(lock_handle, fcntl.LOCK_UN)


def build_row(args: argparse.Namespace, study: str, case_name: str) -> dict[str, str]:
    elapsed = float(args.elapsed_seconds)
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "study": study,
        "case": case_name,
        "step": args.step,
        "status": args.status,
        "elapsed_seconds": f"{elapsed:.3f}",
        "elapsed_hms": elapsed_hms(elapsed),
        "slurm_job_id": os.environ.get("SLURM_JOB_ID", ""),
        "slurm_job_name": os.environ.get("SLURM_JOB_NAME", ""),
        "slurm_nodelist": os.environ.get("SLURM_NODELIST", ""),
        "slurm_ntasks": os.environ.get("SLURM_NTASKS", ""),
        "slurm_cpus_per_task": os.environ.get("SLURM_CPUS_PER_TASK", ""),
        "note": args.note,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Append one workflow timing record.")
    parser.add_argument("--case-dir", type=Path, required=True, help="Case directory.")
    parser.add_argument("--step", required=True, help="Workflow step name.")
    parser.add_argument("--status", required=True, choices=["success", "failure", "skipped"])
    parser.add_argument("--elapsed-seconds", type=float, required=True)
    parser.add_argument("--study", default="", help="Study name. Inferred when omitted.")
    parser.add_argument("--case", default="", help="Case name. Inferred from case directory when omitted.")
    parser.add_argument("--study-root", type=Path, default=None, help="Study root. Inferred when omitted.")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    case_dir = args.case_dir.resolve(strict=False)
    study_root = args.study_root.resolve(strict=False) if args.study_root else find_study_root(case_dir)
    study = args.study or (study_root.name if study_root else "")
    case_name = args.case or case_dir.name
    row = build_row(args, study, case_name)

    append_locked(case_dir / "logs" / "workflow_timings.csv", row)
    if study_root is not None:
        append_locked(study_root / "data" / "workflow_timings.csv", row)

    return 0
