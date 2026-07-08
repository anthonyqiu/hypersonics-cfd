#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pyvista as pv
import vtk

from case_selection import MESH_LEVEL_ORDER, mach_sort_key
from layout import get_study_paths
from setup_cases import load_case_setup


SHOCK_SURFACE_NAME = "shock_surface.vtp"
DEFAULT_OUTPUT_NAME = "shock_surface_deviation_refinement.csv"


def load_surface(path: Path) -> pv.PolyData:
    mesh = pv.read(path)
    if not isinstance(mesh, pv.PolyData):
        mesh = mesh.extract_surface()
    mesh = mesh.triangulate().clean()
    if mesh.n_points == 0 or mesh.n_cells == 0:
        raise ValueError(f"empty surface: {path}")
    return mesh


def cell_centers_and_areas(mesh: pv.PolyData) -> tuple[np.ndarray, np.ndarray, float]:
    sized = mesh.compute_cell_sizes(length=False, area=True, volume=False)
    areas = np.asarray(sized.cell_data["Area"], dtype=float)
    centers = np.asarray(mesh.cell_centers().points, dtype=float)
    valid = np.isfinite(areas) & (areas > 0.0)
    centers = centers[valid]
    areas = areas[valid]
    total_area = float(np.sum(areas))
    if centers.size == 0 or total_area <= 0.0:
        raise ValueError("surface has no positive-area cells")
    return centers, areas, total_area


def build_locator(mesh: pv.PolyData) -> vtk.vtkStaticCellLocator:
    locator = vtk.vtkStaticCellLocator()
    locator.SetDataSet(mesh)
    locator.BuildLocator()
    return locator


def closest_surface_distances(points: np.ndarray, locator: vtk.vtkStaticCellLocator) -> np.ndarray:
    distances = np.empty(points.shape[0], dtype=float)
    closest = [0.0, 0.0, 0.0]
    cell = vtk.vtkGenericCell()
    cell_id = vtk.mutable(0)
    sub_id = vtk.mutable(0)
    dist2 = vtk.mutable(0.0)

    for index, point in enumerate(points):
        locator.FindClosestPoint(point, closest, cell, cell_id, sub_id, dist2)
        distances[index] = math.sqrt(max(float(dist2), 0.0))
    return distances


def weighted_percentile(values: np.ndarray, weights: np.ndarray, percentile: float) -> float:
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights)
    cutoff = percentile / 100.0 * cumulative[-1]
    return float(sorted_values[np.searchsorted(cumulative, cutoff, side="left")])


def weighted_stats(distances: np.ndarray, weights: np.ndarray) -> dict[str, float]:
    weight_sum = float(np.sum(weights))
    mean = float(np.sum(weights * distances) / weight_sum)
    rms = math.sqrt(float(np.sum(weights * distances * distances) / weight_sum))
    return {
        "mean": mean,
        "rms": rms,
        "p95": weighted_percentile(distances, weights, 95.0),
        "max": float(np.max(distances)),
    }


def directed_stats(source: pv.PolyData, target_locator: vtk.vtkStaticCellLocator) -> dict[str, Any]:
    centers, areas, total_area = cell_centers_and_areas(source)
    distances = closest_surface_distances(centers, target_locator)
    stats = weighted_stats(distances, areas)
    stats["area"] = total_area
    stats["samples"] = int(distances.size)
    stats["distances"] = distances
    stats["weights"] = areas
    return stats


def symmetric_surface_distance(source_path: Path, reference_path: Path) -> dict[str, Any]:
    source = load_surface(source_path)
    reference = load_surface(reference_path)
    source_locator = build_locator(source)
    reference_locator = build_locator(reference)

    source_to_reference = directed_stats(source, reference_locator)
    reference_to_source = directed_stats(reference, source_locator)
    combined_distances = np.concatenate(
        [source_to_reference["distances"], reference_to_source["distances"]]
    )
    combined_weights = np.concatenate(
        [source_to_reference["weights"], reference_to_source["weights"]]
    )
    symmetric = weighted_stats(combined_distances, combined_weights)

    return {
        "source_points": source.n_points,
        "source_cells": source.n_cells,
        "source_area": source_to_reference["area"],
        "reference_points": reference.n_points,
        "reference_cells": reference.n_cells,
        "reference_area": reference_to_source["area"],
        "forward_mean": source_to_reference["mean"],
        "forward_rms": source_to_reference["rms"],
        "backward_mean": reference_to_source["mean"],
        "backward_rms": reference_to_source["rms"],
        "symmetric_mean": symmetric["mean"],
        "symmetric_rms": symmetric["rms"],
        "symmetric_p95": symmetric["p95"],
        "symmetric_max": symmetric["max"],
    }


def case_surface_path(paths, spec: dict[str, Any]) -> Path:
    case_name = str(spec.get("alias_of") or spec["case_name"])
    return paths.case_path(case_name) / SHOCK_SURFACE_NAME


