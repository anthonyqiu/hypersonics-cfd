"""Shock-surface file input and output."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pyvista as pv


def partial_output_path(path: Path):
    return path.with_name(f"{path.stem}.part{path.suffix}")


def write_surface_outputs(
    output_dir: Path,
    surface: pv.PolyData,
    surface_name="shock_surface.vtp",
    csv_name="shock_surface.csv",
):
    """Write one extracted surface as VTP and a flat point-data CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    surface_path = output_dir / surface_name
    csv_path = output_dir / csv_name
    partial_surface = partial_output_path(surface_path)
    partial_csv = partial_output_path(csv_path)
    partial_surface.unlink(missing_ok=True)
    partial_csv.unlink(missing_ok=True)
    surface.save(partial_surface)

    columns = (
        ("stream_coord", "StreamCoord", float),
        ("density", "Density", float),
        ("shock_sensor", "ShockSensor", float),
        ("shock_sensor_raw", "ShockSensorRaw", float),
        ("shock_sensor_prominence", "ShockSensorProminence", float),
        ("shock_sensor_prominence_ratio", "ShockSensorProminenceRatio", float),
        ("radius_surface", "RadiusSurface", float),
        ("azimuth_radians", "AzimuthRadians", float),
        ("shell_layer", "ShellLayer", int),
        ("ray_index", "RayIndex", int),
        ("line_index", "LineIndex", int),
        ("line_mode_code", "LineModeCode", int),
        ("prediction_error", "PredictionError", float),
    )
    arrays = {name: np.asarray(surface[array]) for name, array, _ in columns}
    with partial_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["x", "y", "z", *[name for name, _, _ in columns]])
        for index, point in enumerate(np.asarray(surface.points)):
            writer.writerow(
                [
                    float(point[0]),
                    float(point[1]),
                    float(point[2]),
                    *[
                        cast(arrays[name][index])
                        for name, _, cast in columns
                    ],
                ]
            )

    partial_surface.replace(surface_path)
    partial_csv.replace(csv_path)
    return surface_path, csv_path
