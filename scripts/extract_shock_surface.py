#!/usr/bin/env python3
"""
Extract a 3D bow-shock surface from one CFD volume solution.

If you are reading this file as a beginner, the big picture is:

1. Read one `flow.vtu` file.
2. Compute `|grad(rho)|`, the magnitude of the density gradient.
3. Use that quantity as a "shock sensor" because shocks produce strong density jumps.
4. Find an easy first shock point near the stagnation line.
5. March outward shell by shell and find one shock point per ray when possible.
6. Connect the accepted points into a triangulated surface.

Glossary used throughout this file:

- shock sensor:
  The magnitude of the density gradient, `|grad(rho)|`.
- node line:
  A short 1D sampling line placed through the 3D flow field.
- shock node:
  One accepted shock point found from one node line.
- shell:
  One ring of shock nodes at a fixed distance from the streamwise axis.
- ray:
  One azimuth direction around the body.
- panel-guided line:
  A node line whose direction is predicted from earlier accepted shock nodes instead of always
  pointing streamwise.
- `dt`:
  Spacing between neighboring shells.
- `dn`:
  Spacing between neighboring samples along one node line.
"""
from __future__ import annotations

import csv
import math
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pyvista as pv
from scipy.signal import find_peaks, savgol_filter

from case_selection import deduplicate_case_names, choose_postprocess_cases_interactively, resolve_case_path
from layout import StudyPaths, choose_study_paths_interactively, get_study_paths

try:
    from vtkmodules.vtkCommonCore import vtkObject
except ImportError:
    vtkObject = None

# --------------- USER SETTINGS ---------------
# This is the main tuning block for the extractor. The code below uses these values directly,
# so this is the first place to look if you want to change spacing or sensitivity.
vtu_name = "flow.vtu"
density_scalar = "Density"
output_surface_name = "shock_surface.vtp"
output_csv_name = "shock_surface.csv"

# Search radius around the streamwise axis for the very first stagnation shock point.
stagnation_shock_node_radius = 0.10

# `dt` = shell spacing. It controls how far apart neighboring shock rings are.
default_dt = 0.10
# `dn` = node-line spacing. It controls how finely we sample each 1D probe line.
default_dn = 0.025

# Ignore very weak gradients far from the real shock.
surface_sensor_min_fraction = 0.005

# Reject triangles that stretch too far across local gaps in the sampled surface.
surface_mesh_edge_factor = 6.0

# Savitzky-Golay smoothing settings for the 1D shock-sensor profile on each line.
savgol_window_points = 9
savgol_poly_order = 3
streamwise_padding_factor = 1.0

# Peak-detection thresholds on each 1D line sample.
line_peak_height_fraction = 0.05
line_peak_prominence_fraction = 0.02

# Stagnation search refinement:
# - first scan the long stagnation line with a coarse spacing
# - then resample a smaller window around that coarse peak using the normal `dn`
stagnation_coarse_step_factor = 10.0

# Panel-guided search-line settings used after the first shell.
search_line_half_length_factor = 5.0
panel_prediction_tolerance_dt_factor = 3.0
panel_fit_node_count = 5
minimum_azimuth_rays = 12

suppress_vtk_warnings = True
# ---------------------------------------------

LINE_MODE_STAGNATION = 0
LINE_MODE_STREAMWISE = 1
LINE_MODE_PANEL_GUIDED = 2

PEAK_MODE_FIRST_UPSTREAM = "first_upstream"
PEAK_MODE_NEAREST_CENTER = "nearest_center"

AOA_LINE_RE = re.compile(r"^\s*AOA\s*=\s*([-+0-9.eE]+)")
AOA_NAME_RE = re.compile(r"_aoa(\d+(?:p\d+)?)")


# --- Lightweight helpers -----------------------------------------------------
@contextmanager
def vtk_warning_mode(enabled: bool):
    """Temporarily hide noisy VTK warnings while heavy sampling/derivative calls run."""
    if not enabled or vtkObject is None:
        yield
        return

    previous = vtkObject.GetGlobalWarningDisplay()
    vtkObject.SetGlobalWarningDisplay(0)
    try:
        yield
    finally:
        vtkObject.SetGlobalWarningDisplay(previous)


# --- AoA parsing and local coordinate-frame helpers --------------------------
def parse_case_aoa_from_text(text: str) -> float | None:
    """Read the first `AOA = ...` value from a config-like text block."""
    for line in text.splitlines():
        match = AOA_LINE_RE.match(line)
        if match is not None:
            return float(match.group(1))
    return None


def parse_case_aoa_from_name(case_name: str) -> float | None:
    """Fallback AoA parser for case names like `m3_aoa15` or `m1.5_aoa24p5`."""
    match = AOA_NAME_RE.search(case_name)
    if match is None:
        return None
    return float(match.group(1).replace("p", "."))


