#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "cases"
CASE_NAME_RE = re.compile(r"^m\d+(?:\.\d+)?(?:_aoa\d+(?:p\d+)?|_(?:coarse|medium|fine))$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether each residual in history.csv is at or below a target."
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=1e-5,
        help="Residual magnitude target. Defaults to 1e-5.",
    )
    parser.add_argument(
        "--root",
        default=str(CASES_DIR),
        help="Root directory containing case folders.",
    )
    parser.add_argument(
        "cases",
        nargs="*",
        help="Optional case names. If omitted, only recognized case folders are checked.",
    )
    return parser.parse_args()


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
    args = parse_args()
    root = Path(args.root)
    threshold_log10 = math.log10(args.threshold)
    case_dirs = find_case_dirs(root, args.cases)
    explicit_cases = bool(args.cases)

    if not case_dirs:
        print(f"No case folders found under {root}")
        return 1

    failures = 0
    for case_dir in case_dirs:
        history_path = case_dir / "history.csv"
        if not history_path.exists():
            if explicit_cases:
                print(f"{case_dir.name}: MISSING history.csv")
                failures += 1
            else:
                print(f"{case_dir.name}: SKIP (no history.csv)")
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
            print(f"{case_dir.name}: PASS ({len(residuals)} residuals <= {args.threshold:g})")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
