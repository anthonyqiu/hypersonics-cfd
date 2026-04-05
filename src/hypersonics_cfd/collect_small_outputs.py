#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from .artifacts import collect_small_outputs
from .layout import get_study_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy small derived study outputs into a portable bundle for local sync."
    )
    parser.add_argument(
        "--study",
        default="orion",
        help='Study slug under studies/. Defaults to "orion".',
    )
    parser.add_argument(
        "--dest",
        default="",
        help="Optional output directory. Defaults to studies/<study>/data/exports/small_outputs.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete the destination bundle before copying files.",
    )
    parser.add_argument(
        "cases",
        nargs="*",
        help="Optional case names. If omitted, all recognized study cases are scanned.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = get_study_paths(args.study)
    destination = Path(args.dest).expanduser() if args.dest else None
    result = collect_small_outputs(
        paths,
        args.cases,
        destination=destination,
        clean=args.clean,
    )
    print(f"Study: {paths.study_name}")
    print(f"Cases scanned: {result['case_count']}")
    print(f"Files copied: {result['file_count']}")
    print(f"Bundle: {result['destination']}")
    print(f"Manifest: {result['manifest_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
