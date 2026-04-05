#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any


CASE_NAME_RE = re.compile(r"^(m\d+(?:\.\d+)?)(?:_aoa\d+(?:p\d+)?|_(?:coarse|medium|fine))$")
REFINEMENT_SUFFIXES = ("_coarse", "_medium", "_fine")


def format_aoa_token(value: Any) -> str:
    as_float = float(value)
    if as_float.is_integer():
        return str(int(as_float))
    return str(as_float).replace(".", "p")


def normalize_mach_tokens(values: list[str]) -> set[str]:
    return {str(value).strip().removeprefix("m") for value in values}


def normalize_strings(values: list[str]) -> set[str]:
    return {str(value).strip() for value in values}


def add_managed_case_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        default=[],
        help="Select an exact case name. Repeat for multiple cases.",
    )
    parser.add_argument(
        "--study",
        action="append",
        default=[],
        help='Filter by study name, for example "aoa" or "refinement".',
    )
    parser.add_argument(
        "--mach",
        action="append",
        default=[],
        help="Filter by Mach family, for example 3, 6, or 9.",
    )
    parser.add_argument(
        "--aoa",
        action="append",
        default=[],
        help="Filter by angle of attack, for example 32 or 60.",
    )
    parser.add_argument(
        "--mesh-level",
        action="append",
        default=[],
        help='Filter by mesh level, for example "coarse", "medium", or "fine".',
    )


def filter_case_specs(
    case_specs: list[dict[str, Any]],
    requested_cases: list[str],
    study_filters: list[str],
    mach_filters: list[str],
    aoa_filters: list[str],
    mesh_level_filters: list[str],
) -> list[dict[str, Any]]:
    selected = case_specs

    if requested_cases:
        requested_set = set(requested_cases)
        selected = [spec for spec in selected if spec["case_name"] in requested_set]
        found_set = {spec["case_name"] for spec in selected}
        missing = sorted(requested_set - found_set)
        if missing:
            raise SystemExit(f"unknown case name(s): {', '.join(missing)}")

    if study_filters:
        allowed = normalize_strings(study_filters)
        selected = [spec for spec in selected if spec["study"] in allowed]

    if mach_filters:
        allowed = normalize_mach_tokens(mach_filters)
        selected = [spec for spec in selected if spec["mach_token"] in allowed]

    if aoa_filters:
        allowed = {format_aoa_token(value) for value in aoa_filters}
        selected = [spec for spec in selected if spec["aoa"] in allowed]

    if mesh_level_filters:
        allowed = normalize_strings(mesh_level_filters)
        selected = [spec for spec in selected if spec["mesh_level"] in allowed]

    return selected


def resolve_case_path(root: Path, cases_dir: Path, case_dir: str) -> Path:
    path = Path(case_dir)
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(path)
        candidates.append(root / path)
        if path.parts and path.parts[0] == "cases":
            candidates.append(cases_dir / Path(*path.parts[1:]))
        else:
            candidates.append(cases_dir / path)

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.expanduser()
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate

    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "cases":
        return root / path
    return cases_dir / path


def deduplicate_case_names(root: Path, cases_dir: Path, case_names: list[str]) -> list[str]:
    deduped: list[str] = []
    seen_realpaths: set[Path] = set()
    for case_name in case_names:
        real_path = resolve_case_path(root, cases_dir, case_name).resolve(strict=False)
        if real_path in seen_realpaths:
            print(f"-> {case_name} [skip] same directory as {real_path.name}")
            continue
        seen_realpaths.add(real_path)
        deduped.append(case_name)
    return deduped


def mach_sort_key(mach_label: str) -> float:
    try:
        return float(mach_label.removeprefix("m"))
    except ValueError:
        return float("inf")


def discover_postprocess_cases(cases_dir: Path, required_filename: str) -> tuple[list[str], dict[str, list[str]]]:
    all_cases: list[str] = []
    mach_groups: dict[str, list[str]] = {}

    for path in sorted(cases_dir.glob("m*")):
        if not path.is_dir():
            continue
        if not (path / required_filename).exists():
            continue
        match = CASE_NAME_RE.match(path.name)
        if match is None:
            continue

        mach = match.group(1)
        all_cases.append(path.name)
        mach_groups.setdefault(mach, []).append(path.name)

    return all_cases, mach_groups


def choose_postprocess_cases_interactively(
    cases_dir: Path,
    required_filename: str,
    *,
    custom_example: str = "m6_aoa15",
) -> list[str]:
    all_cases, mach_groups = discover_postprocess_cases(cases_dir, required_filename)
    if not all_cases:
        print(f"No case folders with {required_filename} found under {cases_dir}.")
        return []

    menu_items: list[tuple[str, list[str]]] = []
    print("\nSelect case group:\n")

    for mach in sorted(mach_groups.keys(), key=mach_sort_key):
        cases = mach_groups[mach]
        aoa_cases = [case for case in cases if "_aoa" in case]
        refinement_cases = [case for case in cases if case.endswith(REFINEMENT_SUFFIXES)]

        print(f"  -- {mach.upper()} {'─' * max(1, 36 - len(mach))}")

        if aoa_cases:
            label = f"{mach.upper()} AoA cases ({', '.join(aoa_cases)})"
            print(f"  {len(menu_items)+1:2}) {label}")
            menu_items.append((label, aoa_cases))

        if refinement_cases:
            label = f"{mach.upper()} refinement cases ({', '.join(refinement_cases)})"
            print(f"  {len(menu_items)+1:2}) {label}")
            menu_items.append((label, refinement_cases))

        if aoa_cases and refinement_cases:
            label = f"All {mach.upper()} cases"
            print(f"  {len(menu_items)+1:2}) {label}")
            menu_items.append((label, cases))

        print()

    print("  -- Bulk " + "─" * 32)
    all_aoa_cases = [case for case in all_cases if "_aoa" in case]
    all_refinement_cases = [case for case in all_cases if case.endswith(REFINEMENT_SUFFIXES)]

    if all_aoa_cases:
        label = "All AoA cases"
        print(f"  {len(menu_items)+1:2}) {label}")
        menu_items.append((label, all_aoa_cases))

    if all_refinement_cases:
        label = "All refinement cases"
        print(f"  {len(menu_items)+1:2}) {label}")
        menu_items.append((label, all_refinement_cases))

    label = "Everything"
    print(f"  {len(menu_items)+1:2}) {label}")
    menu_items.append((label, all_cases))

    label = "Custom case name"
    print(f"  {len(menu_items)+1:2}) {label}")
    menu_items.append(("CUSTOM", []))

    print("\n   q) Quit\n")
    choice = input(f"Case group [1-{len(menu_items)}/q]: ").strip()
    if choice.lower() == "q":
        print("Bye!")
        return []

    try:
        index = int(choice) - 1
        assert 0 <= index < len(menu_items)
    except (ValueError, AssertionError):
        print("Invalid choice.")
        return []

    label, selected_cases = menu_items[index]
    if label == "CUSTOM":
        custom = input(f"Enter case folder name (e.g. {custom_example}): ").strip()
        selected_cases = [custom]
    return selected_cases
