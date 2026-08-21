#!/usr/bin/env python3
"""
Extract a 3D bow-shock surface from one CFD volume solution.

If you are reading this file as a beginner, the big picture is:

1. Read one flow-field file, defaulting to `flow_full.vtu`.
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
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyvista as pv

from hypersonics_cfd.cases import (
    cases_from_environment,
    choose_postprocess_cases_interactively,
    deduplicate_case_names,
    resolve_case_path,
)
from hypersonics_cfd.study import (
    StudyPaths,
    choose_study_paths_interactively,
    get_study_paths,
)

from .frame import (
    frame_coordinates,
    perpendicular_radius,
    streamwise_basis_from_aoa,
)
from .io import write_surface_outputs
from .sensor import (
    PEAK_MODE_FIRST_UPSTREAM,
    PEAK_MODE_NEAREST_CENTER,
    autoscaled_savgol_window_points,
    find_shock_node_on_line_result,
    line_peak_acceptance_prominence_ratio,
    line_peak_detection_prominence_fraction,
    line_peak_height_fraction,
    savgol_max_window_points,
    savgol_min_window_points,
    savgol_poly_order,
    savgol_smoothing_length,
    smooth_line_profile,
)

try:
    from vtkmodules.vtkCommonCore import vtkObject
except ImportError:
    vtkObject = None

# --------------- USER SETTINGS ---------------
# This is the main tuning block for the extractor. The code below uses these values directly,
# so this is the first place to look if you want to change spacing or sensitivity.
vtu_name = os.environ.get("CFD_FLOW_FILE", "flow_full.vtu").strip() or "flow_full.vtu"
density_scalar = "Density"
output_surface_name = "shock_surface.vtp"
output_csv_name = "shock_surface.csv"
surface_flow_name = "surface_flow.vtu"
body_profile_name = "orion_profile_xy.csv"

# Search radius around the streamwise axis for the very first stagnation shock point.
stagnation_shock_node_radius = 0.10

# `dt` = shell spacing. It controls how far apart neighboring shock rings are.
default_dt = 0.10
# `dn` = node-line spacing. It controls how finely we sample each 1D probe line.
default_dn = 0.01

# Ignore very weak gradients far from the real shock.
surface_sensor_min_fraction = 0.005

streamwise_padding_factor = 1.0

# Very near the nose, some valid broad shock profiles do not form a clean local peak after
# smoothing. Only enforce the final prominence gate farther out, where weak fallback peaks
# are more likely to be spray/artifacts than the main attached shock.
panel_prominence_check_min_radius = 5.0
# Prominence is useful, but a single weak 1D profile should not punch a hole in an otherwise
# coherent 2D shock sheet. Keep very short weak-prominence gaps, and reject longer contiguous
# weak segments as the surface trails into non-shock scatter.
weak_prominence_gap_fill_max_rays = 2

# Stagnation search refinement:
# - first scan the long stagnation line with a moderately coarse spacing
# - then resample a smaller window around that coarse peak using a finer fraction of `dn`
stagnation_coarse_step_factor = 2.0
stagnation_refined_step_factor = 0.2
# When the stagnation line is body-anchored, the body/wall gradient can be stronger than the
# bow shock. Keep this exclusion conservative while still allowing high-Mach,
# low-standoff shocks to be sampled.
stagnation_body_exclusion_dn_factor = 2.0

# Panel-guided search-line settings used after the first shell.
# Keep search lines local to the panel prediction so they cannot reach unrelated gradient
# branches. The acceptance tolerance below is intentionally smaller than this sampled window.
search_line_half_length_sampling_diagonal_factor = 2.0
# `epsilon_tol` is the maximum allowed distance between the panel prediction and the
# detected shock point on that search line. Use the local sampling diagonal so it scales
# with both shell spacing (`dt`) and line spacing (`dn`).
epsilon_tol_sampling_diagonal_factor = 1.25
# Predict each new panel-guided search line from a local polynomial through recent
# accepted nodes on the same ray. A quadratic over a longer history has been more stable
# than a short cubic because it follows the broader shock trend without overreacting to
# one noisy node.
panel_fit_node_count = 31
panel_polynomial_degree = 2
panel_corrector_min_history_nodes = 3
# Use streamwise bootstrap lines only until each ray has enough accepted nodes to fit a
# local panel predictor. This avoids a hardcoded physical transition radius and lets each
# ray switch independently.
streamwise_bootstrap_node_count = 5
# During the first few panel-guided shells, the predictor can still be under-informed,
# especially in the strongly curved nose region. In that warmup period, use the panel line
# first, but fall back to the local streamwise line if the panel candidate fails. This keeps
# the core bow-shock surface complete without reviving far-downstream trailing spray.
panel_guided_warmup_fallback_node_count = 31
minimum_azimuth_rays = 12
# Set to a fraction such as 0.15 to stop before adding shells with too many failed rays.
# Keep this disabled for asymmetric AoA cases because one side can naturally terminate
# earlier than the other.
max_terminated_search_line_fraction = None
# Early accepted points should vary smoothly from ray to ray. This rejects isolated nodes
# that jump to a neighboring shock/gradient branch before those bad points can form panels.
shell_neighbor_check_max_radius = 6.0
shell_neighbor_window_rays = 2
shell_neighbor_stream_tolerance_factor = 3.0

# Final surface cleanup:
# The line-search stage can occasionally leave thin "hairs" near the end of the shock.
# These points may pass the 1D peak test, but they do not form a supported 2D surface.
# This post-processing pass is intentionally gentle:
#   1. keep the main connected surface component
#   2. iteratively peel only one-neighbor dangling endpoints
# It does not crop by x/y/z position, Mach number, or case-specific geometry.
surface_cleanup_enabled = True
surface_cleanup_small_component_fraction = 0.05
surface_cleanup_dangling_neighbor_limit = 2

# This is only a runaway-loop guard. Normal extraction should stop because a shell fails
# or becomes too sparse to form a reliable surface, not because this limit is reached.
shell_iteration_safety_limit = 10000

# Terminated search-line debugging is off by default because it can write many rows.
# Turn it on for one run with:
#   CFD_EXPORT_TERMINATED_SEARCH_LINES=1 CFD_CASE=m6_medium python3 scripts/extract_shock_surface.py
export_terminated_search_lines = False
terminated_search_line_summary_csv_name = "terminated_search_line_summary.csv"
terminated_search_line_profiles_csv_name = "terminated_search_line_profiles.csv"
# 0 means "write every terminated line". Use CFD_TERMINATED_SEARCH_LINE_LIMIT to cap one run.
terminated_search_line_max_lines = 0
# Write one terminated line profile every N terminated lines so the debug CSV stays manageable.
terminated_search_line_stride = 50

suppress_vtk_warnings = True
# ---------------------------------------------

LINE_MODE_STAGNATION = 0
LINE_MODE_STREAMWISE = 1
LINE_MODE_PANEL_GUIDED = 2

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
    """Fallback AoA parser for case names like `m3_aoa15` or `m1p5_aoa24p5`."""
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


def load_body_anchor_points_from_surface_flow(case_path: Path) -> tuple[np.ndarray, str] | None:
    """
    Try to read body-surface points from a case-local `surface_flow.vtu`.

    Some existing cases contain an empty `surface_flow.vtu`, so this is only used when the
    file has real geometry points. Otherwise we fall back to the canonical Orion profile.
    """
    surface_path = case_path / surface_flow_name
    if not surface_path.exists():
        return None

    with vtk_warning_mode(suppress_vtk_warnings):
        surface = pv.read(surface_path)
    if surface.n_points == 0:
        return None
    return np.asarray(surface.points, dtype=float), surface_path.name


def load_body_anchor_points_from_profile(study_root: Path) -> tuple[np.ndarray, str] | None:
    """
    Read the 2D Orion body profile and place it in the extractor's 3D coordinate system.

    The profile columns are `(x, y)` in the AoA plane. The solver/extractor coordinates use
    global `y` as the spanwise direction, so profile `y` becomes global `z` here.
    """
    profile_path = Path(study_root) / "geometry" / body_profile_name
    if not profile_path.exists():
        return None

    points: list[list[float]] = []
    with profile_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if "x" not in row or "y" not in row:
                continue
            points.append([float(row["x"]), 0.0, float(row["y"])])

    if not points:
        return None
    return np.asarray(points, dtype=float), f"geometry/{profile_path.name}"


def choose_body_stagnation_anchor(
    study_root: Path,
    case_path: Path,
    streamwise: np.ndarray,
) -> tuple[np.ndarray, str]:
    """
    Choose the upstream-most body point for the current AoA.

    This point defines the streamwise axis used by the stagnation search and shell marching.
    Without this anchor, high-AoA cases can accidentally start from a generic axis that does
    not pass through the body stagnation region.
    """
    body_sources = (
        load_body_anchor_points_from_surface_flow(case_path),
        load_body_anchor_points_from_profile(study_root),
    )
    for source in body_sources:
        if source is None:
            continue
        points, source_label = source
        stream_coordinates = points @ np.asarray(streamwise, dtype=float)
        anchor = np.asarray(points[int(np.argmin(stream_coordinates))], dtype=float)
        return anchor, source_label

    progress("  [warn] no body geometry anchor found; falling back to the global origin")
    return np.zeros(3, dtype=float), "global origin fallback"


def choose_stagnation_shock_node(
    points: np.ndarray,
    shock_sensor: np.ndarray,
    streamwise: np.ndarray,
    axis_origin: np.ndarray | None = None,
) -> tuple[int, float]:
    """
    Pick the first trusted shock point near the stagnation region.

    We look close to the AoA-aligned streamwise axis first because the bow shock should be
    easiest to identify there. If that narrow tube contains no points, we fall back to the
    points closest to the axis.
    """
    radius = perpendicular_radius(points, streamwise, origin=axis_origin)
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


def env_flag(name: str, default: bool) -> bool:
    """Read a boolean environment override without needing command-line arguments."""
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on", "y"}:
        return True
    if value in {"0", "false", "no", "off", "n"}:
        return False
    raise ValueError(f"{name} must be true/false, got {value!r}")


def env_int(name: str, default: int) -> int:
    """Read an integer environment override."""
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{name} must be nonnegative")
    return parsed


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


class TerminatedSearchLineDebugWriter:
    """
    Stream terminated line-search profiles into compact per-case CSVs.

    The plotter needs profiles as functions of `n`, the local coordinate along each search
    line. To keep "export every terminated line" realistic, each CSV row stores one full
    search-line profile with semicolon-separated arrays instead of one row per sample.
    """

    summary_fieldnames = [
        "debug_line_id",
        "reason",
        "stage",
        "shell_layer",
        "ray_index",
        "azimuth_radians",
        "target_radius",
        "prediction_error",
        "prediction_tolerance",
        "line_mode_code",
        "candidate_index",
        "candidate_n",
        "candidate_smoothed",
        "candidate_prominence",
        "candidate_prominence_ratio",
        "line_center_x",
        "line_center_y",
        "line_center_z",
        "line_direction_x",
        "line_direction_y",
        "line_direction_z",
        "half_length",
        "sample_spacing",
        "savgol_window_points",
        "savgol_smoothing_length",
        "savgol_poly_order",
        "dt",
        "dn",
        "sample_count",
        "valid_sample_count",
        "max_smoothed_sensor",
        "max_smoothed_sensor_n",
    ]

    profile_fieldnames = [
        "debug_line_id",
        "reason",
        "stage",
        "shell_layer",
        "ray_index",
        "azimuth_radians",
        "target_radius",
        "prediction_error",
        "prediction_tolerance",
        "line_mode_code",
        "candidate_index",
        "candidate_n",
        "candidate_smoothed",
        "candidate_prominence",
        "candidate_prominence_ratio",
        "n",
        "x",
        "y",
        "z",
        "density",
        "shock_sensor_raw",
        "shock_sensor_smoothed",
        "valid_mask",
        "is_candidate",
    ]

    def __init__(self, case_path: Path, enabled: bool, max_lines: int, line_stride: int):
        self.enabled = enabled
        self.max_lines = max_lines
        self.line_stride = max(1, int(line_stride))
        self.observed_line_count = 0
        self.line_count = 0
        self.sample_count = 0
        self.output_dir = case_path
        self.summary_csv_path = self.output_dir / terminated_search_line_summary_csv_name
        self.profiles_csv_path = self.output_dir / terminated_search_line_profiles_csv_name
        self.old_debug_dir = case_path / "search_line_debug"
        self.old_debug_paths = (
            self.old_debug_dir / "failed_search_lines.csv",
            self.old_debug_dir / terminated_search_line_summary_csv_name,
            self.old_debug_dir / terminated_search_line_profiles_csv_name,
        )
        self._summary_handle = None
        self._profile_handle = None
        self._summary_writer: csv.DictWriter | None = None
        self._profile_writer: csv.DictWriter | None = None

        if self.enabled:
            for path in (self.summary_csv_path, self.profiles_csv_path, *self.old_debug_paths):
                if path.exists():
                    path.unlink()
            if self.old_debug_dir.exists():
                try:
                    self.old_debug_dir.rmdir()
                except OSError:
                    pass

    def close(self) -> None:
        if self._summary_handle is not None:
            self._summary_handle.close()
            self._summary_handle = None
            self._summary_writer = None
        if self._profile_handle is not None:
            self._profile_handle.close()
            self._profile_handle = None
            self._profile_writer = None

    def _ensure_summary_writer(self) -> csv.DictWriter:
        if self._summary_writer is not None:
            return self._summary_writer
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._summary_handle = self.summary_csv_path.open("w", newline="", encoding="utf-8")
        self._summary_writer = csv.DictWriter(self._summary_handle, fieldnames=self.summary_fieldnames)
        self._summary_writer.writeheader()
        return self._summary_writer

    def _ensure_profile_writer(self) -> csv.DictWriter:
        if self._profile_writer is not None:
            return self._profile_writer
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._profile_handle = self.profiles_csv_path.open("w", newline="", encoding="utf-8")
        self._profile_writer = csv.DictWriter(self._profile_handle, fieldnames=self.profile_fieldnames)
        self._profile_writer.writeheader()
        return self._profile_writer

    @staticmethod
    def _encode_float_array(values: np.ndarray) -> str:
        return ";".join(f"{float(value):.10g}" for value in np.asarray(values).ravel())

    @staticmethod
    def _encode_int_array(values: np.ndarray) -> str:
        return ";".join(str(int(value)) for value in np.asarray(values).ravel())

    def write_search_line(
        self,
        *,
        reason: str,
        stage: str,
        line_sample: dict[str, np.ndarray],
        line_center: np.ndarray,
        line_direction: np.ndarray,
        half_length: float,
        dt: float,
        dn: float,
        shell_layer: int,
        ray_index: int,
        azimuth_radians: float,
        target_radius: float,
        line_mode: int,
        candidate: dict[str, float | int | np.ndarray] | None = None,
        prediction_error: float = float("nan"),
        prediction_tolerance: float = float("nan"),
    ) -> None:
        if not self.enabled:
            return
        self.observed_line_count += 1
        if (self.observed_line_count - 1) % self.line_stride != 0:
            return
        if self.max_lines > 0 and self.line_count >= self.max_lines:
            return

        smoothed = smooth_line_profile(
            line_sample["shock_sensor_raw"],
            line_sample["valid_mask"],
            line_sample["line_coordinates"],
        )
        if line_sample["line_coordinates"].size >= 2:
            sample_spacing = abs(
                float(line_sample["line_coordinates"][1]) - float(line_sample["line_coordinates"][0])
            )
        else:
            sample_spacing = float(dn)

        valid_idx = np.flatnonzero(line_sample["valid_mask"])
        if valid_idx.size > 0:
            segment_size = int(valid_idx[-1] - valid_idx[0] + 1)
            window_points = autoscaled_savgol_window_points(sample_spacing, segment_size)
        else:
            window_points = 0

        n_coordinates = np.asarray(line_sample["line_coordinates"], dtype=float)
        points = np.asarray(line_sample["points"], dtype=float)
        density = np.asarray(line_sample["density"], dtype=float)
        shock_sensor_raw = np.asarray(line_sample["shock_sensor_raw"], dtype=float)
        valid_mask = np.asarray(line_sample["valid_mask"], dtype=bool)

        candidate_index = int(candidate["sample_index"]) if candidate is not None else -1
        candidate_n = (
            float(candidate["line_coordinate"]) if candidate is not None else float("nan")
        )
        candidate_smoothed = (
            float(candidate["shock_sensor_smoothed"]) if candidate is not None else float("nan")
        )
        candidate_prominence = (
            float(candidate["shock_sensor_prominence"]) if candidate is not None else float("nan")
        )
        candidate_prominence_ratio = (
            float(candidate["shock_sensor_prominence_ratio"]) if candidate is not None else float("nan")
        )
        is_candidate = np.zeros(n_coordinates.size, dtype=int)
        if 0 <= candidate_index < is_candidate.size:
            is_candidate[candidate_index] = 1

        if smoothed.size > 0:
            max_index = int(np.nanargmax(smoothed))
            max_smoothed_sensor = float(smoothed[max_index])
            max_smoothed_sensor_n = float(n_coordinates[max_index])
        else:
            max_smoothed_sensor = float("nan")
            max_smoothed_sensor_n = float("nan")

        self.line_count += 1
        debug_line_id = self.observed_line_count
        summary_writer = self._ensure_summary_writer()
        profile_writer = self._ensure_profile_writer()
        center = np.asarray(line_center, dtype=float)
        direction = np.asarray(line_direction, dtype=float)

        common_metadata = {
            "debug_line_id": debug_line_id,
            "reason": reason,
            "stage": stage,
            "shell_layer": int(shell_layer),
            "ray_index": int(ray_index),
            "azimuth_radians": float(azimuth_radians),
            "target_radius": float(target_radius),
            "prediction_error": float(prediction_error),
            "prediction_tolerance": float(prediction_tolerance),
            "line_mode_code": int(line_mode),
            "candidate_index": candidate_index,
            "candidate_n": candidate_n,
            "candidate_smoothed": candidate_smoothed,
            "candidate_prominence": candidate_prominence,
            "candidate_prominence_ratio": candidate_prominence_ratio,
        }

        summary_writer.writerow(
            {
                **common_metadata,
                "line_center_x": float(center[0]),
                "line_center_y": float(center[1]),
                "line_center_z": float(center[2]),
                "line_direction_x": float(direction[0]),
                "line_direction_y": float(direction[1]),
                "line_direction_z": float(direction[2]),
                "half_length": float(half_length),
                "sample_spacing": float(sample_spacing),
                "savgol_window_points": int(window_points),
                "savgol_smoothing_length": float(savgol_smoothing_length),
                "savgol_poly_order": int(savgol_poly_order),
                "dt": float(dt),
                "dn": float(dn),
                "sample_count": int(n_coordinates.size),
                "valid_sample_count": int(np.count_nonzero(valid_mask)),
                "max_smoothed_sensor": max_smoothed_sensor,
                "max_smoothed_sensor_n": max_smoothed_sensor_n,
            }
        )
        profile_writer.writerow(
            {
                **common_metadata,
                "n": self._encode_float_array(n_coordinates),
                "x": self._encode_float_array(points[:, 0]),
                "y": self._encode_float_array(points[:, 1]),
                "z": self._encode_float_array(points[:, 2]),
                "density": self._encode_float_array(density),
                "shock_sensor_raw": self._encode_float_array(shock_sensor_raw),
                "shock_sensor_smoothed": self._encode_float_array(smoothed),
                "valid_mask": self._encode_int_array(valid_mask.astype(int)),
                "is_candidate": self._encode_int_array(is_candidate),
            }
        )
        self.sample_count += int(n_coordinates.size)


# --- Build simple 1D node lines -----------------------------------------------
def build_streamwise_window(
    active_points: np.ndarray,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
    dn: float,
    axis_origin: np.ndarray,
) -> tuple[float, float]:
    """
    Build the baseline streamwise search window.

    Even the panel method needs a "plain streamwise" line at stagnation and on the first shell.
    This function decides how long those lines should be so they cover the active shock region
    plus a little extra margin.
    """
    local_points = frame_coordinates(active_points, streamwise, normal, spanwise, origin=axis_origin)
    stream_min = float(local_points[:, 0].min())
    stream_max = float(local_points[:, 0].max())
    stream_pad = max((stream_max - stream_min) * streamwise_padding_factor, dn)
    start = stream_min - stream_pad
    stop = stream_max + stream_pad
    # The line center deliberately stays at the body anchor (stream coordinate 0). The
    # half-length grows enough to cover the active shock region on both sides of that anchor.
    center = 0.0
    half_length = max(abs(start), abs(stop), dn)
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


def build_stagnation_search_diagnostics(
    gradient_mesh: pv.DataSet,
    line_center: np.ndarray,
    stream_half_length: float,
    streamwise: np.ndarray,
    dn: float,
) -> dict[str, object]:
    """
    Build the coarse/refined diagnostics for the first stagnation search line.

    The full stagnation line can be long, so the coarse pass cheaply localizes the shock.
    We then resample only one coarse interval around that location using a finer fraction of `dn`.
    """
    coarse_step = max(dn, stagnation_coarse_step_factor * dn)
    refined_step = max(dn * stagnation_refined_step_factor, np.finfo(float).eps)
    line_direction = np.asarray(streamwise, dtype=float)
    coarse_center = np.asarray(line_center, dtype=float)

    progress(
        f"  [stage] sampling stagnation node line (coarse pass, step={coarse_step:.4f}, "
        f"half_length={stream_half_length:.4f})"
    )
    coarse_sample = sample_line(
        gradient_mesh,
        coarse_center,
        line_direction,
        stream_half_length,
        coarse_step,
    )
    body_exclusion = max(stagnation_body_exclusion_dn_factor * dn, dn)
    coarse_search_mask = np.asarray(coarse_sample["valid_mask"], dtype=bool).copy()
    coarse_search_mask &= np.asarray(coarse_sample["line_coordinates"], dtype=float) <= -body_exclusion
    coarse_candidate, coarse_rejection_reason, _ = find_shock_node_on_line_result(
        coarse_sample,
        min_height=0.0,
        selection_mode=PEAK_MODE_FIRST_UPSTREAM,
        fallback_global=True,
        enforce_prominence_check=False,
        max_line_coordinate=-body_exclusion,
    )
    if coarse_candidate is None:
        reason = coarse_rejection_reason or "unknown"
        valid_count = int(np.count_nonzero(coarse_search_mask))
        if valid_count:
            search_sensor = np.asarray(coarse_sample["shock_sensor_raw"], dtype=float)[coarse_search_mask]
            search_max = float(np.nanmax(search_sensor))
        else:
            search_max = float("nan")
        raise ValueError(
            "could not find a shock node on the coarse stagnation node line "
            f"({reason}; valid_search_samples={valid_count}, max_raw_sensor={search_max:.6g})"
        )

    refine_half_length = min(stream_half_length, coarse_step)
    refine_center = np.asarray(coarse_candidate["point"], dtype=float)
    # In the refined line coordinate system, the body anchor is downstream of the coarse
    # shock candidate by `-coarse_candidate["line_coordinate"]`. Exclude that wall region
    # again so the refined pass cannot snap back to the body gradient.
    refined_body_coordinate = -float(coarse_candidate["line_coordinate"])
    progress(
        f"  [stage] refining stagnation node line around coarse peak "
        f"(half_length={refine_half_length:.4f}, step={refined_step:.4f})"
    )
    refined_sample = sample_line(
        gradient_mesh,
        refine_center,
        np.asarray(streamwise, dtype=float),
        refine_half_length,
        refined_step,
    )
    refined_candidate, _, _ = find_shock_node_on_line_result(
        refined_sample,
        min_height=0.0,
        selection_mode=PEAK_MODE_FIRST_UPSTREAM,
        fallback_global=True,
        enforce_prominence_check=False,
        max_line_coordinate=refined_body_coordinate - body_exclusion,
    )
    chosen_candidate = refined_candidate if refined_candidate is not None else coarse_candidate
    return {
        "coarse": {
            "sample": coarse_sample,
            "candidate": coarse_candidate,
            "line_center": coarse_center,
            "line_direction": line_direction,
            "half_length": float(stream_half_length),
            "sample_spacing": float(coarse_step),
        },
        "refined": {
            "sample": refined_sample,
            "candidate": refined_candidate,
            "line_center": refine_center,
            "line_direction": line_direction,
            "half_length": float(refine_half_length),
            "sample_spacing": float(refined_step),
        },
        "chosen_candidate": chosen_candidate,
    }


def find_stagnation_candidate(
    gradient_mesh: pv.DataSet,
    line_center: np.ndarray,
    stream_half_length: float,
    streamwise: np.ndarray,
    dn: float,
) -> dict[str, float | int | np.ndarray]:
    """Return the final stagnation candidate from the coarse-to-fine search."""
    diagnostics = build_stagnation_search_diagnostics(
        gradient_mesh,
        line_center,
        stream_half_length,
        streamwise,
        dn,
    )
    return diagnostics["chosen_candidate"]  # type: ignore[return-value]


# --- Panel fitting and predictor/corrector marching ---------------------------
def panel_history_for_ray(
    stagnation_row: dict[str, float | int],
    ray_history: dict[int, list[dict[str, float | int]]],
    ray_index: int,
) -> list[dict[str, float | int]]:
    """Collect the stagnation point plus this ray's previously accepted shock nodes."""
    return [stagnation_row] + list(ray_history.get(ray_index, []))


