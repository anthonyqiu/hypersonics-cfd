#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

from case_selection import add_managed_case_filter_args, filter_case_specs, format_aoa_token
from layout import StudyPaths, get_study_paths


PLACEHOLDER_RE = re.compile(r"{{\s*([A-Za-z0-9_]+)\s*}}")
OLD_CASE_LOCAL_LINKS = ("mesh.su2", "fine.su2", "medium.su2", "coarse.su2")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or stage generated configs and managed case links for a study."
    )
    parser.add_argument(
        "--campaign",
        default="orion",
        help='Study slug under studies/. Defaults to "orion".',
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write generated configs and update the selected case folders.",
    )
    add_managed_case_filter_args(parser, study_option="--experiment", study_dest="experiment")
    return parser.parse_args()


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_case_setup(paths: StudyPaths) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    matrix = load_toml(paths.study_file)
    template_text = paths.su2_template.read_text(encoding="utf-8")
    case_specs = expand_cases(paths, matrix)
    case_specs = apply_alias_map(case_specs, matrix, template_text)
    return matrix, template_text, case_specs


def flatten_named_tables(tree: dict[str, Any], prefix: str = "") -> dict[str, dict[str, Any]]:
    if not isinstance(tree, dict):
        raise TypeError(f"expected dict while flattening named tables, got {type(tree).__name__}")

    has_nested = any(isinstance(value, dict) for value in tree.values())
    has_scalar = any(not isinstance(value, dict) for value in tree.values())

    if prefix and has_scalar:
        return {prefix: dict(tree)}

    flattened: dict[str, dict[str, Any]] = {}
    for key, value in tree.items():
        if not isinstance(value, dict):
            raise TypeError(f"unexpected scalar entry {key!r} while flattening named tables")
        child_prefix = key if not prefix else f"{prefix}.{key}"
        flattened.update(flatten_named_tables(value, child_prefix))
    return flattened


def render_template(template_text: str, context: dict[str, Any]) -> str:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            missing.append(key)
            return match.group(0)
        return str(context[key])

    rendered = PLACEHOLDER_RE.sub(replace, template_text)
    if missing:
        missing_keys = ", ".join(sorted(set(missing)))
        raise KeyError(f"missing template values: {missing_keys}")
    return rendered


def template_placeholder_keys(template_text: str) -> list[str]:
    return sorted({match.group(1) for match in PLACEHOLDER_RE.finditer(template_text)})


def alias_diff_keys(alias_spec: dict[str, Any], target_spec: dict[str, Any], template_text: str) -> list[str]:
    differing: list[str] = []
    for key in template_placeholder_keys(template_text):
        if str(alias_spec.get(key, "")) != str(target_spec.get(key, "")):
            differing.append(key)
    return differing


def describe_alias(spec: dict[str, Any]) -> str:
    alias_of = str(spec.get("alias_of", ""))
    if not alias_of:
        return ""
    diff_keys = list(spec.get("alias_diff_keys", []))
    if not diff_keys:
        return alias_of
    shown = ",".join(diff_keys[:4])
    if len(diff_keys) > 4:
        shown += ",..."
    return f"{alias_of} [target config wins: {shown}]"


def apply_alias_map(
    case_specs: list[dict[str, Any]],
    matrix: dict[str, Any],
    template_text: str,
) -> list[dict[str, Any]]:
    aliases = {str(name): str(target) for name, target in dict(matrix.get("aliases", {})).items()}
    if not aliases:
        return case_specs

    spec_by_name = {str(spec["case_name"]): spec for spec in case_specs}
    for alias_name, target_name in aliases.items():
        if alias_name not in spec_by_name:
            raise ValueError(f"alias case {alias_name!r} was not generated")
        if target_name not in spec_by_name:
            raise ValueError(f"alias target {target_name!r} was not generated")
        if alias_name == target_name:
            raise ValueError(f"alias {alias_name!r} cannot target itself")

        alias_spec = spec_by_name[alias_name]
        target_spec = spec_by_name[target_name]
        alias_spec["alias_of"] = target_name
        alias_spec["alias_diff_keys"] = alias_diff_keys(alias_spec, target_spec, template_text)

    return case_specs