def output_path_from_args(paths, raw_output: str) -> Path:
    output = Path(raw_output)
    if output.is_absolute():
        return output
    return paths.study_root / "data" / output


def refinement_groups(specs: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    groups: dict[str, dict[str, dict[str, Any]]] = {}
    for spec in specs:
        if spec.get("study") != "refinement":
            continue
        groups.setdefault(str(spec["mach_token"]), {})[str(spec["mesh_level"])] = spec
    return groups


def ordered_refinement_items(
    cases_by_level: dict[str, dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    return sorted(cases_by_level.items(), key=lambda item: MESH_LEVEL_ORDER.get(item[0], 99))


def available_surfaces(paths, cases_by_level: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any], Path]]:
    available: list[tuple[str, dict[str, Any], Path]] = []
    for level, spec in ordered_refinement_items(cases_by_level):
        surface_path = case_surface_path(paths, spec)
        if surface_path.is_file() and surface_path.stat().st_size > 0:
            available.append((level, spec, surface_path))
    return available


def format_metric(value: float) -> str:
    return f"{value:.10g}"


def missing_row(mach: str, case_name: str, mesh_level: str, status: str) -> dict[str, str]:
    return {
        "mach": mach,
        "case_a": case_name,
        "mesh_level_a": mesh_level,
        "case_b": "",
        "mesh_level_b": "",
        "comparison": "",
        "is_adjacent": "",
        "status": status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare Orion refinement shock surfaces with an area-weighted symmetric "
            "closest-surface distance."
        )
    )
    parser.add_argument("--study", default="orion")
    parser.add_argument("--diameter", type=float, default=0.0, help="Characteristic length for normalization.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_NAME)
    args = parser.parse_args()

    paths = get_study_paths(args.study)
    matrix, _, specs = load_case_setup(paths)
    diameter = args.diameter or float(matrix.get("defaults", {}).get("reynolds_length", 5.0))
    if diameter <= 0.0:
        raise SystemExit("Characteristic diameter must be positive.")

    output_path = output_path_from_args(paths, args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    groups = refinement_groups(specs)
    for mach in sorted(groups, key=mach_sort_key):
        cases_by_level = groups[mach]
        available = available_surfaces(paths, cases_by_level)
        if len(available) < 2:
            print(f"m{mach}: fewer than two refinement shock surfaces found")
            for level, spec in ordered_refinement_items(cases_by_level):
                surface_path = case_surface_path(paths, spec)
                status = "ok_unpaired" if surface_path.is_file() and surface_path.stat().st_size > 0 else "missing_surface"
                rows.append(missing_row(mach, str(spec["case_name"]), level, status))
            continue

        print(f"m{mach}: {len(available)} available refinement surfaces")
        for (level_a, spec_a, path_a), (level_b, spec_b, path_b) in combinations(available, 2):
            case_a = str(spec_a["case_name"])
            case_b = str(spec_b["case_name"])
            order_a = MESH_LEVEL_ORDER.get(level_a, 99)
            order_b = MESH_LEVEL_ORDER.get(level_b, 99)
            is_adjacent = (order_b - order_a) == 1
            comparison = f"{level_a}-{level_b}"
            print(f"  {case_a} <-> {case_b}")
            try:
                metrics = symmetric_surface_distance(path_a, path_b)
            except Exception as exc:
                print(f"    failed: {exc}")
                rows.append(
                    {
                        "mach": mach,
                        "case_a": case_a,
                        "mesh_level_a": level_a,
                        "case_b": case_b,
                        "mesh_level_b": level_b,
                        "comparison": comparison,
                        "is_adjacent": str(is_adjacent).lower(),
                        "status": "failed",
                    }
                )
                continue

            row = {
                "mach": mach,
                "case_a": case_a,
                "mesh_level_a": level_a,
                "case_b": case_b,
                "mesh_level_b": level_b,
                "comparison": comparison,
                "is_adjacent": str(is_adjacent).lower(),
                "status": "ok",
            }
            for key, value in metrics.items():
                row[key] = format_metric(float(value))
            for key in ("symmetric_mean", "symmetric_rms", "symmetric_p95", "symmetric_max"):
                row[f"{key}_over_D"] = format_metric(float(metrics[key]) / diameter)
            rows.append(row)

    fieldnames = [
        "mach",
        "case_a",
        "mesh_level_a",
        "case_b",
        "mesh_level_b",
        "comparison",
        "is_adjacent",
        "status",
        "source_points",
        "source_cells",
        "source_area",
        "reference_points",
        "reference_cells",
        "reference_area",
        "forward_mean",
        "forward_rms",
        "backward_mean",
        "backward_rms",
        "symmetric_mean",
        "symmetric_rms",
        "symmetric_p95",
        "symmetric_max",
        "symmetric_mean_over_D",
        "symmetric_rms_over_D",
        "symmetric_p95_over_D",
        "symmetric_max_over_D",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    ok_count = sum(1 for row in rows if row.get("status") == "ok")
    print(f"\nwrote {output_path} ({ok_count} comparison rows, D={diameter:g} m)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