def reject_shell_neighbor_outliers(
    shell_rows: list[dict[str, float | int]],
    ray_count: int,
    stream_tolerance: float,
) -> tuple[list[dict[str, float | int]], list[dict[str, float | int]]]:
    """
    Remove isolated shell nodes that disagree strongly with nearby rays.

    A line search can occasionally pick a strong but wrong downstream peak. The panel builder
    should not have to decide whether that point is physical, so this point-checker compares
    each node against the local median streamwise position of nearby rays on the same shell.
    """
    if len(shell_rows) < 2 * shell_neighbor_window_rays + 2:
        return shell_rows, []

    row_by_ray = {int(row["ray_index"]): row for row in shell_rows}
    kept_rows: list[dict[str, float | int]] = []
    dropped_rows: list[dict[str, float | int]] = []

    for row in shell_rows:
        ray_index = int(row["ray_index"])
        neighbor_streams: list[float] = []
        for offset in range(-shell_neighbor_window_rays, shell_neighbor_window_rays + 1):
            if offset == 0:
                continue
            neighbor = row_by_ray.get((ray_index + offset) % ray_count)
            if neighbor is not None:
                neighbor_streams.append(float(neighbor["stream_coord"]))

        if len(neighbor_streams) < max(2, shell_neighbor_window_rays):
            kept_rows.append(row)
            continue

        local_stream_median = float(np.median(neighbor_streams))
        stream_jump = abs(float(row["stream_coord"]) - local_stream_median)
        if stream_jump > stream_tolerance:
            dropped_rows.append(row)
        else:
            kept_rows.append(row)

    return kept_rows, dropped_rows


