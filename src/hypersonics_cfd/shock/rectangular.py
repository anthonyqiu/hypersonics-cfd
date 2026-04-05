#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pyvista as pv
from scipy.signal import find_peaks, savgol_filter

from ..case_selection import deduplicate_case_names, choose_postprocess_cases_interactively, resolve_case_path
from ..layout import StudyPaths, get_study_paths
from ..shock_geometry import (
    frame_coordinates,
    load_case_aoa_degrees,
    perpendicular_radius,
    point_from_frame,
    streamwise_basis_from_aoa,
)

try:
    from vtkmodules.vtkCommonCore import vtkObject
except ImportError:
    vtkObject = None

# --------------- USER SETTINGS ---------------
vtu_name = "flow.vtu"
density_scalar = "Density"
output_surface_name = "shock_surface_rectangular.vtp"
output_csv_name = "shock_surface_rectangular.csv"

# Node-line shock extraction controls.
stagnation_shock_node_radius = 0.10
default_spacing = 0.125
default_dx = None
default_dyz = None
reference_node_line_bins = 61
surface_sensor_min_fraction = 0.005
surface_mesh_edge_factor = 4.0
savgol_window_points = 9
savgol_poly_order = 3
streamwise_padding_factor = 1.0
line_peak_height_fraction = 0.05
line_peak_prominence_fraction = 0.02
transverse_growth_factor = 1.35
max_transverse_expansions = 4
transverse_probe_bins = 25

suppress_vtk_warnings = True
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
        description=(
            "Extract a 3D shock surface by tracking density-gradient peaks along streamwise node lines "
            "with a square-shell spiral over a rectangular pitch/span node-line grid."
        )
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
    parser.add_argument(
        "--spacing",
        type=float,
        help="Common spacing to use for both dx and dyz unless one of them is set explicitly.",
    )
    parser.add_argument(
        "--grid-bins",
        type=int,
        default=reference_node_line_bins,
        help=(
            "Legacy fallback used only to infer dx/dyz when no explicit spacing is provided. "
            "Lower values give coarser inferred spacing."
        ),
    )
    parser.add_argument(
        "--dx",
        type=float,
        help="Streamwise spacing dx for the interpolated node lines.",
    )
    parser.add_argument(
        "--dyz",
        type=float,
        help="Common y-z spacing dyz for the rectangular node-line grid.",
    )
    return parser.parse_args()


def resolve_requested_spacing(args: argparse.Namespace) -> tuple[float | None, float | None]:
    common_spacing = args.spacing if args.spacing is not None else default_spacing
    if common_spacing is not None and common_spacing <= 0.0:
        raise ValueError("default spacing and --spacing must be positive")

    dx_override = args.dx
    if dx_override is None:
        if common_spacing is not None:
            dx_override = common_spacing
        else:
            dx_override = default_dx

    dyz_override = args.dyz
    if dyz_override is None:
        if common_spacing is not None:
            dyz_override = common_spacing
        else:
            dyz_override = default_dyz

    if dx_override is not None and dx_override <= 0.0:
        raise ValueError("default dx and --dx must be positive")
    if dyz_override is not None and dyz_override <= 0.0:
        raise ValueError("default dyz and --dyz must be positive")

    return dx_override, dyz_override

def build_square_shells(ny: int, nz: int, cy: int, cz: int) -> list[list[tuple[int, int]]]:
    shells: list[list[tuple[int, int]]] = [[(cy, cz)]]
    seen = {(cy, cz)}
    max_radius = max(cy, ny - 1 - cy, cz, nz - 1 - cz)
    for layer in range(1, max_radius + 1):
        y0 = max(cy - layer, 0)
        y1 = min(cy + layer, ny - 1)
        z0 = max(cz - layer, 0)
        z1 = min(cz + layer, nz - 1)

        perimeter: list[tuple[int, int]] = []
        for zc in range(z0, z1 + 1):
            perimeter.append((y0, zc))
        for yc in range(y0 + 1, y1 + 1):
            perimeter.append((yc, z1))
        if y1 > y0:
            for zc in range(z1 - 1, z0 - 1, -1):
                perimeter.append((y1, zc))
        if z1 > z0:
            for yc in range(y1 - 1, y0, -1):
                perimeter.append((yc, z0))

        shell: list[tuple[int, int]] = []
        for cell in perimeter:
            if cell in seen:
                continue
            seen.add(cell)
            shell.append(cell)
        if shell:
            shells.append(shell)

    return shells


