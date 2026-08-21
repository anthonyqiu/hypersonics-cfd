from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pyvista as pv


AXIS = {"x": 0, "y": 1, "z": 2}


def mirror_flow(
    source,
    destination,
    axis_name="y",
    plane=0.0,
    merge_points=False,
):
    mesh = pv.read(source)
    mirrored = mesh.copy(deep=True)
    axis = AXIS[axis_name]
    mirrored.points[:, axis] = 2.0 * plane - mirrored.points[:, axis]
    for data in (mirrored.point_data, mirrored.cell_data):
        for name in list(data):
            values = np.asarray(data[name])
            if values.ndim == 2 and values.shape[1] == 3:
                values = values.copy()
                values[:, axis] *= -1.0
                data[name] = values
    mesh.merge(mirrored, merge_points=merge_points).save(destination)
    print(f"wrote {destination}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--axis", choices=AXIS, default="y")
    parser.add_argument("--plane", type=float, default=0.0)
    parser.add_argument("--input-name", default="flow.vtu")
    parser.add_argument("--output-name", default="flow_full.vtu")
    parser.add_argument("--merge-points", action="store_true")
    args = parser.parse_args()
    source = (
        args.path / args.input_name if args.path.is_dir() else args.path
    )
    destination = (
        args.path / args.output_name
        if args.path.is_dir()
        else args.path.with_name(args.output_name)
    )
    mirror_flow(
        source,
        destination,
        args.axis,
        args.plane,
        args.merge_points,
    )