def contiguous_cyclic_segments(indices: set[int], count: int) -> list[list[int]]:
    """Group integer indices into contiguous segments on a periodic ring."""
    if not indices:
        return []
    if len(indices) >= count:
        return [list(range(count))]

    # Start immediately after a gap so wrapped segments are represented as one segment.
    start = next(i for i in range(count) if i not in indices)
    segments: list[list[int]] = []
    current: list[int] = []
    for step in range(1, count + 1):
        idx = (start + step) % count
        if idx in indices:
            current.append(idx)
        elif current:
            segments.append(current)
            current = []
    if current:
        segments.append(current)
    return segments


def reject_unsupported_weak_prominence_rows(
    shell_rows: list[dict[str, float | int]],
    ray_count: int,
) -> tuple[list[dict[str, float | int]], list[dict[str, float | int]], int]:
    """
    Reject broad weak-prominence segments, but keep tiny gaps inside the main surface.

    A single search line can have a weak peak because of sampling/smoothing details even when
    neighboring rays clearly remain on the same shock sheet. Long contiguous weak runs are
    different: those are where the shock signature is dying out, so they should terminate.
    """
    weak_rays = {
        int(row["ray_index"])
        for row in shell_rows
        if int(row.get("prominence_ok", 1)) == 0
    }
    if not weak_rays:
        return shell_rows, [], 0

    rejected_rays: set[int] = set()
    kept_weak_count = 0
    for segment in contiguous_cyclic_segments(weak_rays, ray_count):
        if len(segment) <= weak_prominence_gap_fill_max_rays:
            kept_weak_count += len(segment)
        else:
            rejected_rays.update(segment)

    rejected_rows = [row for row in shell_rows if int(row["ray_index"]) in rejected_rays]
    kept_rows = [row for row in shell_rows if int(row["ray_index"]) not in rejected_rays]
    return kept_rows, rejected_rows, kept_weak_count


