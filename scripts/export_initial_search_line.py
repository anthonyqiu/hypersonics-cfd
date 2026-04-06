#!/usr/bin/env python3
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

import numpy as np
import pyvista as pv

from case_selection import choose_postprocess_cases_interactively, deduplicate_case_names, resolve_case_path
from extract_shock_surface import (
    autoscaled_savgol_window_points,
    build_stagnation_search_diagnostics,
    build_streamwise_window,
    choose_stagnation_shock_node,
    configured_sampling_steps,
    density_scalar,
    load_case_aoa_degrees,
    smooth_line_profile,
    streamwise_basis_from_aoa,
    suppress_vtk_warnings,
    surface_sensor_min_fraction,
    vtk_warning_mode,
    vtu_name,
    savgol_poly_order,
    savgol_smoothing_length,
)
from layout import StudyPaths, choose_study_paths_interactively, get_study_paths


OUTPUT_FILENAME = "initial_search_line_profile.csv"


def cases_from_environment(paths: StudyPaths) -> list[str]:
    raw_cases = os.environ.get("CFD_CASES", "").strip()
    single_case = os.environ.get("CFD_CASE", "").strip()
    requested_cases: list[str] = []

    if raw_cases:
        requested_cases.extend(part.strip() for part in raw_cases.replace("\n", ",").split(",") if part.strip())
    if single_case:
        requested_cases.append(single_case)

    if not requested_cases:
        return []

    return deduplicate_case_names(paths.study_root, paths.cases_dir, requested_cases)


def line_sample_spacing(line_coordinates: np.ndarray, default_spacing: float) -> float:
    if line_coordinates.size < 2:
        return float(default_spacing)
    return abs(float(line_coordinates[1]) - float(line_coordinates[0]))


def line_window_points(line_coordinates: np.ndarray, valid_mask: np.ndarray, default_spacing: float) -> int:
    valid_idx = np.flatnonzero(valid_mask)
    if valid_idx.size == 0:
        return 0
    segment_size = int(valid_idx[-1] - valid_idx[0] + 1)
    if segment_size < 3:
        return segment_size
    spacing = line_sample_spacing(line_coordinates, default_spacing)
    return int(autoscaled_savgol_window_points(spacing, segment_size))


def rows_for_pass(
    *,
    study_name: str,
    case_name: str,
    pass_name: str,
    record: dict[str, Any],
    dt: float,
    dn: float,
    aoa_degrees: float,
    center_peak: float,
    sensor_floor: float,
) -> list[dict[str, object]]:
    sample = record["sample"]
    candidate = record["candidate"]
    line_center = np.asarray(record["line_center"], dtype=float)
    line_direction = np.asarray(record["line_direction"], dtype=float)
    half_length = float(record["half_length"])
    sample_spacing = float(record["sample_spacing"])

    smoothed = smooth_line_profile(
        sample["shock_sensor_raw"],
        sample["valid_mask"],
        sample["line_coordinates"],
    )
    window_points = line_window_points(sample["line_coordinates"], sample["valid_mask"], sample_spacing)

    selected_peak_index = int(candidate["sample_index"]) if candidate is not None else -1
    selected_peak_coordinate = (
        float(candidate["line_coordinate"]) if candidate is not None else float("nan")
    )
    selected_peak_value = (
        float(candidate["shock_sensor_smoothed"]) if candidate is not None else float("nan")
    )

    rows: list[dict[str, object]] = []
    for idx, point in enumerate(np.asarray(sample["points"], dtype=float)):
        rows.append(
            {
                "study_name": study_name,
                "case_name": case_name,
                "pass_name": pass_name,
                "sample_index": int(idx),
                "line_coordinate": float(sample["line_coordinates"][idx]),
                "x": float(point[0]),
                "y": float(point[1]),
                "z": float(point[2]),
                "density": float(sample["density"][idx]),
                "shock_sensor_raw": float(sample["shock_sensor_raw"][idx]),
                "shock_sensor_smoothed": float(smoothed[idx]),
                "valid_mask": int(bool(sample["valid_mask"][idx])),
                "is_selected_peak": int(idx == selected_peak_index),
                "selected_peak_index": selected_peak_index,
                "selected_peak_coordinate": selected_peak_coordinate,
                "selected_peak_value": selected_peak_value,
                "line_center_x": float(line_center[0]),
                "line_center_y": float(line_center[1]),
                "line_center_z": float(line_center[2]),
                "line_direction_x": float(line_direction[0]),
                "line_direction_y": float(line_direction[1]),
                "line_direction_z": float(line_direction[2]),
                "half_length": half_length,
                "sample_spacing": sample_spacing,
                "savgol_window_points": window_points,
                "savgol_smoothing_length": float(savgol_smoothing_length),
                "savgol_poly_order": int(savgol_poly_order),
                "dt": float(dt),
                "dn": float(dn),
                "aoa_degrees": float(aoa_degrees),
                "center_peak": float(center_peak),
                "sensor_floor": float(sensor_floor),
            }
        )
    return rows


