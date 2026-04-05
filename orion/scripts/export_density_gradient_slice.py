#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pyvista as pv

from case_cli import deduplicate_case_names, choose_postprocess_cases_interactively, resolve_case_path

try:
    from vtkmodules.vtkCommonCore import vtkObject
except ImportError:
    vtkObject = None

# --------------- USER SETTINGS ---------------
vtu_name = "flow.vtu"
output_name = "density_gradient_y0.vtu"
slice_normal = "y"
slice_origin = (0.0, 0.0, 0.0)
density_scalar = "Density"
gradient_array_name = "DensityGradient"
gradient_magnitude_name = "DensityGradientMagnitude"
gradient_log_magnitude_name = "DensityGradientLog10Magnitude"
gradient_component_names = ("DensityGradientX", "DensityGradientY", "DensityGradientZ")
keep_density_array = True
suppress_vtk_warnings = True
# ---------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
CASES_DIR = ROOT / "cases"


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
        "cases",
        nargs="*",
        help="Optional case names or paths. If omitted, the interactive selector is used.",
    )
    return parser.parse_args()


def build_lightweight_slice(case_path: Path) -> tuple[pv.UnstructuredGrid, str]:
    vtu_path = case_path / vtu_name
    mesh = pv.read(vtu_path).cell_data_to_point_data()

    if density_scalar not in mesh.array_names:
        available = ", ".join(sorted(mesh.array_names))
        raise KeyError(f"{density_scalar!r} not found. Available arrays: {available}")

    with vtk_warning_mode(suppress_vtk_warnings):
        volume_with_gradient = mesh.compute_derivative(scalars=density_scalar, gradient=True)
        slice_mesh = volume_with_gradient.slice(normal=slice_normal, origin=slice_origin)

    gradient = np.asarray(slice_mesh["gradient"], dtype=float)
    gradient = np.nan_to_num(gradient, nan=0.0, posinf=0.0, neginf=0.0)
    gradient_magnitude = np.linalg.norm(gradient, axis=1)
    positive = gradient_magnitude[gradient_magnitude > 0.0]
    log_floor = np.quantile(positive, 0.01) if positive.size else 1.0
    log_floor = max(float(log_floor), 1e-30)
    gradient_log_magnitude = np.log10(np.maximum(gradient_magnitude, log_floor))

    lightweight = slice_mesh.cast_to_unstructured_grid()

    # Remove all arrays except the ones we explicitly want to keep.
    for array_name in list(lightweight.array_names):
        if array_name in {density_scalar, "gradient"}:
            continue
        if array_name in lightweight.point_data:
            del lightweight.point_data[array_name]
        if array_name in lightweight.cell_data:
            del lightweight.cell_data[array_name]

    if not keep_density_array and density_scalar in lightweight.point_data:
        del lightweight.point_data[density_scalar]

    if "gradient" in lightweight.point_data:
        lightweight.point_data[gradient_array_name] = gradient
        del lightweight.point_data["gradient"]

    lightweight.point_data[gradient_magnitude_name] = gradient_magnitude
    lightweight.point_data[gradient_log_magnitude_name] = gradient_log_magnitude
    for component_name, values in zip(gradient_component_names, gradient.T):
        lightweight.point_data[component_name] = values
    return lightweight, density_scalar


def process_case(case_dir: str):
    case_path = resolve_case_path(ROOT, CASES_DIR, case_dir)
    vtu_path = case_path / vtu_name
    if not vtu_path.exists():
        print(f"  [skip] no {vtu_name} in {case_path.name}")
        return

    output_path = case_path / output_name
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

    print("\n╔══════════════════════════════════════════════╗")
    print("║   Density Gradient Slice VTU Exporter       ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"Output file: {output_name}")
    print(f"Slice: normal={slice_normal}, origin={slice_origin}")

    cases = args.cases or choose_postprocess_cases_interactively(CASES_DIR, vtu_name)
    cases = deduplicate_case_names(ROOT, CASES_DIR, cases)
    if not cases:
        return 0

    print(f"\nProcessing {len(cases)} case(s)...\n")
    for case in cases:
        print(f"-> {case}")
        process_case(case)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