def count_line_modes(shell_rows: list[dict[str, float | int]]) -> tuple[int, int]:
    """Count streamwise and panel-guided accepted rows after shell-level filtering."""
    streamwise_count = sum(1 for row in shell_rows if int(row["line_mode"]) == LINE_MODE_STREAMWISE)
    panel_count = sum(1 for row in shell_rows if int(row["line_mode"]) == LINE_MODE_PANEL_GUIDED)
    return streamwise_count, panel_count


def surface_node_key(row: dict[str, float | int]) -> tuple[int, int]:
    """Return the structured-grid address of one accepted shock node."""
    return int(row["shell_layer"]), int(row["ray_index"])


def build_surface_neighbor_graph(
    node_keys: set[tuple[int, int]],
    ray_count: int,
) -> dict[tuple[int, int], set[tuple[int, int]]]:
    """
    Connect accepted nodes that should be neighbors on the sampled shock surface.

    A node is addressed by `(shell_layer, ray_index)`. The natural neighbors are:
    - previous/next ray on the same shell
    - previous/next shell on the same ray
    - the stagnation node connected to shell 1

    We intentionally avoid diagonal neighbors here. Diagonal connections can make a
    one-cell-wide hair look more supported than it really is.
    """
    graph = {key: set() for key in node_keys}
    center_key = (0, 0)

    def connect(a: tuple[int, int], b: tuple[int, int]) -> None:
        if a in graph and b in graph:
            graph[a].add(b)
            graph[b].add(a)

    if center_key in graph:
        for ray_index in range(ray_count):
            connect(center_key, (1, ray_index))

    for shell_layer, ray_index in node_keys:
        if shell_layer == 0:
            continue

        connect((shell_layer, ray_index), (shell_layer, (ray_index - 1) % ray_count))
        connect((shell_layer, ray_index), (shell_layer, (ray_index + 1) % ray_count))
        if shell_layer > 1:
            connect((shell_layer, ray_index), (shell_layer - 1, ray_index))
        connect((shell_layer, ray_index), (shell_layer + 1, ray_index))

    return graph


def connected_components(
    graph: dict[tuple[int, int], set[tuple[int, int]]],
) -> list[set[tuple[int, int]]]:
    """Find connected groups in the accepted-node graph."""
    components: list[set[tuple[int, int]]] = []
    unseen = set(graph)

    while unseen:
        start = unseen.pop()
        component = {start}
        stack = [start]
        while stack:
            current = stack.pop()
            for neighbor in graph[current]:
                if neighbor not in unseen:
                    continue
                unseen.remove(neighbor)
                component.add(neighbor)
                stack.append(neighbor)
        components.append(component)

    return components


def keep_large_surface_components(
    node_keys: set[tuple[int, int]],
    ray_count: int,
) -> tuple[set[tuple[int, int]], int]:
    """
    Keep the dominant connected surface and remove tiny disconnected islands.

    The largest component is always kept. Additional components are kept only if they are
    at least `surface_cleanup_small_component_fraction` as large as the largest component.
    """
    if not node_keys:
        return node_keys, 0

    graph = build_surface_neighbor_graph(node_keys, ray_count)
    components = connected_components(graph)
    if len(components) <= 1:
        return node_keys, 0

    largest_size = max(len(component) for component in components)
    minimum_size = max(1, int(math.ceil(surface_cleanup_small_component_fraction * largest_size)))
    kept_components = [component for component in components if len(component) >= minimum_size]
    kept_keys = set().union(*kept_components)
    return kept_keys, len(node_keys) - len(kept_keys)


def remove_dangling_surface_endpoints(
    node_keys: set[tuple[int, int]],
    ray_count: int,
) -> tuple[set[tuple[int, int]], int, int]:
    """
    Iteratively peel one-neighbor endpoint nodes from the accepted surface graph.

    This removes hair-like strands without requiring every valid boundary node to have a
    large number of neighbors. The stagnation node is protected because it is the apex of
    the surface fan.
    """
    kept_keys = set(node_keys)
    removed_count = 0
    iteration_count = 0

    while True:
        graph = build_surface_neighbor_graph(kept_keys, ray_count)
        dangling_keys = {
            key
            for key, neighbors in graph.items()
            if key != (0, 0) and len(neighbors) <= surface_cleanup_dangling_neighbor_limit
        }
        if not dangling_keys:
            break

        kept_keys.difference_update(dangling_keys)
        removed_count += len(dangling_keys)
        iteration_count += 1

    return kept_keys, removed_count, iteration_count


def cleanup_accepted_surface_nodes(
    accepted_rows: list[dict[str, float | int]],
    ray_count: int,
) -> tuple[list[dict[str, float | int]], dict[str, int]]:
    """
    Remove obvious non-surface stragglers after the marching stage.

    This cleanup is deliberately topology-based rather than case-geometry-based. It asks:
    "Do these accepted nodes form one supported 2D sheet, or are some nodes disconnected
    islands / dangling one-neighbor hairs?"
    """
    summary = {
        "before_count": len(accepted_rows),
        "small_component_removed": 0,
        "dangling_removed": 0,
        "dangling_iterations": 0,
        "final_component_removed": 0,
        "after_count": len(accepted_rows),
    }
    if not surface_cleanup_enabled or len(accepted_rows) <= 1:
        return accepted_rows, summary

    row_by_key = {surface_node_key(row): row for row in accepted_rows}
    kept_keys = set(row_by_key)

    kept_keys, removed = keep_large_surface_components(kept_keys, ray_count)
    summary["small_component_removed"] = removed

    kept_keys, removed, iterations = remove_dangling_surface_endpoints(kept_keys, ray_count)
    summary["dangling_removed"] = removed
    summary["dangling_iterations"] = iterations

    # Endpoint pruning can split off a new small island. Do one final component pass so
    # the written surface remains a coherent sheet.
    kept_keys, removed = keep_large_surface_components(kept_keys, ray_count)
    summary["final_component_removed"] = removed

    cleaned_rows = [row for row in accepted_rows if surface_node_key(row) in kept_keys]
    summary["after_count"] = len(cleaned_rows)
    return cleaned_rows, summary


