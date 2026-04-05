#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pyvista as pv

from case_selection import deduplicate_case_names, choose_postprocess_cases_interactively, resolve_case_path
from layout import get_study_paths

try:
    from vtkmodules.vtkCommonCore import vtkObject
except ImportError:
    vtkObject = None

# --------------- USER SETTINGS ---------------
VTU_NAME = "flow.vtu"
OUTPUT_NAME = "density_gradient_y0.vtu"
SLICE_NORMAL = "y"
SLICE_ORIGIN = (0.0, 0.0, 0.0)
DENSITY_SCALAR = "Density"
GRADIENT_ARRAY_NAME = "DensityGradient"
GRADIENT_MAGNITUDE_NAME = "DensityGradientMagnitude"
GRADIENT_LOG_MAGNITUDE_NAME = "DensityGradientLog10Magnitude"
GRADIENT_COMPONENT_NAMES = ("DensityGradientX", "DensityGradientY", "DensityGradientZ")
KEEP_DENSITY_ARRAY = True
SUPPRESS_VTK_WARNINGS = True
# ---------------------------------------------


@contextmanager
def vtk_warning_mode(enabled: bool):
    if not enabled or vtkObject is None:
        yield
        return

    previous = vtkObject.GetGlobalWarningDisplay()
    vtkObject.SetGlobalWarningDisplay(0)
    try:
        yield
    finally:
        vtkObject.SetGlobalWarningDisplay(previous)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Slice each case at y=0, compute the density gradient, and write a lightweight VTU."
    )
    parser.add_argument(
        "--study",
        default="orion",
        help='Study slug under studies/. Defaults to "orion".',
    )
    parser.add_argument(
        "cases",
        nargs="*",
        help="Optional case names or paths. If omitted, the interactive selector is used.",
    )
    return parser.parse_args()


def build_lightweight_slice(case_path: Path) -> tuple[pv.UnstructuredGrid, str]:
    vtu_path = case_path / VTU_NAME
    mesh = pv.read(vtu_path).cell_data_to_point_data()

    if DENSITY_SCALAR not in mesh.array_names:
        available = ", ".join(sorted(mesh.array_names))
        raise KeyError(f"{DENSITY_SCALAR!r} not found. Available arrays: {available}")

    with vtk_warning_mode(SUPPRESS_VTK_WARNINGS):
        volume_with_gradient = mesh.compute_derivative(scalars=DENSITY_SCALAR, gradient=True)
        slice_mesh = volume_with_gradient.slice(normal=SLICE_NORMAL, origin=SLICE_ORIGIN)

    gradient = np.asarray(slice_mesh["gradient"], dtype=float)
    gradient = np.nan_to_num(gradient, nan=0.0, posinf=0.0, neginf=0.0)
    gradient_magnitude = np.linalg.norm(gradient, axis=1)
    positive = gradient_magnitude[gradient_magnitude > 0.0]
    log_floor = np.quantile(positive, 0.01) if positive.size else 1.0
    log_floor = max(float(log_floor), 1e-30)
    gradient_log_magnitude = np.log10(np.maximum(gradient_magnitude, log_floor))

    lightweight = slice_mesh.cast_to_unstructured_grid()

    for array_name in list(lightweight.array_names):
        if array_name in {DENSITY_SCALAR, "gradient"}:
            continue
        if array_name in lightweight.point_data:
            del lightweight.point_data[array_name]
        if array_name in lightweight.cell_data:
            del lightweight.cell_data[array_name]

    if not KEEP_DENSITY_ARRAY and DENSITY_SCALAR in lightweight.point_data:
        del lightweight.point_data[DENSITY_SCALAR]

    if "gradient" in lightweight.point_data:
        lightweight.point_data[GRADIENT_ARRAY_NAME] = gradient
        del lightweight.point_data["gradient"]

    lightweight.point_data[GRADIENT_MAGNITUDE_NAME] = gradient_magnitude
    lightweight.point_data[GRADIENT_LOG_MAGNITUDE_NAME] = gradient_log_magnitude
    for component_name, values in zip(GRADIENT_COMPONENT_NAMES, gradient.T):
        lightweight.point_data[component_name] = values
    return lightweight, DENSITY_SCALAR


def process_case(paths, case_dir: str):
    case_path = resolve_case_path(paths.study_root, paths.cases_dir, case_dir)
    vtu_path = case_path / VTU_NAME
    if not vtu_path.exists():
        print(f"  [skip] no {VTU_NAME} in {case_path.name}")
        return

    output_path = case_path / OUTPUT_NAME
    print(f"  [read] {vtu_path}")
    lightweight, scalar_used = build_lightweight_slice(case_path)
    lightweight.save(output_path)
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(
        f"  [ok ] wrote {output_path} "
        f"({lightweight.n_points} pts, {lightweight.n_cells} cells, scalar={scalar_used}, size={size_mb:.2f} MB)"
    )


def main() -> int:
    args = parse_args()
    paths = get_study_paths(args.study)

    print("\n╔══════════════════════════════════════════════╗")
    print("║   Density Gradient Slice VTU Exporter       ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"Study: {paths.study_name}")
    print(f"Output file: {OUTPUT_NAME}")
    print(f"Slice: normal={SLICE_NORMAL}, origin={SLICE_ORIGIN}")

    cases = args.cases or choose_postprocess_cases_interactively(paths.cases_dir, VTU_NAME)
    cases = deduplicate_case_names(paths.study_root, paths.cases_dir, cases)
    if not cases:
        return 0

    print(f"\nProcessing {len(cases)} case(s)...\n")
    for case in cases:
        print(f"-> {case}")
        process_case(paths, case)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
