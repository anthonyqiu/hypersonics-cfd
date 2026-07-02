#!/usr/bin/env python3
"""Mirror a half-domain flow.vtu across the symmetry plane.

The default Orion half meshes use the global y=0 symmetry plane. The script
keeps the original half, appends a mirrored half, and flips the mirrored y
component of 3-component vector arrays such as Momentum.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


AXIS_INDEX = {"x": 0, "y": 1, "z": 2}
DEFAULT_INPUT_NAME = "flow.vtu"
DEFAULT_OUTPUT_NAME = "flow_full.vtu"


def flow_paths(path: Path, input_name: str, output_name: str) -> tuple[Path, Path]:
    if path.is_dir():
        return path / input_name, path / output_name
    return path, path.with_name(output_name)


def reflect_points(points: np.ndarray, axis: int, plane_value: float) -> np.ndarray:
    mirrored = np.array(points, copy=True)
    mirrored[:, axis] = 2.0 * plane_value - mirrored[:, axis]
    return mirrored


def flip_vector_components(data, axis: int) -> None:
    for name in list(data.keys()):
        values = np.asarray(data[name])
        if values.ndim == 2 and values.shape[1] == 3:
            flipped = np.array(values, copy=True)
            flipped[:, axis] *= -1.0
            data[name] = flipped


def mirror_flow(
    source: Path,
    destination: Path,
    *,
    axis_name: str,
    plane_value: float,
    overwrite: bool,
    merge_points: bool,
) -> None:
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

    axis = AXIS_INDEX[axis_name]
    mesh = pv.read(source)
    if mesh.n_points == 0:
        raise ValueError(f"{source} has no points")

    mirrored = mesh.copy(deep=True)
    mirrored.points = reflect_points(np.asarray(mesh.points), axis, plane_value)
    flip_vector_components(mirrored.point_data, axis)
    flip_vector_components(mirrored.cell_data, axis)

    full = mesh.merge(mirrored, merge_points=merge_points)
    destination.parent.mkdir(parents=True, exist_ok=True)
    full.save(destination)

    print(f"{source} -> {destination}")
    print(f"mirrored across {axis_name}={plane_value:g}")
    print(f"points: {mesh.n_points} half -> {full.n_points} full")
    print(f"cells:  {mesh.n_cells} half -> {full.n_cells} full")
    print(f"bounds: {mesh.bounds} -> {full.bounds}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror a half-domain flow.vtu into a full field.")
    parser.add_argument("path", type=Path, help="Case directory or flow.vtu file.")
    parser.add_argument(
        "--axis",
        choices=sorted(AXIS_INDEX),
        default="y",
        help="Coordinate normal to the symmetry plane.",
    )
    parser.add_argument("--plane", type=float, default=0.0, help="Symmetry-plane coordinate value.")
    parser.add_argument("--input-name", default=DEFAULT_INPUT_NAME, help="Input filename for case directories.")
    parser.add_argument("--output-name", default=DEFAULT_OUTPUT_NAME, help="Output filename.")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output file.")
    parser.add_argument(
        "--merge-points",
        action="store_true",
        help="Merge coincident points on the symmetry plane.",
    )
    args = parser.parse_args()

    source, destination = flow_paths(args.path, args.input_name, args.output_name)
    mirror_flow(
        source,
        destination,
        axis_name=args.axis,
        plane_value=args.plane,
        overwrite=args.overwrite,
        merge_points=args.merge_points,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