def fit_panel_model(
    history_rows: list[dict[str, float | int]],
    target_radius: float,
) -> dict[str, float] | None:
    """
    Predict the next local panel state in (radius_surface, stream_coord) space.

    The shock curve on one ray can be viewed as `x(r)`, where `x` is streamwise position
    and `r` is distance from the streamwise axis. We fit a local polynomial through the
    most recent accepted nodes, then evaluate that polynomial at `target_radius`. This is
    a smoother predictor than using only the last straight segment.
    """
    if len(history_rows) < 2:
        return None

    # Use only the most recent accepted points on this ray. Older points are still
    # useful physically, but the local shock shape near the current shell matters most.
    rows = history_rows[-panel_fit_node_count:]
    radii = np.asarray([float(row["radius_surface"]) for row in rows], dtype=float)
    stream_coords = np.asarray([float(row["stream_coord"]) for row in rows], dtype=float)
    sort_idx = np.argsort(radii)
    radii = radii[sort_idx]
    stream_coords = stream_coords[sort_idx]

    unique_radii = np.unique(radii)
    if unique_radii.size < 2:
        return None

    # Repeated radii should not normally occur, but keep the latest point if they do.
    if unique_radii.size != radii.size:
        unique_stream_coords = []
        for radius in unique_radii:
            unique_stream_coords.append(float(stream_coords[np.flatnonzero(radii == radius)[-1]]))
        radii = unique_radii
        stream_coords = np.asarray(unique_stream_coords, dtype=float)

    # Shift the radius origin to the last accepted shell before fitting. The polynomial
    # gives us a smooth local curve shape, but the actual last shock node anchors the
    # prediction so the fitted curve cannot jump away from accepted data at handoff.
    last_radius = float(radii[-1])
    last_stream = float(stream_coords[-1])
    fit_degree = min(int(panel_polynomial_degree), radii.size - 1)
    local_radii = radii - last_radius
    fit_coefficients = np.polyfit(local_radii, stream_coords, deg=fit_degree)
    slope_coefficients = np.polyder(fit_coefficients)

    target_local_radius = float(target_radius) - last_radius
    fit_at_last_radius = float(np.polyval(fit_coefficients, 0.0))
    fit_at_target_radius = float(np.polyval(fit_coefficients, target_local_radius))
    predicted_stream = last_stream + (fit_at_target_radius - fit_at_last_radius)
    slope = float(np.polyval(slope_coefficients, target_local_radius))
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
    axis_origin: np.ndarray,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert the 2D panel prediction back into a real 3D node line."""
    radial_unit = radial_unit_vector(theta, normal, spanwise)
    line_center = (
        np.asarray(axis_origin, dtype=float)
        + float(panel_model["predicted_stream"]) * np.asarray(streamwise, dtype=float)
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
    axis_origin: np.ndarray,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
    half_length: float,
    normal_step: float,
    min_height: float,
    dt: float,
    prediction_tolerance: float,
    debug_writer: TerminatedSearchLineDebugWriter | None,
    shell_index: int,
    ray_index: int,
) -> tuple[dict[str, float | int | np.ndarray] | None, float, str]:
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
        return None, 0.0, "no_panel_history"

    initial_center, initial_direction = build_panel_line(
        panel_model, theta, target_radius, axis_origin, streamwise, normal, spanwise
    )
    initial_sample = sample_line(gradient_mesh, initial_center, initial_direction, half_length, normal_step)
    initial_candidate, initial_rejection_reason, initial_rejected_candidate = find_shock_node_on_line_result(
        initial_sample,
        min_height=min_height,
        selection_mode=PEAK_MODE_NEAREST_CENTER,
        fallback_global=True,
        enforce_prominence_check=False,
        min_line_coordinate=-prediction_tolerance,
        max_line_coordinate=prediction_tolerance,
    )
    if initial_candidate is None:
        if debug_writer is not None:
            debug_writer.write_search_line(
                reason=f"panel_initial_{initial_rejection_reason or 'no_candidate'}",
                stage="panel_initial",
                line_sample=initial_sample,
                line_center=initial_center,
                line_direction=initial_direction,
                half_length=half_length,
                dt=dt,
                dn=normal_step,
                shell_layer=shell_index,
                ray_index=ray_index,
                azimuth_radians=theta,
                target_radius=target_radius,
                line_mode=LINE_MODE_PANEL_GUIDED,
                candidate=initial_rejected_candidate,
                prediction_tolerance=prediction_tolerance,
            )
        return None, 0.0, initial_rejection_reason or "no_candidate"

    initial_prediction_error = abs(float(initial_candidate["line_coordinate"]))
    if initial_prediction_error > prediction_tolerance:
        if debug_writer is not None:
            debug_writer.write_search_line(
                reason="panel_initial_prediction_tolerance_rejected",
                stage="panel_initial",
                line_sample=initial_sample,
                line_center=initial_center,
                line_direction=initial_direction,
                half_length=half_length,
                dt=dt,
                dn=normal_step,
                shell_layer=shell_index,
                ray_index=ray_index,
                azimuth_radians=theta,
                target_radius=target_radius,
                line_mode=LINE_MODE_PANEL_GUIDED,
                candidate=initial_candidate,
                prediction_error=initial_prediction_error,
                prediction_tolerance=prediction_tolerance,
            )
        return None, initial_prediction_error, "panel_initial_prediction_tolerance_rejected"

    history_radius_count = np.unique(
        np.asarray([float(row["radius_surface"]) for row in history_rows], dtype=float)
    ).size
    if history_radius_count < panel_corrector_min_history_nodes:
        return initial_candidate, initial_prediction_error, ""

    provisional_point = np.asarray(initial_candidate["point"], dtype=float)
    # The provisional row is the first guess. We temporarily pretend it is correct, refit
    # the local panel once, and then resample on that corrected line.
    provisional_row = {
        "stream_coord": float(np.dot(provisional_point - np.asarray(axis_origin, dtype=float), streamwise)),
        "radius_surface": float(target_radius),
    }
    corrected_model = fit_panel_model(history_rows + [provisional_row], target_radius)
    if corrected_model is None:
        return initial_candidate, abs(float(initial_candidate["line_coordinate"])), ""

    corrected_center, corrected_direction = build_panel_line(
        corrected_model, theta, target_radius, axis_origin, streamwise, normal, spanwise
    )
    corrected_sample = sample_line(gradient_mesh, corrected_center, corrected_direction, half_length, normal_step)
    corrected_candidate, _, _ = find_shock_node_on_line_result(
        corrected_sample,
        min_height=min_height,
        selection_mode=PEAK_MODE_NEAREST_CENTER,
        fallback_global=True,
        enforce_prominence_check=False,
        min_line_coordinate=-prediction_tolerance,
        max_line_coordinate=prediction_tolerance,
    )
    if corrected_candidate is None:
        prediction_error = initial_prediction_error
        if debug_writer is not None:
            debug_writer.write_search_line(
                reason="panel_prediction_tolerance_rejected",
                stage="panel_initial",
                line_sample=initial_sample,
                line_center=initial_center,
                line_direction=initial_direction,
                half_length=half_length,
                dt=dt,
                dn=normal_step,
                shell_layer=shell_index,
                ray_index=ray_index,
                azimuth_radians=theta,
                target_radius=target_radius,
                line_mode=LINE_MODE_PANEL_GUIDED,
                candidate=initial_candidate,
                prediction_error=prediction_error,
                prediction_tolerance=prediction_tolerance,
            )
        return initial_candidate, prediction_error, ""

    prediction_error = abs(float(corrected_candidate["line_coordinate"]))
    if prediction_error > prediction_tolerance and debug_writer is not None:
        debug_writer.write_search_line(
            reason="panel_prediction_tolerance_rejected",
            stage="panel_corrected",
            line_sample=corrected_sample,
            line_center=corrected_center,
            line_direction=corrected_direction,
            half_length=half_length,
            dt=dt,
            dn=normal_step,
            shell_layer=shell_index,
            ray_index=ray_index,
            azimuth_radians=theta,
            target_radius=target_radius,
            line_mode=LINE_MODE_PANEL_GUIDED,
            candidate=corrected_candidate,
            prediction_error=prediction_error,
            prediction_tolerance=prediction_tolerance,
        )
    return corrected_candidate, prediction_error, ""


def streamwise_candidate_for_shell_ray(
    gradient_mesh: pv.DataSet,
    history_rows: list[dict[str, float | int]],
    shell_radius: float,
    theta: float,
    axis_origin: np.ndarray,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
    half_length: float,
    normal_step: float,
    shell_spacing: float,
    prediction_tolerance: float,
    sensor_floor: float,
    debug_writer: TerminatedSearchLineDebugWriter | None,
    shell_index: int,
    ray_index: int,
    stage: str,
) -> tuple[dict[str, float | int | np.ndarray] | None, str]:
    """
    Sample a local streamwise fallback line for one shell/ray location.

    This is the conservative line-search path. It is centered on the last accepted point
    for the same ray, then shifted outward to the target shell radius.
    """
    radial_unit = radial_unit_vector(theta, normal, spanwise)
    bootstrap_stream = float(history_rows[-1]["stream_coord"])
    line_center = (
        axis_origin
        + bootstrap_stream * np.asarray(streamwise, dtype=float)
        + float(shell_radius) * radial_unit
    )
    line_direction = np.asarray(streamwise, dtype=float)
    line_sample = sample_line(gradient_mesh, line_center, line_direction, half_length, normal_step)
    candidate, rejection_reason, rejected_candidate = find_shock_node_on_line_result(
        line_sample,
        min_height=sensor_floor,
        selection_mode=PEAK_MODE_NEAREST_CENTER,
        fallback_global=True,
        enforce_prominence_check=False,
        min_line_coordinate=-prediction_tolerance,
        max_line_coordinate=prediction_tolerance,
    )
    if candidate is None and debug_writer is not None:
        debug_writer.write_search_line(
            reason=f"{stage}_{rejection_reason or 'no_candidate'}",
            stage=stage,
            line_sample=line_sample,
            line_center=line_center,
            line_direction=line_direction,
            half_length=half_length,
            dt=shell_spacing,
            dn=normal_step,
            shell_layer=shell_index,
            ray_index=ray_index,
            azimuth_radians=theta,
            target_radius=shell_radius,
            line_mode=LINE_MODE_STREAMWISE,
            candidate=rejected_candidate,
        )
    return candidate, rejection_reason


# --- Main shock-surface marching routine --------------------------------------
def extract_panel_surface(
    gradient_mesh: pv.DataSet,
    active_points: np.ndarray,
    dt: float,
    dn: float,
    axis_origin: np.ndarray,
    axis_origin_source: str,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
    debug_writer: TerminatedSearchLineDebugWriter | None = None,
) -> tuple[pv.PolyData, dict[str, float | int | str]]:
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
    axis_origin = np.asarray(axis_origin, dtype=float)
    stream_center, stream_half_length = build_streamwise_window(
        active_points, streamwise, normal, spanwise, dn, axis_origin
    )
    stream_axis_center = axis_origin + float(stream_center) * np.asarray(streamwise, dtype=float)
    normal_step = dn
    sampling_diagonal = math.hypot(dt, dn)
    search_line_half_length = search_line_half_length_sampling_diagonal_factor * sampling_diagonal
    epsilon_tol = epsilon_tol_sampling_diagonal_factor * sampling_diagonal
    max_surface_radius = max(float(np.max(perpendicular_radius(active_points, streamwise, origin=axis_origin))), dt)
    azimuth_angles = build_surface_azimuth_rays(max_surface_radius, dt)
    ray_count = len(azimuth_angles)
    max_shell_count = int(shell_iteration_safety_limit)
    progress(
        f"  [stage] marching shock surface with {ray_count} rays, dt={dt:.4f}, dn={dn:.4f}, "
        f"search_half_length={search_line_half_length:.4f}, epsilon_tol={epsilon_tol:.4f}, "
        f"streamwise_bootstrap_nodes={streamwise_bootstrap_node_count}, "
        f"warmup_fallback_nodes={panel_guided_warmup_fallback_node_count}, "
        f"panel_fit_nodes={panel_fit_node_count}, panel_poly_degree={panel_polynomial_degree}, "
        f"safety_limit={max_shell_count}"
    )
    progress(
        f"  [stage] streamwise marching axis anchored by {axis_origin_source} at "
        f"x={axis_origin[0]:.4f}, y={axis_origin[1]:.4f}, z={axis_origin[2]:.4f}"
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
        stream_axis_center,
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
        "stream_coord": float(np.dot(stagnation_point - axis_origin, streamwise)),
        "density": float(stagnation_candidate["density"]),
        "shock_sensor": float(stagnation_candidate["shock_sensor_smoothed"]),
        "shock_sensor_raw": float(stagnation_candidate["shock_sensor_raw"]),
        "shock_sensor_prominence": float(stagnation_candidate["shock_sensor_prominence"]),
        "shock_sensor_prominence_ratio": float(stagnation_candidate["shock_sensor_prominence_ratio"]),
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

    termination_reason = "reached_safety_limit"
    termination_shell = max_shell_count
    termination_detail = (
        f"completed the runaway safety limit of {max_shell_count} shells; "
        "this should not happen during normal extraction"
    )

    # March outward shell by shell. Each shell contains one candidate node line per ray.
    for shell_index in range(1, max_shell_count + 1):
        shell_radius = float(shell_index) * dt
        # We collect a full shell first, then commit it afterward. That way one bad
        # ray does not partially mutate the accepted surface mid-shell.
        accepted_rows_in_shell: list[dict[str, float | int]] = []
        streamwise_accept_count = 0
        panel_guided_accept_count = 0
        no_candidate_count = 0
        prominence_reject_count = 0
        tolerance_reject_count = 0
        neighbor_reject_count = 0
        fallback_accept_count = 0
        weak_prominence_keep_count = 0
        progress(f"  [shell {shell_index}] radius_surface={shell_radius:.4f}")
        for ray_index, theta in enumerate(azimuth_angles):
            line_rejection_reason = ""

            history_rows = panel_history_for_ray(stagnation_row, ray_history, ray_index)
            if len(history_rows) <= streamwise_bootstrap_node_count:
                # The nose region is strongly curved, so the first few shells bootstrap
                # each ray with streamwise lines before polynomial-guided marching. Keep
                # each bootstrap line local to the last accepted shock node on that ray;
                # scanning the entire domain here can jump to a different shock/gradient.
                line_mode = LINE_MODE_STREAMWISE
                candidate, line_rejection_reason = streamwise_candidate_for_shell_ray(
                    gradient_mesh,
                    history_rows,
                    shell_radius,
                    theta,
                    axis_origin,
                    streamwise,
                    normal,
                    spanwise,
                    search_line_half_length,
                    normal_step,
                    dt,
                    epsilon_tol,
                    sensor_floor,
                    debug_writer,
                    shell_index,
                    ray_index,
                    "streamwise_bootstrap",
                )
                prediction_error = 0.0
            else:
                # Later shells can use the ray's previously accepted nodes to predict a better
                # shock-normal direction.
                candidate, prediction_error, line_rejection_reason = predictor_corrector_candidate(
                    gradient_mesh,
                    history_rows,
                    shell_radius,
                    theta,
                    axis_origin,
                    streamwise,
                    normal,
                    spanwise,
                    search_line_half_length,
                    normal_step,
                    sensor_floor,
                    dt,
                    epsilon_tol,
                    debug_writer,
                    shell_index,
                    ray_index,
                )
                panel_failed = candidate is None or prediction_error > epsilon_tol
                can_streamwise_fallback = len(history_rows) <= panel_guided_warmup_fallback_node_count
                if panel_failed and can_streamwise_fallback:
                    fallback_candidate, fallback_reason = streamwise_candidate_for_shell_ray(
                        gradient_mesh,
                        history_rows,
                        shell_radius,
                        theta,
                        axis_origin,
                        streamwise,
                        normal,
                        spanwise,
                        search_line_half_length,
                        normal_step,
                        dt,
                        epsilon_tol,
                        sensor_floor,
                        debug_writer,
                        shell_index,
                        ray_index,
                        "streamwise_warmup_fallback",
                    )
                    if fallback_candidate is not None:
                        candidate = fallback_candidate
                        line_rejection_reason = ""
                        prediction_error = 0.0
                        line_mode = LINE_MODE_STREAMWISE
                        fallback_accept_count += 1
                    else:
                        candidate = None
                        line_rejection_reason = fallback_reason or line_rejection_reason
                elif not panel_failed:
                    line_mode = LINE_MODE_PANEL_GUIDED

                if candidate is None:
                    if line_rejection_reason == "peak_prominence_rejected":
                        prominence_reject_count += 1
                    else:
                        no_candidate_count += 1
                    continue
                # Reject panel candidates that drift too far from the panel prediction after
                # the warmup fallback window has ended.
                if int(line_mode) == LINE_MODE_PANEL_GUIDED and prediction_error > epsilon_tol:
                    tolerance_reject_count += 1
                    continue

            if candidate is None:
                if line_rejection_reason == "peak_prominence_rejected":
                    prominence_reject_count += 1
                else:
                    no_candidate_count += 1
                continue

            point = np.asarray(candidate["point"], dtype=float)
            prominence_ratio = float(candidate["shock_sensor_prominence_ratio"])
            prominence_ok = (
                int(line_mode) != LINE_MODE_PANEL_GUIDED
                or shell_radius < panel_prominence_check_min_radius
                or prominence_ratio >= line_peak_acceptance_prominence_ratio
            )
            row = {
                "x": float(point[0]),
                "y": float(point[1]),
                "z": float(point[2]),
                "stream_coord": float(np.dot(point - axis_origin, streamwise)),
                "density": float(candidate["density"]),
                "shock_sensor": float(candidate["shock_sensor_smoothed"]),
                "shock_sensor_raw": float(candidate["shock_sensor_raw"]),
                "shock_sensor_prominence": float(candidate["shock_sensor_prominence"]),
                "shock_sensor_prominence_ratio": prominence_ratio,
                "prominence_ok": int(prominence_ok),
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

        accepted_rows_in_shell, weak_prominence_rejected_rows, weak_prominence_keep_count = (
            reject_unsupported_weak_prominence_rows(accepted_rows_in_shell, ray_count)
        )
        if weak_prominence_rejected_rows:
            prominence_reject_count += len(weak_prominence_rejected_rows)
            streamwise_accept_count, panel_guided_accept_count = count_line_modes(accepted_rows_in_shell)

        if shell_radius <= shell_neighbor_check_max_radius and accepted_rows_in_shell:
            stream_tolerance = max(
                shell_neighbor_stream_tolerance_factor * epsilon_tol,
                4.0 * dt,
            )
            accepted_rows_in_shell, neighbor_rejected_rows = reject_shell_neighbor_outliers(
                accepted_rows_in_shell,
                ray_count,
                stream_tolerance,
            )
            neighbor_reject_count = len(neighbor_rejected_rows)
            if neighbor_reject_count:
                streamwise_accept_count, panel_guided_accept_count = count_line_modes(accepted_rows_in_shell)

        # If an entire shell finds no accepted shock nodes, the outward marching stops here.
        if not accepted_rows_in_shell:
            termination_reason = "empty_shell"
            termination_shell = shell_index
            termination_detail = (
                f"shell {shell_index} accepted 0/{ray_count} nodes "
                f"({no_candidate_count} no-candidate, {prominence_reject_count} prominence-rejected, "
                f"{tolerance_reject_count} tolerance-rejected, {neighbor_reject_count} neighbor-rejected)"
            )
            progress(f"  [shell {shell_index}] accepted 0/{ray_count} shock nodes -> stopping")
            break

        shell_message = (
            f"  [shell {shell_index}] accepted {len(accepted_rows_in_shell)}/{ray_count} shock nodes "
            f"({streamwise_accept_count} streamwise, {panel_guided_accept_count} panel-guided)"
        )
        if fallback_accept_count:
            shell_message += f", {fallback_accept_count} warmup fallback"
        if weak_prominence_keep_count:
            shell_message += f", kept {weak_prominence_keep_count} weak-prominence gap node(s)"
        if no_candidate_count or prominence_reject_count or tolerance_reject_count or neighbor_reject_count:
            shell_message += (
                f", terminated lines: {no_candidate_count} no-candidate, "
                f"{prominence_reject_count} prominence-rejected, "
                f"{tolerance_reject_count} tolerance-rejected, "
                f"{neighbor_reject_count} neighbor-rejected"
            )
        progress(shell_message)

        terminated_count = ray_count - len(accepted_rows_in_shell)
        terminated_fraction = terminated_count / float(ray_count)
        if (
            max_terminated_search_line_fraction is not None
            and terminated_fraction >= max_terminated_search_line_fraction
        ):
            termination_reason = "too_many_terminated_search_lines"
            termination_shell = shell_index
            termination_detail = (
                f"shell {shell_index} terminated {terminated_count}/{ray_count} search lines "
                f"({terminated_fraction:.1%}), at or above "
                f"max_terminated_search_line_fraction={max_terminated_search_line_fraction:.1%}"
            )
            progress(
                f"  [shell {shell_index}] terminated {terminated_count}/{ray_count} search lines "
                f"({terminated_fraction:.1%}) -> stopping before adding this sparse shell"
            )
            break

        # A mostly failed shell can create long, spiky strips if we keep marching.
        # Once fewer than this many rays survive, treat the shock surface as ended.
        if len(accepted_rows_in_shell) < minimum_azimuth_rays:
            termination_reason = "too_few_accepted_rays"
            termination_shell = shell_index
            termination_detail = (
                f"shell {shell_index} accepted {len(accepted_rows_in_shell)}/{ray_count} nodes, "
                f"below minimum_azimuth_rays={minimum_azimuth_rays}"
            )
            progress(
                f"  [shell {shell_index}] fewer than {minimum_azimuth_rays} accepted rays "
                "-> stopping before adding this sparse shell"
            )
            break

        # Only commit a shell after the full ring has been tested.
        for row in accepted_rows_in_shell:
            point = np.asarray([row["x"], row["y"], row["z"]], dtype=float)
            local_idx = len(accepted_shock_nodes)
            accepted_shock_nodes.append(point)
            shell_ray = (int(row["shell_layer"]), int(row["ray_index"]))
            shock_node_index_by_shell_ray[shell_ray] = local_idx
            accepted_rows.append(row)
            ray_history[int(row["ray_index"])].append(row)

    progress(
        f"  [stop] marching termination: {termination_reason} "
        f"(shell={termination_shell}, {termination_detail})"
    )

    accepted_rows, cleanup_summary = cleanup_accepted_surface_nodes(accepted_rows, ray_count)
    removed_by_cleanup = cleanup_summary["before_count"] - cleanup_summary["after_count"]
    if removed_by_cleanup:
        progress(
            f"  [cleanup] removed {removed_by_cleanup} straggler node(s): "
            f"{cleanup_summary['small_component_removed']} small-component, "
            f"{cleanup_summary['dangling_removed']} dangling-endpoint "
            f"over {cleanup_summary['dangling_iterations']} pass(es), "
            f"{cleanup_summary['final_component_removed']} final-component"
        )
    else:
        progress("  [cleanup] no straggler nodes removed")

    # Rebuild the point list and `(shell, ray) -> point index` map after cleanup. This keeps
    # the written VTP/CSV and the triangulation in sync with the accepted node set.
    accepted_shock_nodes = []
    shock_node_index_by_shell_ray = {}
    for row in accepted_rows:
        point = np.asarray([row["x"], row["y"], row["z"]], dtype=float)
        local_idx = len(accepted_shock_nodes)
        accepted_shock_nodes.append(point)
        shock_node_index_by_shell_ray[surface_node_key(row)] = local_idx

    # Build the actual ParaView surface object, then attach the per-point metadata so
    # the same information is available in ParaView and in the CSV export.
    poly = pv.PolyData(np.asarray(accepted_shock_nodes))
    poly.point_data["Density"] = np.asarray([row["density"] for row in accepted_rows], dtype=float)
    poly.point_data["ShockSensor"] = np.asarray([row["shock_sensor"] for row in accepted_rows], dtype=float)
    poly.point_data["ShockSensorRaw"] = np.asarray([row["shock_sensor_raw"] for row in accepted_rows], dtype=float)
    poly.point_data["ShockSensorProminence"] = np.asarray(
        [row["shock_sensor_prominence"] for row in accepted_rows], dtype=float
    )
    poly.point_data["ShockSensorProminenceRatio"] = np.asarray(
        [row["shock_sensor_prominence_ratio"] for row in accepted_rows], dtype=float
    )
    poly.point_data["RadiusSurface"] = np.asarray([row["radius_surface"] for row in accepted_rows], dtype=float)
    poly.point_data["AzimuthRadians"] = np.asarray([row["azimuth_radians"] for row in accepted_rows], dtype=float)
    poly.point_data["ShellLayer"] = np.asarray([row["shell_layer"] for row in accepted_rows], dtype=int)
    poly.point_data["RayIndex"] = np.asarray([row["ray_index"] for row in accepted_rows], dtype=int)
    poly.point_data["LineIndex"] = np.asarray([row["line_index"] for row in accepted_rows], dtype=int)
    poly.point_data["LineModeCode"] = np.asarray([row["line_mode"] for row in accepted_rows], dtype=int)
    poly.point_data["PredictionError"] = np.asarray([row["prediction_error"] for row in accepted_rows], dtype=float)
    poly.point_data["StreamCoord"] = np.asarray([row["stream_coord"] for row in accepted_rows], dtype=float)
    poly.field_data["BodyAnchor"] = np.asarray(axis_origin, dtype=float).reshape(1, 3)
    poly.field_data["StreamwiseBasis"] = np.asarray(streamwise, dtype=float).reshape(1, 3)
    poly.field_data["NormalBasis"] = np.asarray(normal, dtype=float).reshape(1, 3)
    poly.field_data["SpanwiseBasis"] = np.asarray(spanwise, dtype=float).reshape(1, 3)

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

            c0, c1, c2, c3 = [int(corner) for corner in corners]
            faces.extend([3, c0, c1, c2, 3, c0, c2, c3])

    if faces:
        poly.faces = np.asarray(faces, dtype=np.int64)
    progress(f"  [stage] surface triangulation complete ({poly.n_points} points, {poly.n_cells} cells)")

    summary: dict[str, float | int | str] = {
        "point_count": poly.n_points,
        "cell_count": poly.n_cells,
        "center_peak": center_peak,
        "sensor_floor": sensor_floor,
        "prediction_tolerance": epsilon_tol,
        "dt": dt,
        "dn": dn,
        "ray_count": ray_count,
        "max_shell_layer": max_shell_layer,
        "termination_reason": termination_reason,
        "termination_shell": termination_shell,
        "panel_lines": sum(1 for row in accepted_rows if int(row["line_mode"]) == LINE_MODE_PANEL_GUIDED),
        "streamwise_lines": sum(1 for row in accepted_rows if int(row["line_mode"]) == LINE_MODE_STREAMWISE),
        "cleanup_removed": removed_by_cleanup,
        "cleanup_dangling_removed": cleanup_summary["dangling_removed"],
        "cleanup_small_component_removed": cleanup_summary["small_component_removed"]
        + cleanup_summary["final_component_removed"],
    }
    return poly, summary

# --- Case-level orchestration -------------------------------------------------
@dataclass
class PreparedShockField:
    """Flow-derived data that can be reused for several extractor sampling settings."""

    gradient_mesh: pv.DataSet
    active_points: np.ndarray
    body_anchor: np.ndarray
    body_anchor_source: str
    streamwise: np.ndarray
    normal: np.ndarray
    spanwise: np.ndarray
    aoa_degrees: float


def prepare_shock_field(
    paths: StudyPaths,
    case_path: Path,
    stage_times: dict[str, float] | None = None,
) -> PreparedShockField:
    """Read and differentiate one flow field for one or more extraction runs."""
    if stage_times is None:
        stage_times = {}

    vtu_path = case_path / vtu_name
    progress(f"  [stage] reading flow field: {vtu_path}")
    with timed_stage(stage_times, "read flow field"):
        mesh = pv.read(vtu_path)
    if density_scalar not in mesh.point_data and density_scalar in mesh.cell_data:
        progress("  [stage] converting cell data to point data")
        with timed_stage(stage_times, "convert cell data to point data"):
            mesh = mesh.cell_data_to_point_data()

    if density_scalar not in mesh.array_names:
        available = ", ".join(sorted(mesh.array_names))
        raise KeyError(f"{density_scalar!r} not found. Available arrays: {available}")

    progress("  [stage] differentiating 3D density field")
    with timed_stage(stage_times, "differentiate 3D density field"):
        with vtk_warning_mode(suppress_vtk_warnings):
            gradient_mesh = mesh.compute_derivative(scalars=density_scalar, gradient=True)

    with timed_stage(stage_times, "build frame and active shock region"):
        aoa_degrees = load_case_aoa_degrees(paths.generated_config_dir, case_path)
        progress(f"  [stage] building AoA-aligned frame (aoa={aoa_degrees:.1f} deg)")
        streamwise, normal, spanwise = streamwise_basis_from_aoa(aoa_degrees)
        body_anchor, body_anchor_source = choose_body_stagnation_anchor(
            paths.study_root,
            case_path,
            streamwise,
        )
        progress(
            f"  [stage] body stagnation anchor from {body_anchor_source}: "
            f"x={body_anchor[0]:.4f}, y={body_anchor[1]:.4f}, z={body_anchor[2]:.4f}"
        )
        points = np.asarray(gradient_mesh.points)
        gradient = np.asarray(gradient_mesh["gradient"], dtype=float)
        gradient = np.nan_to_num(gradient, nan=0.0, posinf=0.0, neginf=0.0)
        shock_sensor_raw = np.linalg.norm(gradient, axis=1)
        gradient_mesh["ShockSensorRaw"] = shock_sensor_raw

        progress("  [stage] locating stagnation shock node and active shock region")
        _, center_peak = choose_stagnation_shock_node(points, shock_sensor_raw, streamwise, body_anchor)
        active_points = points[shock_sensor_raw >= center_peak * surface_sensor_min_fraction]
        if active_points.size == 0:
            raise ValueError("no active points passed the surface sensor threshold")

    return PreparedShockField(
        gradient_mesh=gradient_mesh,
        active_points=active_points,
        body_anchor=body_anchor,
        body_anchor_source=body_anchor_source,
        streamwise=streamwise,
        normal=normal,
        spanwise=spanwise,
        aoa_degrees=aoa_degrees,
    )


def extract_prepared_surface(
    prepared: PreparedShockField,
    dt: float,
    dn: float,
    debug_writer: TerminatedSearchLineDebugWriter | None = None,
) -> tuple[pv.PolyData, dict[str, float | int | str]]:
    """Run panel marching on an already differentiated flow field."""
    return extract_panel_surface(
        prepared.gradient_mesh,
        prepared.active_points,
        dt,
        dn,
        prepared.body_anchor,
        prepared.body_anchor_source,
        prepared.streamwise,
        prepared.normal,
        prepared.spanwise,
        debug_writer=debug_writer,
    )


def process_case(paths: StudyPaths, case_dir: str):
    """Run the full panel shock extraction pipeline for one CFD case folder."""
    case_start_time = time.perf_counter()
    stage_times: dict[str, float] = {}
    case_path = resolve_case_path(paths.study_root, paths.cases_dir, case_dir)
    vtu_path = case_path / vtu_name
    if not vtu_path.exists():
        progress(f"  [skip] no {vtu_name} in {case_path.name}")
        return

    prepared = prepare_shock_field(paths, case_path, stage_times)

    dt, dn = configured_sampling_steps()
    debug_export_enabled = env_flag("CFD_EXPORT_TERMINATED_SEARCH_LINES", export_terminated_search_lines)
    debug_export_limit = env_int("CFD_TERMINATED_SEARCH_LINE_LIMIT", terminated_search_line_max_lines)
    debug_export_stride = env_int("CFD_TERMINATED_SEARCH_LINE_STRIDE", terminated_search_line_stride)
    debug_writer = TerminatedSearchLineDebugWriter(
        case_path,
        debug_export_enabled,
        debug_export_limit,
        debug_export_stride,
    )
    if debug_export_enabled:
        limit_label = "all" if debug_export_limit == 0 else str(debug_export_limit)
        progress(
            f"  [debug] terminated search-line export enabled "
            f"(limit={limit_label}, stride={debug_writer.line_stride}, "
            f"output={debug_writer.summary_csv_path}, {debug_writer.profiles_csv_path})"
        )
    # `dt` controls the shell-to-shell spacing; `dn` controls the sample spacing
    # along each probe line.
    progress(
        f"  [stage] extracting shock surface (active points={prepared.active_points.shape[0]}, "
        f"dt={dt:.4f}, dn={dn:.4f})"
    )
    try:
        with timed_stage(stage_times, "extract shock surface"):
            surface, summary = extract_prepared_surface(
                prepared,
                dt,
                dn,
                debug_writer=debug_writer,
            )
    finally:
        debug_writer.close()
    progress("  [stage] writing surface outputs")
    with timed_stage(stage_times, "write surface outputs"):
        surface_path, csv_path = write_surface_outputs(case_path, surface)
    elapsed_seconds = time.perf_counter() - case_start_time

    progress(
        f"  [ok ] wrote {surface_path} ({surface.n_points} pts, {surface.n_cells} tris, "
        f"aoa={prepared.aoa_degrees:.1f}, center_peak={summary['center_peak']:.3f}, "
        f"dt={summary['dt']:.4f}, dn={summary['dn']:.4f}, rays={summary['ray_count']}, "
        f"panel_lines={summary['panel_lines']}, streamwise_lines={summary['streamwise_lines']}, "
        f"max_shell={summary['max_shell_layer']}, cleanup_removed={summary['cleanup_removed']}, "
        f"elapsed={elapsed_seconds / 60.0:.1f} min)"
    )
    progress(f"  [ok ] wrote {csv_path}")
    progress(
        f"  [stop] termination summary: {summary['termination_reason']} "
        f"at shell {summary['termination_shell']}"
    )
    if debug_export_enabled:
        if debug_writer.line_count > 0:
            progress(
                f"  [debug] wrote {debug_writer.summary_csv_path} and {debug_writer.profiles_csv_path} "
                f"({debug_writer.line_count}/{debug_writer.observed_line_count} terminated lines sampled, "
                f"{debug_writer.sample_count} samples, stride={debug_writer.line_stride})"
            )
        else:
            progress("  [debug] no terminated search lines were exported")
    progress("  [time ] timing summary:")
    for stage_name, stage_seconds in stage_times.items():
        progress(f"  [time ]   {stage_name}: {stage_seconds:.1f} s")
    progress(f"  [time ]   total: {elapsed_seconds:.1f} s")


def main() -> int:
    env_study = os.environ.get("CFD_STUDY", "").strip()
    paths = get_study_paths(env_study) if env_study else choose_study_paths_interactively()

    print("\n╔══════════════════════════════════════════════╗")
    print("║   Panel Shock Surface Extractor             ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"Study: {paths.study_name}")
    print(f"Flow file: {vtu_name}")
    print(f"Density scalar: {density_scalar}")
    dt, dn = configured_sampling_steps()
    print(
        f"Spacing from code settings: dt={dt:.4f}, dn={dn:.4f}, "
        f"sensor floor: {surface_sensor_min_fraction:g} of center peak, "
        f"savgol smoothing length/poly: {savgol_smoothing_length:.4f}/{savgol_poly_order}, "
        f"panel predictor: degree {panel_polynomial_degree} using {panel_fit_node_count} nodes, "
        f"peak prominence ratio min: {line_peak_acceptance_prominence_ratio:.3f} "
        f"after radius {panel_prominence_check_min_radius:.2f}, "
        f"surface cleanup: {'on' if surface_cleanup_enabled else 'off'}"
    )
    if env_flag("CFD_EXPORT_TERMINATED_SEARCH_LINES", export_terminated_search_lines):
        limit = env_int("CFD_TERMINATED_SEARCH_LINE_LIMIT", terminated_search_line_max_lines)
        stride = max(1, env_int("CFD_TERMINATED_SEARCH_LINE_STRIDE", terminated_search_line_stride))
        limit_label = "all" if limit == 0 else str(limit)
        print(
            f"Terminated search-line debug export: on "
            f"(limit={limit_label}, stride={stride}, files={terminated_search_line_summary_csv_name}, "
            f"{terminated_search_line_profiles_csv_name})"
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
