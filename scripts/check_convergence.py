#!/usr/bin/env python3
from __future__ import annotations

import csv
import math
import re
import sys
from pathlib import Path

from case_selection import choose_postprocess_cases_interactively, prompt_with_default
from layout import choose_study_paths_interactively


CASE_NAME_RE = re.compile(r"^m\d+(?:\.\d+)?(?:_aoa\d+(?:p\d+)?|_(?:coarse|medium|fine))$")


def is_case_dir(path: Path) -> bool:
    return path.is_dir() and CASE_NAME_RE.match(path.name) is not None


def find_case_dirs(root: Path, requested: list[str]) -> list[Path]:
    if requested:
        return [root / name for name in requested]
    if not root.exists():
        return []
    return sorted(path for path in root.iterdir() if is_case_dir(path))


def read_last_row(history_path: Path) -> tuple[list[str], list[str]] | None:
    with history_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return None

        last_row: list[str] | None = None
        for row in reader:
            if row:
                last_row = row

    if last_row is None:
        return None
    return header, last_row


def main() -> int:
    paths = choose_study_paths_interactively()
    threshold_text = prompt_with_default("Residual threshold", "1e-5")
    try:
        threshold = float(threshold_text)
    except ValueError as exc:
        raise SystemExit(f"Invalid threshold: {threshold_text}") from exc

    root = paths.cases_dir
    selected_cases = choose_postprocess_cases_interactively(root, "history.csv")
    if not selected_cases:
        return 0

    threshold_log10 = math.log10(threshold)
    case_dirs = find_case_dirs(root, selected_cases)

    failures = 0
    for case_dir in case_dirs:
        history_path = case_dir / "history.csv"
        if not history_path.exists():
            print(f"{case_dir.name}: MISSING history.csv")
            failures += 1
            continue

        parsed = read_last_row(history_path)
        if parsed is None:
            print(f"{case_dir.name}: no data")
            failures += 1
            continue

        header, last_row = parsed
        residuals: list[tuple[str, float]] = []
        for name, value in zip(header, last_row):
            clean_name = name.strip().strip('"')
            if clean_name.startswith("rms["):
                residuals.append((clean_name, float(value)))

        failed = [(name, value) for name, value in residuals if value > threshold_log10]

        if failed:
            failures += 1
            failed_str = ", ".join(f"{name}={value:.3f}" for name, value in failed)
            print(f"{case_dir.name}: FAIL ({failed_str})")
        else:
            print(f"{case_dir.name}: PASS ({len(residuals)} residuals <= {threshold:g})")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
