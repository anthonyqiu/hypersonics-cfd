#!/usr/bin/env python3
"""Shift SU2/PyVista flow-field coordinates in x.

This script only moves the point coordinates in a `flow.vtu` file. It leaves
all solution arrays and mesh connectivity unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


DEFAULT_DX = 0.71
DEFAULT_INPUT_NAME = "flow.vtu"
DEFAULT_OUTPUT_NAME = "flow_shifted.vtu"


def flow_paths(path: Path, output_name: str) -> tuple[Path, Path]:
    if path.is_dir():
        return path / DEFAULT_INPUT_NAME, path / output_name
    return path, path.with_name(output_name)


def shift_flow(source: Path, destination: Path, dx: float, overwrite: bool) -> None:
    if not source.exists():
        raise FileNotFoundError(f"missing input: {source}")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"output exists: {destination} (use --overwrite)")

    try:
        import pyvista as pv
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "pyvista/vtk is required. Load the same Python environment used for "
            "shock extraction, then rerun this script."
        ) from exc

    mesh = pv.read(source)
    if mesh.n_points == 0:
        raise ValueError(f"{source} has no points")

    shift = np.array([dx, 0.0, 0.0])
    old_bounds = mesh.bounds
    mesh.points = np.asarray(mesh.points) + shift

    destination.parent.mkdir(parents=True, exist_ok=True)
    mesh.save(destination)
    print(f"{source} -> {destination}")
    print(f"shifted x by {dx:g} m")
    print(f"bounds: {old_bounds} -> {mesh.bounds}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Shift flow.vtu coordinates in +x.")
    parser.add_argument("path", type=Path, help="Case directory or flow.vtu file.")
    parser.add_argument("--dx", type=float, default=DEFAULT_DX, help="x shift in metres.")
    parser.add_argument(
        "--output-name",
        default=DEFAULT_OUTPUT_NAME,
        help="Output filename next to the input/case directory.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output file.")
    args = parser.parse_args()

    source, destination = flow_paths(args.path, args.output_name)
    shift_flow(source, destination, args.dx, args.overwrite)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