def choose_stagnation_shock_node(
    points: np.ndarray,
    shock_sensor: np.ndarray,
    streamwise: np.ndarray,
) -> tuple[int, float]:
    radius = perpendicular_radius(points, streamwise)
    center_mask = radius <= stagnation_shock_node_radius
    center_indices = np.flatnonzero(center_mask)
    if center_indices.size == 0:
        center_indices = np.argsort(radius)[: max(32, len(points) // 2000)]
    stagnation_node_idx = int(center_indices[np.argmax(shock_sensor[center_indices])])
    return stagnation_node_idx, float(shock_sensor[stagnation_node_idx])


def centered_axis(max_abs: float, step: float) -> np.ndarray:
    count = max(1, int(math.ceil(max_abs / step)))
    return np.arange(-count, count + 1, dtype=float) * step


def streamwise_axis(x_min: float, x_max: float, dx: float) -> np.ndarray:
    start = math.floor(x_min / dx) * dx
    stop = math.ceil(x_max / dx) * dx
    count = max(2, int(round((stop - start) / dx)) + 1)
    return start + np.arange(count, dtype=float) * dx


def derive_sampling_steps(
    active_points: np.ndarray,
    grid_bins: int,
    dx_override: float | None,
    dyz_override: float | None,
) -> tuple[float, float]:
    x_span = max(float(active_points[:, 0].max() - active_points[:, 0].min()), 1.0e-12)
    max_abs_y = max(float(np.max(np.abs(active_points[:, 1]))), 1.0e-12)
    max_abs_z = max(float(np.max(np.abs(active_points[:, 2]))), 1.0e-12)
    max_abs_yz = max(max_abs_y, max_abs_z)

    inferred_dx = x_span / max(grid_bins - 1, 1)
    inferred_dyz = (2.0 * max_abs_yz) / max(grid_bins - 1, 1)

    dx = dx_override if dx_override is not None else inferred_dx
    dyz = dyz_override if dyz_override is not None else inferred_dyz
    if dx <= 0.0 or dyz <= 0.0:
        raise ValueError("dx and dyz must both be positive")
    return float(dx), float(dyz)


def build_node_line_axes(
    active_points: np.ndarray,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
    dx: float,
    dyz: float,
    transverse_scale: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
    local_points = frame_coordinates(active_points, streamwise, normal, spanwise)
    stream_min = float(local_points[:, 0].min())
    stream_max = float(local_points[:, 0].max())
    stream_pad = max((stream_max - stream_min) * streamwise_padding_factor, dx)
    stream_values = streamwise_axis(stream_min - stream_pad, stream_max + stream_pad, dx)
    normal_values = centered_axis(float(np.max(np.abs(local_points[:, 1]))) * transverse_scale, dyz)
    span_values = centered_axis(float(np.max(np.abs(local_points[:, 2]))) * transverse_scale, dyz)
    center_normal = len(normal_values) // 2
    center_span = len(span_values) // 2
    return stream_values, normal_values, span_values, center_normal, center_span


def sample_node_lines(
    gradient_mesh: pv.DataSet,
    stream_values: np.ndarray,
    normal_values: np.ndarray,
    span_values: np.ndarray,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    nx = len(stream_values)
    ny = len(normal_values)
    nz = len(span_values)

    sample_points = np.empty((nx * ny * nz, 3), dtype=float)
    offset = 0
    line_origin_stream = np.asarray(stream_values, dtype=float)
    line_origin_stream = np.outer(line_origin_stream, streamwise)
    for iy, normal_val in enumerate(normal_values):
        for iz, span_val in enumerate(span_values):
            next_offset = offset + nx
            line_offset = (
                float(normal_val) * np.asarray(normal, dtype=float)
                + float(span_val) * np.asarray(spanwise, dtype=float)
            )
            sample_points[offset:next_offset] = line_origin_stream + line_offset
            offset = next_offset

    sampled = pv.PolyData(sample_points).sample(gradient_mesh)
    density = np.nan_to_num(np.asarray(sampled[density_scalar], dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    sensor_raw = np.nan_to_num(np.asarray(sampled["ShockSensorRaw"], dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    if "vtkValidPointMask" in sampled.array_names:
        valid_mask = np.asarray(sampled["vtkValidPointMask"], dtype=int) > 0
    else:
        valid_mask = np.isfinite(density) & np.isfinite(sensor_raw)

    return (
        density.reshape(ny, nz, nx),
        sensor_raw.reshape(ny, nz, nx),
        valid_mask.reshape(ny, nz, nx),
    )


def smooth_line_profile(values: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    smoothed = np.zeros_like(values, dtype=float)
    valid_idx = np.flatnonzero(valid_mask)
    if valid_idx.size == 0:
        return smoothed

    start = int(valid_idx[0])
    stop = int(valid_idx[-1]) + 1
    segment = np.asarray(values[start:stop], dtype=float)
    if segment.size < 3:
        smoothed[start:stop] = segment
        return smoothed

    window = min(savgol_window_points, segment.size if segment.size % 2 == 1 else segment.size - 1)
    if window < 3:
        smoothed[start:stop] = segment
        return smoothed

    polyorder = min(savgol_poly_order, window - 1)
    smoothed[start:stop] = savgol_filter(segment, window_length=window, polyorder=polyorder, mode="interp")
    return smoothed


def find_first_local_peak(
    x_values: np.ndarray,
    density_line: np.ndarray,
    sensor_raw_line: np.ndarray,
    valid_mask: np.ndarray,
    min_height: float,
    fallback_global: bool,
) -> dict[str, float | int] | None:
    valid_idx = np.flatnonzero(valid_mask)
    if valid_idx.size == 0:
        return None

    smoothed = smooth_line_profile(sensor_raw_line, valid_mask)
    start = int(valid_idx[0])
    stop = int(valid_idx[-1]) + 1
    segment = smoothed[start:stop]
    local_max = float(np.max(segment))
    height_threshold = max(float(min_height), local_max * line_peak_height_fraction)
    prominence_threshold = local_max * line_peak_prominence_fraction

    peaks, _ = find_peaks(segment, height=height_threshold, prominence=prominence_threshold)
    candidate_indices = [start + int(idx) for idx in peaks]

    if candidate_indices:
        peak_idx = int(candidate_indices[0])
    elif fallback_global:
        peak_idx = int(start + np.argmax(segment))
        if smoothed[peak_idx] <= 0.0:
            return None
    else:
        return None

    return {
        "x": float(x_values[peak_idx]),
        "density": float(density_line[peak_idx]),
        "shock_sensor_raw": float(sensor_raw_line[peak_idx]),
        "shock_sensor_smoothed": float(smoothed[peak_idx]),
        "x_index": peak_idx,
    }


def has_adjacent_shock(
    iy: int,
    iz: int,
    shock_node: np.ndarray,
    shock_node_index_by_line: dict[tuple[int, int], int],
    accepted_shock_nodes: list[np.ndarray],
    radius: float,
    ny: int,
    nz: int,
) -> bool:
    neighbor_points: list[np.ndarray] = []
    for jy in range(max(0, iy - 1), min(ny, iy + 2)):
        for jz in range(max(0, iz - 1), min(nz, iz + 2)):
            if (jy, jz) == (iy, iz):
                continue
            local_idx = shock_node_index_by_line.get((jy, jz))
            if local_idx is not None:
                neighbor_points.append(accepted_shock_nodes[local_idx])

    if not neighbor_points:
        return False

    neighbors = np.asarray(neighbor_points, dtype=float)
    distances = np.linalg.norm(neighbors - shock_node, axis=1)
    return bool(np.any(distances <= radius))


def extract_shock_nodes(
    stream_values: np.ndarray,
    normal_values: np.ndarray,
    span_values: np.ndarray,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
    density_on_node_lines: np.ndarray,
    shock_sensor_on_node_lines: np.ndarray,
    valid_sample_mask: np.ndarray,
) -> tuple[pv.PolyData, dict[str, float | int]]:
    ny, nz, nx = density_on_node_lines.shape
    cy = ny // 2
    cz = nz // 2
    dx = float(stream_values[1] - stream_values[0]) if len(stream_values) > 1 else 0.0
    dyz = float(normal_values[1] - normal_values[0]) if len(normal_values) > 1 else 0.0
    node_line_diag = math.hypot(dx, dyz)
    neighbor_radius = 3.0 * (dx + dyz)

    center_candidate = find_first_local_peak(
        stream_values,
        density_on_node_lines[cy, cz],
        shock_sensor_on_node_lines[cy, cz],
        valid_sample_mask[cy, cz],
        min_height=0.0,
        fallback_global=True,
    )
    if center_candidate is None:
        raise ValueError("could not find a shock peak on the center node line")

    center_peak = float(center_candidate["shock_sensor_smoothed"])
    sensor_floor = center_peak * surface_sensor_min_fraction

    shock_node_rows: list[dict[str, float | int]] = []
    shock_node_index_by_line: dict[tuple[int, int], int] = {}
    accepted_shock_nodes: list[np.ndarray] = []

    center_shock_node = point_from_frame(
        center_candidate["x"],
        normal_values[cy],
        span_values[cz],
        streamwise,
        normal,
        spanwise,
    )
    accepted_shock_nodes.append(center_shock_node)
    shock_node_index_by_line[(cy, cz)] = 0
    shock_node_rows.append(
        {
            "x": float(center_shock_node[0]),
            "y": float(center_shock_node[1]),
            "z": float(center_shock_node[2]),
            "density": float(center_candidate["density"]),
            "shock_sensor": float(center_candidate["shock_sensor_smoothed"]),
            "shock_sensor_raw": float(center_candidate["shock_sensor_raw"]),
            "bin_i": cy,
            "bin_j": cz,
            "line_index": int(center_candidate["x_index"]),
            "shell_layer": 0,
            "spiral_step": 0,
            "radius_yz": float(math.hypot(normal_values[cy], span_values[cz])),
        }
    )

    spiral_step = 1
    square_shells = build_square_shells(ny, nz, cy, cz)
    for shell_layer, square_shell in enumerate(square_shells[1:], start=1):
        accepted_in_shell: list[dict[str, float | int]] = []
        reference_map = dict(shock_node_index_by_line)
        for iy, iz in square_shell:
            candidate = find_first_local_peak(
                stream_values,
                density_on_node_lines[iy, iz],
                shock_sensor_on_node_lines[iy, iz],
                valid_sample_mask[iy, iz],
                min_height=sensor_floor,
                fallback_global=False,
            )
            if candidate is None:
                continue

            shock_node = point_from_frame(
                candidate["x"],
                normal_values[iy],
                span_values[iz],
                streamwise,
                normal,
                spanwise,
            )
            if not has_adjacent_shock(
                iy,
                iz,
                shock_node,
                reference_map,
                accepted_shock_nodes,
                neighbor_radius,
                ny,
                nz,
            ):
                continue

            accepted_in_shell.append(
                {
                    "x": float(shock_node[0]),
                    "y": float(shock_node[1]),
                    "z": float(shock_node[2]),
                    "density": float(candidate["density"]),
                    "shock_sensor": float(candidate["shock_sensor_smoothed"]),
                    "shock_sensor_raw": float(candidate["shock_sensor_raw"]),
                    "bin_i": iy,
                    "bin_j": iz,
                    "line_index": int(candidate["x_index"]),
                    "shell_layer": shell_layer,
                    "spiral_step": spiral_step,
                    "radius_yz": float(math.hypot(normal_values[iy], span_values[iz])),
                }
            )
            spiral_step += 1

        if not accepted_in_shell:
            break

        for row in accepted_in_shell:
            local_idx = len(accepted_shock_nodes)
            point = np.asarray([row["x"], row["y"], row["z"]], dtype=float)
            accepted_shock_nodes.append(point)
            shock_node_index_by_line[(int(row["bin_i"]), int(row["bin_j"]))] = local_idx
            shock_node_rows.append(row)

    poly = pv.PolyData(np.asarray(accepted_shock_nodes))
    poly.point_data["Density"] = np.asarray([row["density"] for row in shock_node_rows], dtype=float)
    poly.point_data["ShockSensor"] = np.asarray([row["shock_sensor"] for row in shock_node_rows], dtype=float)
    poly.point_data["ShockSensorRaw"] = np.asarray([row["shock_sensor_raw"] for row in shock_node_rows], dtype=float)
    poly.point_data["RadiusYZ"] = np.asarray([row["radius_yz"] for row in shock_node_rows], dtype=float)
    poly.point_data["SpiralStep"] = np.asarray([row["spiral_step"] for row in shock_node_rows], dtype=int)
    poly.point_data["ShellLayer"] = np.asarray([row["shell_layer"] for row in shock_node_rows], dtype=int)
    poly.point_data["BinI"] = np.asarray([row["bin_i"] for row in shock_node_rows], dtype=int)
    poly.point_data["BinJ"] = np.asarray([row["bin_j"] for row in shock_node_rows], dtype=int)
    poly.point_data["LineIndex"] = np.asarray([row["line_index"] for row in shock_node_rows], dtype=int)

    faces: list[int] = []
    for iy in range(ny - 1):
        for iz in range(nz - 1):
            corners = [
                shock_node_index_by_line.get((iy, iz)),
                shock_node_index_by_line.get((iy + 1, iz)),
                shock_node_index_by_line.get((iy + 1, iz + 1)),
                shock_node_index_by_line.get((iy, iz + 1)),
            ]
            if any(corner is None for corner in corners):
                continue

            p0, p1, p2, p3 = [poly.points[int(corner)] for corner in corners]
            max_edge = max(
                np.linalg.norm(p0 - p1),
                np.linalg.norm(p1 - p2),
                np.linalg.norm(p2 - p3),
                np.linalg.norm(p3 - p0),
                np.linalg.norm(p0 - p2),
                np.linalg.norm(p1 - p3),
            )
            if max_edge > surface_mesh_edge_factor * node_line_diag:
                continue

            c0, c1, c2, c3 = [int(corner) for corner in corners]
            faces.extend([3, c0, c1, c2, 3, c0, c2, c3])

    if faces:
        poly.faces = np.asarray(faces, dtype=np.int64)

    summary: dict[str, float | int] = {
        "point_count": poly.n_points,
        "cell_count": poly.n_cells,
        "center_peak": center_peak,
        "sensor_floor": sensor_floor,
        "neighbor_radius": neighbor_radius,
        "dx": dx,
        "dyz": dyz,
        "x_node_count": nx,
        "y_node_count": ny,
        "z_node_count": nz,
        "max_shell_layer": max(int(row["shell_layer"]) for row in shock_node_rows),
        "touches_boundary": int(
            any(
                int(row["bin_i"]) in {0, ny - 1} or int(row["bin_j"]) in {0, nz - 1}
                for row in shock_node_rows
            )
        ),
    }
    return poly, summary


def choose_transverse_scale(
    gradient_mesh: pv.DataSet,
    active_points: np.ndarray,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
    grid_bins: int,
    dx_override: float | None,
    dyz_override: float | None,
) -> float:
    probe_bins = min(grid_bins, transverse_probe_bins)
    probe_dx, probe_dyz = derive_sampling_steps(active_points, probe_bins, dx_override, dyz_override)
    scale = 1.0
    for _ in range(max_transverse_expansions + 1):
        stream_values, normal_values, span_values, _, _ = build_node_line_axes(
            active_points, streamwise, normal, spanwise, probe_dx, probe_dyz, scale
        )
        density_on_node_lines, shock_sensor_on_node_lines, valid_sample_mask = sample_node_lines(
            gradient_mesh, stream_values, normal_values, span_values, streamwise, normal, spanwise
        )
        _, summary = extract_shock_nodes(
            stream_values,
            normal_values,
            span_values,
            streamwise,
            normal,
            spanwise,
            density_on_node_lines,
            shock_sensor_on_node_lines,
            valid_sample_mask,
        )
        if not int(summary["touches_boundary"]):
            return scale
        scale *= transverse_growth_factor
    return scale


def write_surface_outputs(case_path: Path, surface: pv.PolyData):
    surface_path = case_path / output_surface_name
    csv_path = case_path / output_csv_name
    surface.save(surface_path)

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "x",
                "y",
                "z",
                "density",
                "shock_sensor",
                "shock_sensor_raw",
                "radius_yz",
                "spiral_step",
                "shell_layer",
                "line_index",
                "bin_i",
                "bin_j",
            ]
        )
        density = np.asarray(surface["Density"])
        sensor = np.asarray(surface["ShockSensor"])
        sensor_raw = np.asarray(surface["ShockSensorRaw"])
        radius = np.asarray(surface["RadiusYZ"])
        steps = np.asarray(surface["SpiralStep"])
        shell_layer = np.asarray(surface["ShellLayer"])
        line_index = np.asarray(surface["LineIndex"])
        bin_i = np.asarray(surface["BinI"])
        bin_j = np.asarray(surface["BinJ"])
        for idx, point in enumerate(np.asarray(surface.points)):
            writer.writerow(
                [
                    float(point[0]),
                    float(point[1]),
                    float(point[2]),
                    float(density[idx]),
                    float(sensor[idx]),
                    float(sensor_raw[idx]),
                    float(radius[idx]),
                    int(steps[idx]),
                    int(shell_layer[idx]),
                    int(line_index[idx]),
                    int(bin_i[idx]),
                    int(bin_j[idx]),
                ]
            )

    return surface_path, csv_path


def process_case(
    paths: StudyPaths,
    case_dir: str,
    grid_bins: int,
    dx_override: float | None,
    dyz_override: float | None,
):
    case_path = resolve_case_path(paths.study_root, paths.cases_dir, case_dir)
    vtu_path = case_path / vtu_name
    if not vtu_path.exists():
        print(f"  [skip] no {vtu_name} in {case_path.name}")
        return

    print(f"  [read] {vtu_path}")
    mesh = pv.read(vtu_path)
    if density_scalar not in mesh.point_data and density_scalar in mesh.cell_data:
        mesh = mesh.cell_data_to_point_data()

    if density_scalar not in mesh.array_names:
        available = ", ".join(sorted(mesh.array_names))
        raise KeyError(f"{density_scalar!r} not found. Available arrays: {available}")

    with vtk_warning_mode(suppress_vtk_warnings):
        gradient_mesh = mesh.compute_derivative(scalars=density_scalar, gradient=True)

    aoa_degrees = load_case_aoa_degrees(paths.generated_config_dir, case_path)
    streamwise, normal, spanwise = streamwise_basis_from_aoa(aoa_degrees)
    points = np.asarray(gradient_mesh.points)
    gradient = np.asarray(gradient_mesh["gradient"], dtype=float)
    gradient = np.nan_to_num(gradient, nan=0.0, posinf=0.0, neginf=0.0)
    sensor_raw = np.linalg.norm(gradient, axis=1)
    gradient_mesh["ShockSensorRaw"] = sensor_raw

    _, center_peak = choose_stagnation_shock_node(points, sensor_raw, streamwise)
    active_mask = sensor_raw >= center_peak * surface_sensor_min_fraction
    active_points = points[active_mask]
    if active_points.size == 0:
        raise ValueError("no active points passed the surface sensor threshold")

    dx, dyz = derive_sampling_steps(active_points, grid_bins, dx_override, dyz_override)
    transverse_scale = choose_transverse_scale(
        gradient_mesh, active_points, streamwise, normal, spanwise, grid_bins, dx_override, dyz_override
    )
    stream_values, normal_values, span_values, _, _ = build_node_line_axes(
        active_points, streamwise, normal, spanwise, dx, dyz, transverse_scale
    )
    density_on_node_lines, shock_sensor_on_node_lines, valid_sample_mask = sample_node_lines(
        gradient_mesh, stream_values, normal_values, span_values, streamwise, normal, spanwise
    )
    surface, summary = extract_shock_nodes(
        stream_values,
        normal_values,
        span_values,
        streamwise,
        normal,
        spanwise,
        density_on_node_lines,
        shock_sensor_on_node_lines,
        valid_sample_mask,
    )
    surface_path, csv_path = write_surface_outputs(case_path, surface)

    print(
        f"  [ok ] wrote {surface_path} ({surface.n_points} pts, {surface.n_cells} tris, "
        f"aoa={aoa_degrees:.1f}, center_peak={summary['center_peak']:.3f}, dx={summary['dx']:.4f}, "
        f"dyz={summary['dyz']:.4f}, neighbor_radius={summary['neighbor_radius']:.4f}, "
        f"node_lines=({summary['x_node_count']} x {summary['y_node_count']} x {summary['z_node_count']}), "
        f"max_shell={summary['max_shell_layer']}, touches_boundary={summary['touches_boundary']}, "
        f"transverse_scale={transverse_scale:.3f})"
    )
    print(f"  [ok ] wrote {csv_path}")


def main() -> int:
    args = parse_args()
    paths = get_study_paths(args.study)
    dx_override, dyz_override = resolve_requested_spacing(args)

    print("\n╔══════════════════════════════════════════════╗")
    print("║   Rectangular Shock Extractor (Legacy)      ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"Study: {paths.study_name}")
    print(f"Density scalar: {density_scalar}")
    if dx_override is None and dyz_override is None:
        spacing_label = f"inferred from reference node lines={args.grid_bins}"
    else:
        spacing_label = f"requested dx={dx_override if dx_override is not None else 'auto'}, dyz={dyz_override if dyz_override is not None else 'auto'}"
    print(
        f"Spacing: {spacing_label}, "
        f"sensor floor: {surface_sensor_min_fraction:g} of center peak, "
        f"savgol window/poly: {savgol_window_points}/{savgol_poly_order}"
    )

    cases = args.cases or choose_postprocess_cases_interactively(paths.cases_dir, vtu_name)
    cases = deduplicate_case_names(paths.study_root, paths.cases_dir, cases)
    if not cases:
        return 0

    print(f"\nProcessing {len(cases)} case(s)...\n")
    for case in cases:
        print(f"-> {case}")
        process_case(paths, case, args.grid_bins, dx_override, dyz_override)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