def load_case_aoa_degrees(generated_config_dir: Path, case_path: Path) -> float:
    """
    Get the case AoA, preferring config files over the case folder name.

    This keeps the extractor tied to the actual run configuration when that information is
    available, but still gives us a safe fallback for older case layouts.
    """
    generated_cfg = Path(generated_config_dir) / f"{case_path.name}.cfg"
    local_cfg = case_path / "config.cfg"
    candidate_paths = (generated_cfg, local_cfg)

    for path in candidate_paths:
        if not path.exists():
            continue
        aoa = parse_case_aoa_from_text(path.read_text(encoding="utf-8"))
        if aoa is not None:
            return float(aoa)

    aoa_from_name = parse_case_aoa_from_name(case_path.name)
    if aoa_from_name is not None:
        return float(aoa_from_name)
    return 0.0


def streamwise_basis_from_aoa(aoa_degrees: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Build the AoA-aware orthonormal basis used by the extractor.

    The frame is:
    - `streamwise`: freestream direction, rotated in the x-z plane
    - `normal`: up/down direction in the AoA plane
    - `spanwise`: unchanged global y direction
    """
    alpha = math.radians(float(aoa_degrees))
    streamwise = np.asarray([math.cos(alpha), 0.0, math.sin(alpha)], dtype=float)
    streamwise /= np.linalg.norm(streamwise)

    spanwise = np.asarray([0.0, 1.0, 0.0], dtype=float)
    normal = np.cross(streamwise, spanwise)
    normal /= np.linalg.norm(normal)
    return streamwise, normal, spanwise


def frame_coordinates(
    points: np.ndarray,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
) -> np.ndarray:
    """Project global xyz points into the local (streamwise, normal, spanwise) frame."""
    pts = np.asarray(points, dtype=float)
    return np.column_stack((pts @ streamwise, pts @ normal, pts @ spanwise))


def perpendicular_radius(points: np.ndarray, streamwise: np.ndarray) -> np.ndarray:
    """
    Distance from each point to the AoA-aligned streamwise axis.

    This is the sideways distance from the tilted centerline, not distance from the body.
    """
    pts = np.asarray(points, dtype=float)
    axial = np.outer(pts @ streamwise, streamwise)
    return np.linalg.norm(pts - axial, axis=1)


def choose_stagnation_shock_node(
    points: np.ndarray,
    shock_sensor: np.ndarray,
    streamwise: np.ndarray,
) -> tuple[int, float]:
    """
    Pick the first trusted shock point near the stagnation region.

    We look close to the AoA-aligned streamwise axis first because the bow shock should be
    easiest to identify there. If that narrow tube contains no points, we fall back to the
    points closest to the axis.
    """
    radius = perpendicular_radius(points, streamwise)
    center_mask = radius <= stagnation_shock_node_radius
    center_indices = np.flatnonzero(center_mask)
    if center_indices.size == 0:
        center_indices = np.argsort(radius)[: max(32, len(points) // 2000)]
    stagnation_node_idx = int(center_indices[np.argmax(shock_sensor[center_indices])])
    return stagnation_node_idx, float(shock_sensor[stagnation_node_idx])


def configured_sampling_steps() -> tuple[float, float]:
    """
    Read the user-tuned sampling spacings directly from the settings block.

    Returns:
    - `dt`: spacing between neighboring shell layers
    - `dn`: spacing between neighboring samples along one node line
    """
    return float(default_dt), float(default_dn)


def progress(message: str):
    """Print progress immediately so long runs are visible in the terminal and SLURM logs."""
    print(message, flush=True)


@contextmanager
def timed_stage(stage_times: dict[str, float], stage_name: str):
    """
    Time one coarse pipeline stage and print the elapsed time when it finishes.

    This is intentionally lightweight: it is only meant to answer "where is the case-level
    runtime going?" without cluttering the extractor with lots of nested instrumentation.
    """
    stage_start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_seconds = time.perf_counter() - stage_start
        stage_times[stage_name] = elapsed_seconds
        progress(f"  [time ] {stage_name}: {elapsed_seconds:.1f} s")


# --- Build simple 1D node lines -----------------------------------------------
def build_streamwise_window(
    active_points: np.ndarray,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
    dn: float,
) -> tuple[float, float]:
    """
    Build the baseline streamwise search window.

    Even the panel method needs a "plain streamwise" line at stagnation and on the first shell.
    This function decides how long those lines should be so they cover the active shock region
    plus a little extra margin.
    """
    local_points = frame_coordinates(active_points, streamwise, normal, spanwise)
    stream_min = float(local_points[:, 0].min())
    stream_max = float(local_points[:, 0].max())
    stream_pad = max((stream_max - stream_min) * streamwise_padding_factor, dn)
    start = stream_min - stream_pad
    stop = stream_max + stream_pad
    center = 0.5 * (start + stop)
    half_length = max(0.5 * (stop - start), dn)
    return center, half_length


def build_surface_azimuth_rays(reference_radius: float, dt: float) -> np.ndarray:
    """Choose the ray directions around the body so outer-shell tangent spacing is about dt."""
    reference_radius = max(float(reference_radius), float(dt))
    azimuth_count = max(minimum_azimuth_rays, int(math.ceil((2.0 * math.pi * reference_radius) / dt)))
    return np.linspace(0.0, 2.0 * math.pi, azimuth_count, endpoint=False, dtype=float)


def radial_unit_vector(theta: float, normal: np.ndarray, spanwise: np.ndarray) -> np.ndarray:
    """Unit vector in the local normal-spanwise plane for one azimuth angle."""
    return math.cos(theta) * np.asarray(normal, dtype=float) + math.sin(theta) * np.asarray(spanwise, dtype=float)


def sample_line(
    gradient_mesh: pv.DataSet,
    line_center: np.ndarray,
    line_direction: np.ndarray,
    half_length: float,
    normal_step: float,
) -> dict[str, np.ndarray]:
    """
    Interpolate the 3D flow-derived shock sensor onto one 1D node line.

    The returned arrays all live on the same line parameter:
    - `line_coordinates`: signed distance along the line
    - `points`: xyz position of each sample
    - `density`, `shock_sensor_raw`: interpolated field values
    - `valid_mask`: whether VTK says the interpolation is trustworthy there
    """
    direction = np.asarray(line_direction, dtype=float)
    direction_norm = np.linalg.norm(direction)
    if direction_norm <= 0.0:
        raise ValueError("node-line direction must be nonzero")
    direction /= direction_norm

    # Use an odd sample count so the line has a true middle sample at coordinate 0.
    count = max(3, int(math.ceil((2.0 * half_length) / normal_step)) + 1)
    if count % 2 == 0:
        count += 1
    line_coordinates = np.linspace(-half_length, half_length, count, dtype=float)
    sample_points = np.asarray(line_center, dtype=float) + np.outer(line_coordinates, direction)

    sampled = pv.PolyData(sample_points).sample(gradient_mesh)
    density = np.nan_to_num(np.asarray(sampled[density_scalar], dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    shock_sensor_raw = np.nan_to_num(
        np.asarray(sampled["ShockSensorRaw"], dtype=float), nan=0.0, posinf=0.0, neginf=0.0
    )
    if "vtkValidPointMask" in sampled.array_names:
        valid_mask = np.asarray(sampled["vtkValidPointMask"], dtype=int) > 0
    else:
        valid_mask = np.isfinite(density) & np.isfinite(shock_sensor_raw)

    return {
        "points": sample_points,
        "line_coordinates": line_coordinates,
        "density": density,
        "shock_sensor_raw": shock_sensor_raw,
        "valid_mask": valid_mask,
    }


def find_stagnation_candidate(
    gradient_mesh: pv.DataSet,
    stream_center: float,
    stream_half_length: float,
    streamwise: np.ndarray,
    dn: float,
) -> dict[str, float | int | np.ndarray]:
    """
    Find the first stagnation shock node with a coarse-to-fine streamwise search.

    The full stagnation line can be long, so the coarse pass cheaply localizes the shock.
    We then resample only one coarse interval around that location using the normal fine `dn`.
    """
    coarse_step = max(dn, stagnation_coarse_step_factor * dn)
    line_center = np.asarray(stream_center, dtype=float) * np.asarray(streamwise, dtype=float)

    progress(
        f"  [stage] sampling stagnation node line (coarse pass, step={coarse_step:.4f}, "
        f"half_length={stream_half_length:.4f})"
    )
    coarse_sample = sample_line(
        gradient_mesh,
        line_center,
        np.asarray(streamwise, dtype=float),
        stream_half_length,
        coarse_step,
    )
    coarse_candidate = find_shock_node_on_line(
        coarse_sample,
        min_height=0.0,
        selection_mode=PEAK_MODE_FIRST_UPSTREAM,
        fallback_global=True,
    )
    if coarse_candidate is None:
        raise ValueError("could not find a shock node on the coarse stagnation node line")

    refine_half_length = min(stream_half_length, coarse_step)
    refine_center = np.asarray(coarse_candidate["point"], dtype=float)
    progress(
        f"  [stage] refining stagnation node line around coarse peak "
        f"(half_length={refine_half_length:.4f}, step={dn:.4f})"
    )
    refined_sample = sample_line(
        gradient_mesh,
        refine_center,
        np.asarray(streamwise, dtype=float),
        refine_half_length,
        dn,
    )
    refined_candidate = find_shock_node_on_line(
        refined_sample,
        min_height=0.0,
        selection_mode=PEAK_MODE_FIRST_UPSTREAM,
        fallback_global=True,
    )
    if refined_candidate is None:
        return coarse_candidate
    return refined_candidate


def smooth_line_profile(values: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    """
    Smooth only the valid portion of a node-line profile.

    Invalid samples are left at zero so they cannot accidentally produce fake peaks.
    """
    smoothed = np.zeros_like(values, dtype=float)
    valid_idx = np.flatnonzero(valid_mask)
    if valid_idx.size == 0:
        return smoothed

    # Only smooth the continuous valid part of the sampled line. We do not want
    # invalid VTK samples near the ends to influence the peak location.
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


def find_shock_node_on_line(
    line_sample: dict[str, np.ndarray],
    min_height: float,
    selection_mode: str,
    fallback_global: bool,
) -> dict[str, float | int | np.ndarray] | None:
    """
    Find one shock node on a 1D node-line sample.

    The smoothing, thresholding, and peak detection are the same for every node line. The only
    thing that changes is *which* acceptable peak we prefer:
    - `first_upstream`: used for stagnation and shell 1 streamwise lines
    - `nearest_center`: used for panel-guided lines centered near a predicted shock location
    """
    valid_idx = np.flatnonzero(line_sample["valid_mask"])
    if valid_idx.size == 0:
        return None

    smoothed = smooth_line_profile(line_sample["shock_sensor_raw"], line_sample["valid_mask"])
    start = int(valid_idx[0])
    stop = int(valid_idx[-1]) + 1
    segment = smoothed[start:stop]
    local_max = float(np.max(segment))
    height_threshold = max(float(min_height), local_max * line_peak_height_fraction)
    prominence_threshold = local_max * line_peak_prominence_fraction

    # `find_peaks` returns all acceptable local maxima. We then apply a second rule
    # to choose which peak is the physical shock for this particular line.
    peaks, _ = find_peaks(segment, height=height_threshold, prominence=prominence_threshold)
    candidate_indices = [start + int(idx) for idx in peaks]
    if candidate_indices:
        if selection_mode == PEAK_MODE_FIRST_UPSTREAM:
            peak_idx = int(candidate_indices[0])
        elif selection_mode == PEAK_MODE_NEAREST_CENTER:
            peak_idx = min(candidate_indices, key=lambda idx: abs(float(line_sample["line_coordinates"][idx])))
        else:
            raise ValueError(f"unknown peak selection mode: {selection_mode}")
    elif fallback_global:
        peak_idx = int(start + np.argmax(segment))
        if smoothed[peak_idx] <= 0.0:
            return None
    else:
        return None

    return {
        "point": line_sample["points"][peak_idx],
        "density": float(line_sample["density"][peak_idx]),
        "shock_sensor_raw": float(line_sample["shock_sensor_raw"][peak_idx]),
        "shock_sensor_smoothed": float(smoothed[peak_idx]),
        "sample_index": peak_idx,
        "line_coordinate": float(line_sample["line_coordinates"][peak_idx]),
    }


# --- Panel fitting and predictor/corrector marching ---------------------------
def panel_history_for_ray(
    stagnation_row: dict[str, float | int],
    ray_history: dict[int, list[dict[str, float | int]]],
    ray_index: int,
) -> list[dict[str, float | int]]:
    """Collect the stagnation point plus this ray's previously accepted shock nodes."""
    return [stagnation_row] + list(ray_history.get(ray_index, []))


def fit_panel_model(
    history_rows: list[dict[str, float | int]],
    target_radius: float,
) -> dict[str, float] | None:
    """
    Fit a simple local panel model in (radius_surface, stream_coord) space.

    The fit is intentionally lightweight: a straight line through the last few accepted points
    on one ray. From that line we get:
    - the predicted streamwise location at the next shell radius
    - the normal direction of the line in the local (stream, radial) plane
    """
    if len(history_rows) < 2:
        return None

    # Use only the most recent accepted points on this ray. Older points are still
    # useful physically, but the local shock shape near the current shell matters most.
    rows = history_rows[-panel_fit_node_count:]
    radii = np.asarray([float(row["radius_surface"]) for row in rows], dtype=float)
    stream_coords = np.asarray([float(row["stream_coord"]) for row in rows], dtype=float)

    unique_radii = np.unique(radii)
    if unique_radii.size < 2:
        return None

    # We fit streamwise position as a function of surface radius on this ray.
    slope, intercept = np.polyfit(radii, stream_coords, deg=1)
    predicted_stream = float(slope * target_radius + intercept)
    # In the local (x, r) view, the panel tangent is [slope, 1]. A perpendicular vector
    # becomes the search-line direction used to probe across the shock.
    normal_xr = np.asarray([1.0, -float(slope)], dtype=float)
    normal_xr /= np.linalg.norm(normal_xr)
    return {
        "predicted_stream": predicted_stream,
        "slope": float(slope),
        "normal_stream": float(normal_xr[0]),
        "normal_radial": float(normal_xr[1]),
    }


def build_panel_line(
    panel_model: dict[str, float],
    theta: float,
    target_radius: float,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert the 2D panel prediction back into a real 3D node line."""
    radial_unit = radial_unit_vector(theta, normal, spanwise)
    line_center = (
        float(panel_model["predicted_stream"]) * np.asarray(streamwise, dtype=float)
        + float(target_radius) * radial_unit
    )
    line_direction = (
        float(panel_model["normal_stream"]) * np.asarray(streamwise, dtype=float)
        + float(panel_model["normal_radial"]) * radial_unit
    )
    line_direction /= np.linalg.norm(line_direction)
    return line_center, line_direction


def predictor_corrector_candidate(
    gradient_mesh: pv.DataSet,
    history_rows: list[dict[str, float | int]],
    target_radius: float,
    theta: float,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
    half_length: float,
    normal_step: float,
    min_height: float,
) -> tuple[dict[str, float | int | np.ndarray] | None, float]:
    """
    Do one panel-based predictor/corrector pass for a single shell-ray location.

    Predictor:
    - fit a panel from previous nodes
    - build a node line normal to that panel
    - find a candidate shock point on that line

    Corrector:
    - temporarily append the predicted point to the ray history
    - refit the panel once
    - rebuild the node line and sample again
    """
    panel_model = fit_panel_model(history_rows, target_radius)
    if panel_model is None:
        return None, 0.0

    initial_center, initial_direction = build_panel_line(
        panel_model, theta, target_radius, streamwise, normal, spanwise
    )
    initial_sample = sample_line(gradient_mesh, initial_center, initial_direction, half_length, normal_step)
    initial_candidate = find_shock_node_on_line(
        initial_sample,
        min_height=min_height,
        selection_mode=PEAK_MODE_NEAREST_CENTER,
        fallback_global=True,
    )
    if initial_candidate is None:
        return None, 0.0

    provisional_point = np.asarray(initial_candidate["point"], dtype=float)
    # The provisional row is the first guess. We temporarily pretend it is correct, refit
    # the local panel once, and then resample on that corrected line.
    provisional_row = {
        "stream_coord": float(np.dot(provisional_point, streamwise)),
        "radius_surface": float(target_radius),
    }
    corrected_model = fit_panel_model(history_rows + [provisional_row], target_radius)
    if corrected_model is None:
        return initial_candidate, abs(float(initial_candidate["line_coordinate"]))

    corrected_center, corrected_direction = build_panel_line(
        corrected_model, theta, target_radius, streamwise, normal, spanwise
    )
    corrected_sample = sample_line(gradient_mesh, corrected_center, corrected_direction, half_length, normal_step)
    corrected_candidate = find_shock_node_on_line(
        corrected_sample,
        min_height=min_height,
        selection_mode=PEAK_MODE_NEAREST_CENTER,
        fallback_global=True,
    )
    if corrected_candidate is None:
        return initial_candidate, abs(float(initial_candidate["line_coordinate"]))

    return corrected_candidate, abs(float(corrected_candidate["line_coordinate"]))


# --- Main shock-surface marching routine --------------------------------------
def extract_panel_surface(
    gradient_mesh: pv.DataSet,
    active_points: np.ndarray,
    dt: float,
    dn: float,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
) -> tuple[pv.PolyData, dict[str, float | int]]:
    """
    Main panel-method shock extraction loop.

    High-level flow:
    1. Find the stagnation shock node.
    2. Build azimuth rays around the body.
    3. March outward shell by shell.
    4. On shell 1, use simple streamwise node lines.
    5. On later shells, use panel-guided node lines.
    6. Stop when a full shell produces no accepted shock nodes.
    7. Triangulate neighboring accepted nodes into a surface.
    """
    stream_center, stream_half_length = build_streamwise_window(
        active_points, streamwise, normal, spanwise, dn
    )
    normal_step = dn
    search_line_half_length = search_line_half_length_factor * dt
    prediction_tolerance = panel_prediction_tolerance_dt_factor * dt
    max_surface_radius = max(float(np.max(perpendicular_radius(active_points, streamwise))), dt)
    azimuth_angles = build_surface_azimuth_rays(max_surface_radius, dt)
    ray_count = len(azimuth_angles)
    max_shell_count = max(1, int(math.ceil(max_surface_radius / dt)) + 2)
    progress(
        f"  [stage] marching shock surface with {ray_count} rays, dt={dt:.4f}, dn={dn:.4f}, "
        f"max_shells~{max_shell_count}"
    )

    # `accepted_rows` stores one metadata dictionary per accepted shock node.
    # `accepted_shock_nodes` stores just the xyz coordinates used to build the surface.
    accepted_rows: list[dict[str, float | int]] = []
    accepted_shock_nodes: list[np.ndarray] = []
    # Maps (shell, ray) -> point index in the final PolyData point list.
    shock_node_index_by_shell_ray: dict[tuple[int, int], int] = {}
    # Each ray stores only its own previously accepted shock nodes.
    ray_history: dict[int, list[dict[str, float | int]]] = {ray_idx: [] for ray_idx in range(ray_count)}

    # First, find the stagnation shock node on a plain streamwise node line.
    stagnation_candidate = find_stagnation_candidate(
        gradient_mesh,
        stream_center,
        stream_half_length,
        streamwise,
        dn,
    )

    # This first peak sets the global sensor floor for the rest of the extraction.
    center_peak = float(stagnation_candidate["shock_sensor_smoothed"])
    sensor_floor = center_peak * surface_sensor_min_fraction
    stagnation_point = np.asarray(stagnation_candidate["point"], dtype=float)
    stagnation_row = {
        "x": float(stagnation_point[0]),
        "y": float(stagnation_point[1]),
        "z": float(stagnation_point[2]),
        "stream_coord": float(np.dot(stagnation_point, streamwise)),
        "density": float(stagnation_candidate["density"]),
        "shock_sensor": float(stagnation_candidate["shock_sensor_smoothed"]),
        "shock_sensor_raw": float(stagnation_candidate["shock_sensor_raw"]),
        "radius_surface": 0.0,
        "azimuth_radians": 0.0,
        "shell_layer": 0,
        "ray_index": 0,
        "line_index": int(stagnation_candidate["sample_index"]),
        "line_mode": LINE_MODE_STAGNATION,
        "prediction_error": 0.0,
    }
    accepted_rows.append(stagnation_row)
    accepted_shock_nodes.append(stagnation_point)
    progress(
        f"  [stage] stagnation shock node found at x={stagnation_point[0]:.4f}, "
        f"y={stagnation_point[1]:.4f}, z={stagnation_point[2]:.4f}, peak={center_peak:.3f}"
    )

    # March outward shell by shell. Each shell contains one candidate node line per ray.
    for shell_index in range(1, max_shell_count + 1):
        shell_radius = float(shell_index) * dt
        # We collect a full shell first, then commit it afterward. That way one bad
        # ray does not partially mutate the accepted surface mid-shell.
        accepted_rows_in_shell: list[dict[str, float | int]] = []
        streamwise_accept_count = 0
        panel_guided_accept_count = 0
        progress(f"  [shell {shell_index}] radius_surface={shell_radius:.4f}")
        for ray_index, theta in enumerate(azimuth_angles):
            radial_unit = radial_unit_vector(theta, normal, spanwise)

            if shell_index == 1:
                # The first shell has no panel history yet, so it must use streamwise lines.
                line_mode = LINE_MODE_STREAMWISE
                line_center = (
                    float(stream_center) * np.asarray(streamwise, dtype=float) + float(shell_radius) * radial_unit
                )
                line_direction = np.asarray(streamwise, dtype=float)
                half_length = stream_half_length
                line_sample = sample_line(gradient_mesh, line_center, line_direction, half_length, normal_step)
                candidate = find_shock_node_on_line(
                    line_sample,
                    min_height=sensor_floor,
                    selection_mode=PEAK_MODE_FIRST_UPSTREAM,
                    fallback_global=True,
                )
                prediction_error = 0.0
            else:
                # Later shells can use the ray's previously accepted nodes to predict a better
                # shock-normal direction.
                history_rows = panel_history_for_ray(stagnation_row, ray_history, ray_index)
                candidate, prediction_error = predictor_corrector_candidate(
                    gradient_mesh,
                    history_rows,
                    shell_radius,
                    theta,
                    streamwise,
                    normal,
                    spanwise,
                    search_line_half_length,
                    normal_step,
                    sensor_floor,
                )
                if candidate is None:
                    continue
                # Reject panel candidates that drift too far from the panel prediction.
                if prediction_error > prediction_tolerance:
                    continue
                line_mode = LINE_MODE_PANEL_GUIDED

            if candidate is None:
                continue

            point = np.asarray(candidate["point"], dtype=float)
            row = {
                "x": float(point[0]),
                "y": float(point[1]),
                "z": float(point[2]),
                "stream_coord": float(np.dot(point, streamwise)),
                "density": float(candidate["density"]),
                "shock_sensor": float(candidate["shock_sensor_smoothed"]),
                "shock_sensor_raw": float(candidate["shock_sensor_raw"]),
                "radius_surface": float(shell_radius),
                "azimuth_radians": float(theta),
                "shell_layer": int(shell_index),
                "ray_index": int(ray_index),
                "line_index": int(candidate["sample_index"]),
                "line_mode": int(line_mode),
                "prediction_error": float(prediction_error),
            }
            accepted_rows_in_shell.append(row)
            if line_mode == LINE_MODE_STREAMWISE:
                streamwise_accept_count += 1
            elif line_mode == LINE_MODE_PANEL_GUIDED:
                panel_guided_accept_count += 1

        # If an entire shell finds no accepted shock nodes, the outward marching stops here.
        if not accepted_rows_in_shell:
            progress(f"  [shell {shell_index}] accepted 0/{ray_count} shock nodes -> stopping")
            break

        progress(
            f"  [shell {shell_index}] accepted {len(accepted_rows_in_shell)}/{ray_count} shock nodes "
            f"({streamwise_accept_count} streamwise, {panel_guided_accept_count} panel-guided)"
        )

        # Only commit a shell after the full ring has been tested.
        for row in accepted_rows_in_shell:
            point = np.asarray([row["x"], row["y"], row["z"]], dtype=float)
            local_idx = len(accepted_shock_nodes)
            accepted_shock_nodes.append(point)
            shell_ray = (int(row["shell_layer"]), int(row["ray_index"]))
            shock_node_index_by_shell_ray[shell_ray] = local_idx
            accepted_rows.append(row)
            ray_history[int(row["ray_index"])].append(row)

    # Build the actual ParaView surface object, then attach the per-point metadata so
    # the same information is available in ParaView and in the CSV export.
    poly = pv.PolyData(np.asarray(accepted_shock_nodes))
    poly.point_data["Density"] = np.asarray([row["density"] for row in accepted_rows], dtype=float)
    poly.point_data["ShockSensor"] = np.asarray([row["shock_sensor"] for row in accepted_rows], dtype=float)
    poly.point_data["ShockSensorRaw"] = np.asarray([row["shock_sensor_raw"] for row in accepted_rows], dtype=float)
    poly.point_data["RadiusSurface"] = np.asarray([row["radius_surface"] for row in accepted_rows], dtype=float)
    poly.point_data["AzimuthRadians"] = np.asarray([row["azimuth_radians"] for row in accepted_rows], dtype=float)
    poly.point_data["ShellLayer"] = np.asarray([row["shell_layer"] for row in accepted_rows], dtype=int)
    poly.point_data["RayIndex"] = np.asarray([row["ray_index"] for row in accepted_rows], dtype=int)
    poly.point_data["LineIndex"] = np.asarray([row["line_index"] for row in accepted_rows], dtype=int)
    poly.point_data["LineModeCode"] = np.asarray([row["line_mode"] for row in accepted_rows], dtype=int)
    poly.point_data["PredictionError"] = np.asarray([row["prediction_error"] for row in accepted_rows], dtype=float)
    poly.point_data["StreamCoord"] = np.asarray([row["stream_coord"] for row in accepted_rows], dtype=float)

    faces: list[int] = []
    center_idx = 0
    # Build a fan from the stagnation shock node to the first shell.
    if any((1, ray_idx) in shock_node_index_by_shell_ray for ray_idx in range(ray_count)):
        for ray_idx in range(ray_count):
            next_ray = (ray_idx + 1) % ray_count
            idx_a = shock_node_index_by_shell_ray.get((1, ray_idx))
            idx_b = shock_node_index_by_shell_ray.get((1, next_ray))
            if idx_a is None or idx_b is None:
                continue
            faces.extend([3, center_idx, int(idx_a), int(idx_b)])

    max_shell_layer = max(int(row["shell_layer"]) for row in accepted_rows)
    # Then stitch shell-to-shell quads and split each quad into two triangles.
    for shell_index in range(1, max_shell_layer):
        next_shell = shell_index + 1
        for ray_idx in range(ray_count):
            next_ray = (ray_idx + 1) % ray_count
            corners = [
                shock_node_index_by_shell_ray.get((shell_index, ray_idx)),
                shock_node_index_by_shell_ray.get((next_shell, ray_idx)),
                shock_node_index_by_shell_ray.get((next_shell, next_ray)),
                shock_node_index_by_shell_ray.get((shell_index, next_ray)),
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
            # Skip very stretched cells; they usually come from local gaps or missed rays.
            if max_edge > surface_mesh_edge_factor * max(dt, dn):
                continue

            c0, c1, c2, c3 = [int(corner) for corner in corners]
            faces.extend([3, c0, c1, c2, 3, c0, c2, c3])

    if faces:
        poly.faces = np.asarray(faces, dtype=np.int64)
    progress(f"  [stage] surface triangulation complete ({poly.n_points} points, {poly.n_cells} cells)")

    summary: dict[str, float | int] = {
        "point_count": poly.n_points,
        "cell_count": poly.n_cells,
        "center_peak": center_peak,
        "sensor_floor": sensor_floor,
        "prediction_tolerance": prediction_tolerance,
        "dt": dt,
        "dn": dn,
        "ray_count": ray_count,
        "max_shell_layer": max_shell_layer,
        "panel_lines": sum(1 for row in accepted_rows if int(row["line_mode"]) == LINE_MODE_PANEL_GUIDED),
        "streamwise_lines": sum(1 for row in accepted_rows if int(row["line_mode"]) == LINE_MODE_STREAMWISE),
    }
    return poly, summary

# --- Output and case-level orchestration --------------------------------------
def write_surface_outputs(case_path: Path, surface: pv.PolyData):
    """Write the extracted surface both as ParaView geometry and as a flat CSV table."""
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
                "stream_coord",
                "density",
                "shock_sensor",
                "shock_sensor_raw",
                "radius_surface",
                "azimuth_radians",
                "shell_layer",
                "ray_index",
                "line_index",
                "line_mode_code",
                "prediction_error",
            ]
        )

        # Pull each point-data column out once so the row-writing loop below is easy
        # to read and each column name is spelled in only one place.
        density = np.asarray(surface["Density"])
        shock_sensor = np.asarray(surface["ShockSensor"])
        shock_sensor_raw = np.asarray(surface["ShockSensorRaw"])
        radius_surface = np.asarray(surface["RadiusSurface"])
        azimuth_radians = np.asarray(surface["AzimuthRadians"])
        shell_layer = np.asarray(surface["ShellLayer"])
        ray_index = np.asarray(surface["RayIndex"])
        line_index = np.asarray(surface["LineIndex"])
        line_mode = np.asarray(surface["LineModeCode"])
        prediction_error = np.asarray(surface["PredictionError"])
        stream_coord = np.asarray(surface["StreamCoord"])

        for idx, point in enumerate(np.asarray(surface.points)):
            writer.writerow(
                [
                    float(point[0]),
                    float(point[1]),
                    float(point[2]),
                    float(stream_coord[idx]),
                    float(density[idx]),
                    float(shock_sensor[idx]),
                    float(shock_sensor_raw[idx]),
                    float(radius_surface[idx]),
                    float(azimuth_radians[idx]),
                    int(shell_layer[idx]),
                    int(ray_index[idx]),
                    int(line_index[idx]),
                    int(line_mode[idx]),
                    float(prediction_error[idx]),
                ]
            )

    return surface_path, csv_path


def process_case(paths: StudyPaths, case_dir: str):
    """Run the full panel shock extraction pipeline for one CFD case folder."""
    case_start_time = time.perf_counter()
    stage_times: dict[str, float] = {}
    case_path = resolve_case_path(paths.study_root, paths.cases_dir, case_dir)
    vtu_path = case_path / vtu_name
    if not vtu_path.exists():
        progress(f"  [skip] no {vtu_name} in {case_path.name}")
        return

    progress(f"  [stage] reading flow field: {vtu_path}")
    with timed_stage(stage_times, "read flow field"):
        mesh = pv.read(vtu_path)
    if density_scalar not in mesh.point_data and density_scalar in mesh.cell_data:
        # PyVista's derivative/sampling routines are easiest to use with point data.
        progress("  [stage] converting cell data to point data")
        with timed_stage(stage_times, "convert cell data to point data"):
            mesh = mesh.cell_data_to_point_data()

    if density_scalar not in mesh.array_names:
        available = ", ".join(sorted(mesh.array_names))
        raise KeyError(f"{density_scalar!r} not found. Available arrays: {available}")

    # Differentiate the full 3D density field first. The panel method works from this 3D
    # shock sensor instead of differentiating a lower-dimensional slice.
    progress("  [stage] differentiating 3D density field")
    with timed_stage(stage_times, "differentiate 3D density field"):
        with vtk_warning_mode(suppress_vtk_warnings):
            gradient_mesh = mesh.compute_derivative(scalars=density_scalar, gradient=True)

    with timed_stage(stage_times, "build frame and active shock region"):
        aoa_degrees = load_case_aoa_degrees(paths.generated_config_dir, case_path)
        progress(f"  [stage] building AoA-aligned frame (aoa={aoa_degrees:.1f} deg)")
        streamwise, normal, spanwise = streamwise_basis_from_aoa(aoa_degrees)
        points = np.asarray(gradient_mesh.points)
        gradient = np.asarray(gradient_mesh["gradient"], dtype=float)
        gradient = np.nan_to_num(gradient, nan=0.0, posinf=0.0, neginf=0.0)
        # The shock sensor is the magnitude of grad(rho).
        shock_sensor_raw = np.linalg.norm(gradient, axis=1)
        gradient_mesh["ShockSensorRaw"] = shock_sensor_raw

        progress("  [stage] locating stagnation shock node and active shock region")
        _, center_peak = choose_stagnation_shock_node(points, shock_sensor_raw, streamwise)
        # Ignore very weak gradients far from the shock so the marching logic focuses on the
        # meaningful part of the field.
        active_mask = shock_sensor_raw >= center_peak * surface_sensor_min_fraction
        active_points = points[active_mask]
        if active_points.size == 0:
            raise ValueError("no active points passed the surface sensor threshold")

    dt, dn = configured_sampling_steps()
    # `dt` controls the shell-to-shell spacing; `dn` controls the sample spacing
    # along each probe line.
    progress(
        f"  [stage] extracting shock surface (active points={active_points.shape[0]}, "
        f"dt={dt:.4f}, dn={dn:.4f})"
    )
    with timed_stage(stage_times, "extract shock surface"):
        surface, summary = extract_panel_surface(
            gradient_mesh, active_points, dt, dn, streamwise, normal, spanwise
        )
    progress("  [stage] writing surface outputs")
    with timed_stage(stage_times, "write surface outputs"):
        surface_path, csv_path = write_surface_outputs(case_path, surface)
    elapsed_seconds = time.perf_counter() - case_start_time

    progress(
        f"  [ok ] wrote {surface_path} ({surface.n_points} pts, {surface.n_cells} tris, "
        f"aoa={aoa_degrees:.1f}, center_peak={summary['center_peak']:.3f}, "
        f"dt={summary['dt']:.4f}, dn={summary['dn']:.4f}, rays={summary['ray_count']}, "
        f"panel_lines={summary['panel_lines']}, streamwise_lines={summary['streamwise_lines']}, "
        f"max_shell={summary['max_shell_layer']}, elapsed={elapsed_seconds / 60.0:.1f} min)"
    )
    progress(f"  [ok ] wrote {csv_path}")
    progress("  [time ] timing summary:")
    for stage_name, stage_seconds in stage_times.items():
        progress(f"  [time ]   {stage_name}: {stage_seconds:.1f} s")
    progress(f"  [time ]   total: {elapsed_seconds:.1f} s")


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


def main() -> int:
    env_study = os.environ.get("CFD_STUDY", "").strip()
    paths = get_study_paths(env_study) if env_study else choose_study_paths_interactively()

    print("\n╔══════════════════════════════════════════════╗")
    print("║   Panel Shock Surface Extractor             ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"Study: {paths.study_name}")
    print(f"Density scalar: {density_scalar}")
    dt, dn = configured_sampling_steps()
    print(
        f"Spacing from code settings: dt={dt:.4f}, dn={dn:.4f}, "
        f"sensor floor: {surface_sensor_min_fraction:g} of center peak, "
        f"savgol window/poly: {savgol_window_points}/{savgol_poly_order}"
    )

    cases = cases_from_environment(paths)
    if not cases:
        cases = choose_postprocess_cases_interactively(paths.cases_dir, vtu_name)
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
