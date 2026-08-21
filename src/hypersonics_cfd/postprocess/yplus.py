#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pyvista as pv

from hypersonics_cfd.cases import (
    cases_from_environment,
    choose_postprocess_cases_interactively,
    deduplicate_case_names,
    resolve_case_path,
)
from hypersonics_cfd.study import StudyPaths, choose_study_paths_interactively, get_study_paths
from hypersonics_cfd.workflow.setup import load_case_setup, render_template


MARKER_NAME = "ORION_SURFACE"
SURFACE_SOURCE_NAME = "surface_flow.vtu"
RESTART_NAME = "restart_flow.dat"
SURFACE_OUTPUT_NAME = "orion_yplus.vtp"
SUMMARY_OUTPUT_NAME = "yplus_summary.csv"
YPLUS_NAMES = ("Y_Plus", "Y_PLUS", "y_plus", "y+")
SUMMARY_FIELDS = (
    "case",
    "marker",
    "points",
    "cells",
    "surface_area_m2",
    "yplus_min",
    "yplus_area_mean",
    "yplus_area_median",
    "yplus_area_p95",
    "yplus_area_p99",
    "yplus_max",
    "area_fraction_yplus_gt_1",
    "area_fraction_yplus_gt_5",
)


def progress(message: str) -> None:
    print(message, flush=True)


def complete_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def yplus_name(dataset: pv.DataSet) -> tuple[str, str] | None:
    for association, arrays in (("point", dataset.point_data), ("cell", dataset.cell_data)):
        for candidate in YPLUS_NAMES:
            if candidate in arrays:
                return association, candidate
    return None


def read_usable_surface(path: Path, restart_path: Path) -> pv.DataSet | None:
    if not complete_file(path):
        return None
    if complete_file(restart_path) and path.stat().st_mtime < restart_path.stat().st_mtime:
        return None

    surface = pv.read(path)
    if surface.n_points == 0 or surface.n_cells == 0 or yplus_name(surface) is None:
        return None
    return surface


