from __future__ import annotations

import re
import subprocess


SBATCH_JOB_RE = re.compile(r"Submitted batch job\s+(\d+)")


def command_string(command: list[str]) -> str:
    return " ".join(str(part) for part in command)


def add_afterok_dependency(command: list[str], job_ids: list[str]) -> list[str]:
    clean_job_ids = [str(job_id).strip() for job_id in job_ids if str(job_id).strip()]
    if not clean_job_ids:
        return list(command)
    updated = list(command)
    updated[1:1] = ["--dependency", "afterok:" + ":".join(clean_job_ids)]
    return updated


def parse_sbatch_job_id(stdout: str) -> str:
    match = SBATCH_JOB_RE.search(stdout)
    if match is None:
        return ""
    return match.group(1)


def submit_sbatch(command: list[str]) -> tuple[str, str]:
    completed = subprocess.run(command, check=True, text=True, capture_output=True)
    stdout = completed.stdout.strip()
    return stdout, parse_sbatch_job_id(stdout)