def format_yes_no(value: Any) -> str:
    if isinstance(value, bool):
        return "YES" if value else "NO"
    value_str = str(value).strip().upper()
    if value_str in {"YES", "NO"}:
        return value_str
    raise ValueError(f"expected YES/NO or boolean, got {value!r}")


def matches_override(rule: dict[str, Any], spec: dict[str, Any]) -> bool:
    match_cases = rule.get("match_cases")
    if match_cases and spec["case_name"] not in {str(value) for value in match_cases}:
        return False

    match_study = rule.get("match_study")
    if match_study and spec["study"] not in {str(value) for value in match_study}:
        return False

    match_mach = rule.get("match_mach")
    if match_mach and spec["mach_token"] not in {str(value).removeprefix("m") for value in match_mach}:
        return False

    match_mesh_level = rule.get("match_mesh_level")
    if match_mesh_level and spec["mesh_level"] not in {str(value) for value in match_mesh_level}:
        return False

    match_aoa = rule.get("match_aoa")
    if match_aoa:
        allowed = {float(value) for value in match_aoa}
        if spec["aoa_value"] not in allowed:
            return False

    match_aoa_min = rule.get("match_aoa_min")
    if match_aoa_min is not None and spec["aoa_value"] < float(match_aoa_min):
        return False

    match_aoa_max = rule.get("match_aoa_max")
    if match_aoa_max is not None and spec["aoa_value"] > float(match_aoa_max):
        return False

    return True


def apply_override_rules(base_spec: dict[str, Any], override_rules: list[dict[str, Any]]) -> dict[str, Any]:
    merged = dict(base_spec)
    for rule in override_rules:
        if not matches_override(rule, merged):
            continue
        for key, value in rule.items():
            if key == "name" or key.startswith("match_"):
                continue
            merged[key] = value
    return merged


def resolve_mesh_reference(paths: StudyPaths, mesh_value: str) -> str:
    raw = Path(str(mesh_value).strip())
    candidates: list[Path] = []

    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.extend(
            [
                paths.meshes_dir / raw,
                paths.meshes_dir / raw.name,
                paths.study_root / raw,
            ]
        )

    mesh_path = next((candidate for candidate in candidates if candidate.exists()), None)
    if mesh_path is None:
        mesh_path = candidates[1] if len(candidates) > 1 else candidates[0]

    return str(mesh_path.resolve(strict=False))


def case_runtime_value(case_dir: Path, stem: str) -> str:
    return str((case_dir / stem).resolve(strict=False))