def locate_su2_sol() -> str:
    candidates = [
        os.environ.get("SU2_SOL", ""),
        shutil.which("SU2_SOL") or "",
        str(Path(os.environ.get("SU2_RUN", "")) / "SU2_SOL") if os.environ.get("SU2_RUN") else "",
        str(Path.home() / ".local" / "su2-7.5.1" / "bin" / "SU2_SOL"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise FileNotFoundError("SU2_SOL was not found in PATH, SU2_RUN, or ~/.local/su2-7.5.1/bin")


def set_config_option(config_text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=.*$", re.MULTILINE)
    replacement = f"{key}= {value}"
    if pattern.search(config_text):
        return pattern.sub(replacement, config_text, count=1)
    return config_text.rstrip() + f"\n{replacement}\n"


def base_config_text(paths: StudyPaths, case_name: str) -> str:
    generated_config = paths.generated_config_path(case_name)
    if generated_config.is_file():
        return generated_config.read_text(encoding="utf-8")

    _, template_text, specs = load_case_setup(paths)
    spec = next((item for item in specs if str(item["case_name"]) == case_name), None)
    if spec is None:
        raise KeyError(f"{case_name} is not a managed case in {paths.study_file}")
    return render_template(template_text, spec) + "\n"


def generate_surface_from_restart(
    paths: StudyPaths,
    case_name: str,
    case_path: Path,
    restart_path: Path,
) -> pv.DataSet:
    if not complete_file(restart_path):
        raise FileNotFoundError(f"missing restart solution: {restart_path}")

    su2_sol = locate_su2_sol()
    config_text = base_config_text(paths, case_name)
    with tempfile.TemporaryDirectory(prefix="yplus_", dir=case_path) as temp_name:
        temp_dir = Path(temp_name)
        surface_stem = temp_dir / "orion_yplus_raw"
        config_path = temp_dir / "yplus.cfg"

        overrides = {
            "RESTART_SOL": "YES",
            "SOLUTION_FILENAME": str(restart_path.resolve()),
            "MARKER_PLOTTING": f"( {MARKER_NAME} )",
            "OUTPUT_FILES": "( SURFACE_PARAVIEW )",
            "SURFACE_FILENAME": f"{temp_dir.name}/{surface_stem.name}",
            "VOLUME_OUTPUT": "COORDINATES, Y_PLUS",
        }
        for key, value in overrides.items():
            config_text = set_config_option(config_text, key, value)
        config_path.write_text(config_text, encoding="utf-8")

        progress(f"  [stage] generating {MARKER_NAME} y+ surface with SU2_SOL")
        subprocess.run([su2_sol, str(config_path)], cwd=case_path, check=True)

        candidates = [
            path
            for path in temp_dir.glob("orion_yplus_raw*")
            if path.suffix.lower() in {".vtu", ".vtp", ".vtk"}
        ]
        if not candidates:
            raise FileNotFoundError(f"SU2_SOL did not write a surface file under {temp_dir}")
        surface = pv.read(max(candidates, key=lambda path: path.stat().st_mtime))
        if surface.n_points == 0 or surface.n_cells == 0:
            raise ValueError(f"SU2_SOL produced an empty {MARKER_NAME} surface")
        if yplus_name(surface) is None:
            available = sorted(set(surface.point_data.keys()) | set(surface.cell_data.keys()))
            raise KeyError(f"surface has no y+ array; available arrays: {', '.join(available)}")
        return surface


def full_body_surface(surface: pv.DataSet) -> pv.PolyData:
    half = surface.extract_surface()
    mirrored = half.copy(deep=True)
    mirrored_points = np.asarray(mirrored.points).copy()
    mirrored_points[:, 1] *= -1.0
    mirrored.points = mirrored_points
    return half.merge(mirrored, merge_points=True).extract_surface()


def weighted_percentile(values: np.ndarray, weights: np.ndarray, fraction: float) -> float:
    order = np.argsort(values)
    sorted_values = values[order]
    cumulative = np.cumsum(weights[order])
    index = np.searchsorted(cumulative, fraction * cumulative[-1], side="left")
    return float(sorted_values[min(index, sorted_values.size - 1)])


def summarize_yplus(case_name: str, surface: pv.PolyData) -> dict[str, str]:
    association_and_name = yplus_name(surface)
    if association_and_name is None:
        raise KeyError("surface has no y+ array")
    association, array_name = association_and_name
    source_arrays = surface.point_data if association == "point" else surface.cell_data
    source_values = np.asarray(source_arrays[array_name], dtype=float).reshape(-1)
    source_values = source_values[np.isfinite(source_values) & (source_values >= 0.0)]
    if source_values.size == 0:
        raise ValueError("surface contains no valid y+ values")

    cells = surface.compute_cell_sizes(length=False, area=True, volume=False)
    if association == "point":
        cells = cells.point_data_to_cell_data(pass_point_data=True)

    values = np.asarray(cells.cell_data[array_name], dtype=float).reshape(-1)
    areas = np.asarray(cells.cell_data["Area"], dtype=float).reshape(-1)
    valid = np.isfinite(values) & np.isfinite(areas) & (values >= 0.0) & (areas > 0.0)
    values = values[valid]
    areas = areas[valid]
    if values.size == 0:
        raise ValueError("surface contains no valid y+ values on positive-area cells")

    total_area = float(np.sum(areas))
    weighted_mean = float(np.sum(values * areas) / total_area)
    area_fraction_gt_1 = float(np.sum(areas[values > 1.0]) / total_area)
    area_fraction_gt_5 = float(np.sum(areas[values > 5.0]) / total_area)

    def formatted(value: float) -> str:
        return f"{value:.8g}"

    return {
        "case": case_name,
        "marker": MARKER_NAME,
        "points": str(surface.n_points),
        "cells": str(surface.n_cells),
        "surface_area_m2": formatted(total_area),
        "yplus_min": formatted(float(np.min(source_values))),
        "yplus_area_mean": formatted(weighted_mean),
        "yplus_area_median": formatted(weighted_percentile(values, areas, 0.50)),
        "yplus_area_p95": formatted(weighted_percentile(values, areas, 0.95)),
        "yplus_area_p99": formatted(weighted_percentile(values, areas, 0.99)),
        "yplus_max": formatted(float(np.max(source_values))),
        "area_fraction_yplus_gt_1": formatted(area_fraction_gt_1),
        "area_fraction_yplus_gt_5": formatted(area_fraction_gt_5),
    }


def write_outputs(case_path: Path, surface: pv.PolyData, summary: dict[str, str]) -> None:
    surface_path = case_path / SURFACE_OUTPUT_NAME
    surface_part = surface_path.with_name(f"{surface_path.stem}.part{surface_path.suffix}")
    surface_part.unlink(missing_ok=True)
    surface.save(surface_part)
    surface_part.replace(surface_path)

    summary_path = case_path / SUMMARY_OUTPUT_NAME
    summary_part = summary_path.with_suffix(".part.csv")
    with summary_part.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerow(summary)
    summary_part.replace(summary_path)


def extract_case(paths: StudyPaths, case_name: str) -> None:
    case_path = resolve_case_path(paths.study_root, paths.cases_dir, case_name)
    restart_path = case_path / RESTART_NAME
    source_path = case_path / SURFACE_SOURCE_NAME

    surface = read_usable_surface(source_path, restart_path)
    if surface is None:
        surface = generate_surface_from_restart(paths, case_name, case_path, restart_path)
    else:
        progress(f"  [stage] using existing {source_path.name}")

    full_surface = full_body_surface(surface)
    summary = summarize_yplus(case_name, full_surface)
    write_outputs(case_path, full_surface, summary)

    progress(
        f"  [ok ] wrote {SURFACE_OUTPUT_NAME} and {SUMMARY_OUTPUT_NAME}: "
        f"mean={summary['yplus_area_mean']}, p95={summary['yplus_area_p95']}, "
        f"max={summary['yplus_max']}, area(y+>1)={summary['area_fraction_yplus_gt_1']}"
    )


def parse_case_names(raw_cases: str) -> list[str]:
    return [part.strip() for part in raw_cases.replace(",", " ").split() if part.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Extract {MARKER_NAME} y+ surface and summary.")
    parser.add_argument("--study", default=os.environ.get("CFD_STUDY", ""))
    parser.add_argument("--cases", default=os.environ.get("CFD_CASE", ""))
    args = parser.parse_args()

    paths = get_study_paths(args.study) if args.study else choose_study_paths_interactively()
    cases = parse_case_names(args.cases)
    if not cases:
        cases = cases_from_environment(paths)
    if not cases:
        cases = choose_postprocess_cases_interactively(paths.cases_dir, RESTART_NAME)
    cases = deduplicate_case_names(paths.study_root, paths.cases_dir, cases)

    for case_name in cases:
        progress(f"-> {case_name}")
        extract_case(paths, case_name)
    return 0
