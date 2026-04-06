#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


CASE_NAME_RE = re.compile(r"^(m\d+(?:\.\d+)?)(?:_aoa\d+(?:p\d+)?|_(?:coarse|medium|fine))$")
REFINEMENT_SUFFIXES = ("_coarse", "_medium", "_fine")
MESH_LEVEL_ORDER = {"coarse": 0, "medium": 1, "fine": 2}


def format_aoa_token(value: Any) -> str:
    as_float = float(value)
    if as_float.is_integer():
        return str(int(as_float))
    return str(as_float).replace(".", "p")


def normalize_mach_tokens(values: list[str]) -> set[str]:
    return {str(value).strip().removeprefix("m") for value in values}


def normalize_strings(values: list[str]) -> set[str]:
    return {str(value).strip() for value in values}


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


def prompt_yes_no(prompt: str, *, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{prompt} {suffix}: ").strip().lower()
    if not answer:
        return default
    if answer in {"y", "yes"}:
        return True
    if answer in {"n", "no"}:
        return False
    print("Please answer y or n.")
    return prompt_yes_no(prompt, default=default)


def prompt_with_default(prompt: str, default: str) -> str:
    answer = input(f"{prompt} [{default}]: ").strip()
    return answer or default


def mach_sort_key(mach_label: str) -> float:
    try:
        return float(mach_label.removeprefix("m"))
    except ValueError:
        return float("inf")


def case_spec_sort_key(spec: dict[str, Any]) -> tuple[object, ...]:
    aoa_value = float(spec.get("aoa_value", 0.0))
    mesh_level = str(spec.get("mesh_level", ""))
    return (
        str(spec.get("study", "")),
        mach_sort_key(f"m{spec.get('mach_token', '')}"),
        aoa_value,
        MESH_LEVEL_ORDER.get(mesh_level, 99),
        str(spec.get("case_name", "")),
    )


def format_study_label(study_name: str) -> str:
    return study_name.replace("_", " ").title()


def choose_managed_case_specs_interactively(
    case_specs: list[dict[str, Any]],
    *,
    action_label: str = "work with",
    custom_example: str = "m6_aoa15",
) -> list[dict[str, Any]]:
    if not case_specs:
        print("No managed cases are available.")
        return []

    sorted_specs = sorted(case_specs, key=case_spec_sort_key)

    grouped_by_study: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for spec in sorted_specs:
        study_name = str(spec["study"])
        mach_label = f"m{spec['mach_token']}"
        grouped_by_study.setdefault(study_name, {}).setdefault(mach_label, []).append(spec)

    menu_items: list[tuple[str, list[dict[str, Any]]]] = []
    print(f"\nSelect case group to {action_label}:\n")

    for study_name in sorted(grouped_by_study.keys()):
        print(f"  -- {format_study_label(study_name)} " + "─" * 24)
        study_specs: list[dict[str, Any]] = []

        for mach_label in sorted(grouped_by_study[study_name].keys(), key=mach_sort_key):
            mach_specs = grouped_by_study[study_name][mach_label]
            study_specs.extend(mach_specs)
            case_names = ", ".join(str(spec["case_name"]) for spec in mach_specs)
            label = f"{format_study_label(study_name)}: {mach_label.upper()} cases ({case_names})"
            print(f"  {len(menu_items)+1:2}) {label}")
            menu_items.append((label, mach_specs))

        if len(study_specs) > 1:
            label = f"All {format_study_label(study_name)} cases"
            print(f"  {len(menu_items)+1:2}) {label}")
            menu_items.append((label, study_specs))

        print()

    print("  -- Bulk " + "─" * 32)
    high_aoa_specs = [spec for spec in sorted_specs if float(spec.get("aoa_value", 0.0)) >= 40.0]
    if high_aoa_specs:
        label = "High AoA cases (>= 40 deg)"
        print(f"  {len(menu_items)+1:2}) {label}")
        menu_items.append((label, high_aoa_specs))

    label = "Everything"
    print(f"  {len(menu_items)+1:2}) {label}")
    menu_items.append((label, sorted_specs))

    label = "Custom case names"
    print(f"  {len(menu_items)+1:2}) {label}")
    menu_items.append(("CUSTOM", []))

    print("\n  q) Quit\n")
    choice = input(f"Selection [1-{len(menu_items)}/q]: ").strip().lower()
    if choice == "q":
        print("Bye!")
        return []

    try:
        index = int(choice) - 1
        assert 0 <= index < len(menu_items)
    except (ValueError, AssertionError):
        print("Invalid choice.")
        return []

    label, selected_specs = menu_items[index]
    if label == "CUSTOM":
        raw = input(f"Enter case names (comma separated, e.g. {custom_example}): ").strip()
        requested = [part.strip() for part in raw.split(",") if part.strip()]
        return filter_case_specs(sorted_specs, requested, [], [], [], [])

    return list(selected_specs)


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
        elif len(path.parts) >= 2 and path.parts[:2] == ("data", "cases"):
            candidates.append(cases_dir / Path(*path.parts[2:]))
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