def expand_cases(paths: StudyPaths, matrix: dict[str, Any]) -> list[dict[str, Any]]:
    defaults = dict(matrix["defaults"])
    profiles = flatten_named_tables(dict(matrix["profiles"]))
    meshes = dict(matrix["meshes"])
    studies = dict(matrix["generation"]["studies"])
    override_rules = list(matrix.get("overrides", []))

    case_specs: list[dict[str, Any]] = []
    seen_case_names: set[str] = set()

    for study_name, study in studies.items():
        pattern = str(study["case_name_pattern"])
        aoa_values = list(study.get("aoas", [study.get("aoa", 0)]))
        mesh_levels = list(study.get("mesh_levels", [study.get("mesh_level", "fine")]))

        for profile_name in study["mach_profiles"]:
            if profile_name not in profiles:
                available = ", ".join(sorted(profiles))
                raise KeyError(
                    f"unknown Mach profile {profile_name!r}. Available profiles: {available}"
                )
            profile = dict(profiles[profile_name])
            mach_token = profile_name.removeprefix("m")

            for aoa in aoa_values:
                aoa_token = format_aoa_token(aoa)
                for mesh_level in mesh_levels:
                    mesh_level = str(mesh_level)
                    if mesh_level not in meshes:
                        available = ", ".join(sorted(meshes))
                        raise KeyError(
                            f"mesh level {mesh_level!r} is not defined. Available mesh levels: {available}"
                        )

                    spec = dict(defaults)
                    spec.update(profile)
                    spec["study"] = study_name
                    spec["study_slug"] = paths.study_name
                    spec["aoa"] = aoa_token
                    spec["aoa_value"] = float(aoa)
                    spec["mach_token"] = mach_token
                    spec["mesh_level"] = mesh_level
                    spec["mesh_filename"] = resolve_mesh_reference(paths, str(meshes[mesh_level]))
                    spec["case_name"] = pattern.format(
                        mach=mach_token,
                        aoa=aoa_token,
                        mesh_level=mesh_level,
                        study=study_name,
                    )
                    spec = apply_override_rules(spec, override_rules)

                    case_dir = paths.case_path(str(spec["case_name"]))
                    spec["solution_filename"] = str((case_dir / "restart_flow.dat").resolve(strict=False))
                    spec["solution_adj_filename"] = case_runtime_value(case_dir, "solution_adj")
                    spec["conv_filename"] = case_runtime_value(case_dir, "history")
                    spec["restart_filename"] = case_runtime_value(case_dir, "restart_flow")
                    spec["restart_adj_filename"] = case_runtime_value(case_dir, "restart_adj")
                    spec["volume_filename"] = case_runtime_value(case_dir, "flow")
                    spec["volume_adj_filename"] = case_runtime_value(case_dir, "adjoint")
                    spec["grad_objfunc_filename"] = case_runtime_value(case_dir, "of_grad.dat")
                    spec["surface_filename"] = case_runtime_value(case_dir, "surface_flow")
                    spec["surface_adj_filename"] = case_runtime_value(case_dir, "surface_adjoint")

                    spec["job_name"] = str(spec["case_name"])
                    spec["case_description"] = (
                        f"{paths.study_name} {study_name} study, Mach {spec['mach_number']}, "
                        f"AoA {spec['aoa']}, mesh {spec['mesh_level']}"
                    )
                    spec["restart_sol"] = format_yes_no(spec["restart_sol"])
                    spec["cfl_adapt"] = format_yes_no(spec["cfl_adapt"])

                    sa_options = str(spec.get("sa_options", "")).strip()
                    spec["sa_options_block"] = f"SA_OPTIONS = {sa_options}" if sa_options else ""

                    volume_output = str(spec.get("volume_output", "")).strip()
                    spec["volume_output_block"] = (
                        f"VOLUME_OUTPUT= {volume_output}" if volume_output else ""
                    )

                    if spec["case_name"] in seen_case_names:
                        raise ValueError(f"duplicate generated case name: {spec['case_name']}")
                    seen_case_names.add(spec["case_name"])
                    case_specs.append(spec)

    return case_specs


def write_text_file(path: Path, content: str) -> str:
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current == content:
            return "kept"
        path.write_text(content, encoding="utf-8")
        return "updated"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "created"


def remove_if_exists(path: Path) -> str:
    if not path.exists() and not path.is_symlink():
        return "missing"
    if path.is_dir() and not path.is_symlink():
        raise IsADirectoryError(f"refusing to remove directory with remove_if_exists: {path}")
    path.unlink()
    return "removed"


def ensure_alias_symlink(alias_path: Path, target_path: Path) -> str:
    if not target_path.exists():
        raise FileNotFoundError(f"alias target does not exist: {target_path}")

    desired_link = Path(target_path.name)
    if alias_path.is_symlink():
        current_link = Path(os.readlink(alias_path))
        if current_link == desired_link:
            return "kept"
        alias_path.unlink()
        alias_path.symlink_to(desired_link)
        return "updated"

    if alias_path.exists():
        raise FileExistsError(
            f"alias path exists as a regular directory/file and cannot be replaced safely: {alias_path}"
        )

    alias_path.parent.mkdir(parents=True, exist_ok=True)
    alias_path.symlink_to(desired_link)
    return "created"