def write_profile_csv(output_path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty initial-search-line profile")

    fieldnames = list(rows[0].keys())
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_case(paths: StudyPaths, case_dir: str) -> Path | None:
    case_path = resolve_case_path(paths.study_root, paths.cases_dir, case_dir)
    vtu_path = case_path / vtu_name
    if not vtu_path.exists():
        print(f"  [skip] no {vtu_name} in {case_path.name}")
        return None

    print(f"  [stage] reading flow field: {vtu_path}")
    mesh = pv.read(vtu_path)
    if density_scalar not in mesh.point_data and density_scalar in mesh.cell_data:
        print("  [stage] converting cell data to point data")
        mesh = mesh.cell_data_to_point_data()

    if density_scalar not in mesh.array_names:
        available = ", ".join(sorted(mesh.array_names))
        raise KeyError(f"{density_scalar!r} not found. Available arrays: {available}")

    print("  [stage] differentiating 3D density field")
    with vtk_warning_mode(suppress_vtk_warnings):
        gradient_mesh = mesh.compute_derivative(scalars=density_scalar, gradient=True)

    aoa_degrees = load_case_aoa_degrees(paths.generated_config_dir, case_path)
    print(f"  [stage] building AoA-aligned frame (aoa={aoa_degrees:.1f} deg)")
    streamwise, normal, spanwise = streamwise_basis_from_aoa(aoa_degrees)

    points = np.asarray(gradient_mesh.points)
    gradient = np.asarray(gradient_mesh["gradient"], dtype=float)
    gradient = np.nan_to_num(gradient, nan=0.0, posinf=0.0, neginf=0.0)
    shock_sensor_raw = np.linalg.norm(gradient, axis=1)
    gradient_mesh["ShockSensorRaw"] = shock_sensor_raw

    _, center_peak = choose_stagnation_shock_node(points, shock_sensor_raw, streamwise)
    active_mask = shock_sensor_raw >= center_peak * surface_sensor_min_fraction
    active_points = points[active_mask]
    if active_points.size == 0:
        raise ValueError("no active points passed the surface sensor threshold")

    dt, dn = configured_sampling_steps()
    sensor_floor = center_peak * surface_sensor_min_fraction
    stream_center, stream_half_length = build_streamwise_window(
        active_points, streamwise, normal, spanwise, dn
    )
    diagnostics = build_stagnation_search_diagnostics(
        gradient_mesh,
        stream_center,
        stream_half_length,
        streamwise,
        dn,
    )

    rows: list[dict[str, object]] = []
    rows.extend(
        rows_for_pass(
            study_name=paths.study_name,
            case_name=case_path.name,
            pass_name="coarse",
            record=diagnostics["coarse"],
            dt=dt,
            dn=dn,
            aoa_degrees=aoa_degrees,
            center_peak=center_peak,
            sensor_floor=sensor_floor,
        )
    )
    rows.extend(
        rows_for_pass(
            study_name=paths.study_name,
            case_name=case_path.name,
            pass_name="refined",
            record=diagnostics["refined"],
            dt=dt,
            dn=dn,
            aoa_degrees=aoa_degrees,
            center_peak=center_peak,
            sensor_floor=sensor_floor,
        )
    )

    output_path = case_path / OUTPUT_FILENAME
    write_profile_csv(output_path, rows)

    chosen_candidate = diagnostics["chosen_candidate"]
    chosen_coordinate = float(chosen_candidate["line_coordinate"])
    chosen_value = float(chosen_candidate["shock_sensor_smoothed"])
    print(
        f"  [ok ] wrote {output_path} "
        f"(chosen peak at n={chosen_coordinate:.4f}, smoothed |grad rho|={chosen_value:.4f})"
    )
    return output_path


def main() -> int:
    env_study = os.environ.get("CFD_STUDY", "").strip()
    paths = get_study_paths(env_study) if env_study else choose_study_paths_interactively()

    print("\n╔══════════════════════════════════════════════╗")
    print("║   Initial Search-Line Diagnostic Export     ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"Study: {paths.study_name}")
    print(f"Output file: {OUTPUT_FILENAME}")

    cases = cases_from_environment(paths)
    if not cases:
        cases = choose_postprocess_cases_interactively(paths.cases_dir, vtu_name)
        cases = deduplicate_case_names(paths.study_root, paths.cases_dir, cases)
    if not cases:
        return 0

    print(f"\nProcessing {len(cases)} case(s)...\n")
    for case in cases:
        print(f"-> {case}")
        export_case(paths, case)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