def stage_case(paths: StudyPaths, spec: dict[str, Any], template_text: str) -> dict[str, str]:
    paths.ensure_runtime_dirs()

    case_name = str(spec["case_name"])
    alias_of = str(spec.get("alias_of", ""))
    case_dir = paths.case_path(case_name)
    generated_cfg = paths.generated_config_path(case_name)

    if alias_of:
        generated_cleanup = remove_if_exists(generated_cfg)
        if generated_cleanup == "missing":
            generated_cleanup = "not-needed"
        alias_status = ensure_alias_symlink(case_dir, paths.case_path(alias_of))
        return {
            "case_name": case_name,
            "generated": f"alias->{alias_of} ({generated_cleanup})",
            "case_dir": alias_status,
            "config_cleanup": "alias-skip",
            "run_cleanup": "alias-skip",
            "removed_links": "alias-skip",
            "alias_of": alias_of,
            "alias_note": describe_alias(spec),
        }

    case_dir_status = "kept"
    if case_dir.is_symlink():
        case_dir.unlink()
        case_dir_status = "replaced-alias"
    case_dir.mkdir(parents=True, exist_ok=True)

    config_text = render_template(template_text, spec) + "\n"
    generated_status = write_text_file(generated_cfg, config_text)

    config_cleanup = remove_if_exists(case_dir / "config.cfg")

    run_cleanup = remove_if_exists(case_dir / "run.sh")

    removed_links: list[str] = []
    for name in OLD_CASE_LOCAL_LINKS:
        path = case_dir / name
        if path.is_symlink():
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            else:
                removed_links.append(name)

    return {
        "case_name": case_name,
        "generated": generated_status,
        "case_dir": case_dir_status,
        "config_cleanup": config_cleanup,
        "run_cleanup": run_cleanup,
        "removed_links": ",".join(removed_links) if removed_links else "none",
        "alias_of": alias_of,
        "alias_note": describe_alias(spec),
    }


def preview_case(spec: dict[str, Any]) -> str:
    alias_label = describe_alias(spec)
    alias_suffix = f", alias_of={alias_label}" if alias_label else ""
    return (
        f"{spec['case_name']}: study={spec['study']}, mach={spec['mach_number']}, aoa={spec['aoa']}, "
        f"mesh={spec['mesh_level']}, restart={spec['restart_sol']}, cfl={spec['cfl_number']}{alias_suffix}"
    )


def main() -> int:
    args = parse_args()
    paths = get_study_paths(args.campaign)
    _, template_text, case_specs = load_case_setup(paths)
    case_specs = filter_case_specs(
        case_specs,
        args.cases,
        args.experiment,
        args.mach,
        args.aoa,
        args.mesh_level,
    )

    if not args.apply:
        print(f"Study: {paths.study_name}")
        print(f"Previewing {len(case_specs)} case(s):")
        for spec in case_specs:
            print(f"  - {preview_case(spec)}")
        print()
        print("No files written. Re-run with --apply to update the managed case layout.")
        return 0

    for spec in case_specs:
        result = stage_case(paths, spec, template_text)
        alias_suffix = f", alias_of={result['alias_note']}" if result["alias_note"] else ""
        print(
            f"{result['case_name']}: case_dir={result['case_dir']}, generated={result['generated']}, "
            f"config_cleanup={result['config_cleanup']}, run_cleanup={result['run_cleanup']}, "
            f"removed_links={result['removed_links']}{alias_suffix}"
        )

    print()
    print(f"Summary: updated {len(case_specs)} case(s), generated_dir={paths.generated_config_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
