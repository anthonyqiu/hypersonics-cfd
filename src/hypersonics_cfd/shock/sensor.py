"""One-dimensional shock-sensor smoothing and peak selection."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks, savgol_filter


PEAK_MODE_FIRST_UPSTREAM = "first_upstream"
PEAK_MODE_NEAREST_CENTER = "nearest_center"


@dataclass(frozen=True)
class PeakSettings:
    default_spacing: float = 0.01
    smoothing_length: float = 0.25
    min_window_points: int = 9
    max_window_points: int = 31
    poly_order: int = 3
    height_fraction: float = 0.05
    detection_prominence_fraction: float = 0.02
    acceptance_prominence_ratio: float = 0.02


DEFAULT_PEAK_SETTINGS = PeakSettings()
savgol_smoothing_length = DEFAULT_PEAK_SETTINGS.smoothing_length
savgol_min_window_points = DEFAULT_PEAK_SETTINGS.min_window_points
savgol_max_window_points = DEFAULT_PEAK_SETTINGS.max_window_points
savgol_poly_order = DEFAULT_PEAK_SETTINGS.poly_order
line_peak_height_fraction = DEFAULT_PEAK_SETTINGS.height_fraction
line_peak_detection_prominence_fraction = DEFAULT_PEAK_SETTINGS.detection_prominence_fraction
line_peak_acceptance_prominence_ratio = DEFAULT_PEAK_SETTINGS.acceptance_prominence_ratio


def autoscaled_savgol_window_points(
    sample_spacing: float,
    segment_size: int,
    settings: PeakSettings = DEFAULT_PEAK_SETTINGS,
) -> int:
    """Convert a physical smoothing length into an odd Savitzky-Golay window."""
    if segment_size < 3:
        return segment_size
    if sample_spacing <= 0.0:
        raise ValueError("sample spacing must be positive")

    min_window = max(3, settings.min_window_points, settings.poly_order + 2)
    if min_window % 2 == 0:
        min_window += 1
    max_window = max(min_window, settings.max_window_points)
    if max_window % 2 == 0:
        max_window -= 1
    target = max(min_window, int(math.ceil(settings.smoothing_length / sample_spacing)))
    if target % 2 == 0:
        target += 1
    target = min(target, max_window)
    segment_limit = segment_size if segment_size % 2 else segment_size - 1
    return min(target, segment_limit)


def smooth_line_profile(
    values,
    valid_mask,
    line_coordinates,
    settings: PeakSettings = DEFAULT_PEAK_SETTINGS,
):
    """Smooth only the continuous valid portion of a sampled search line."""
    values = np.asarray(values, dtype=float)
    valid_mask = np.asarray(valid_mask, dtype=bool)
    line_coordinates = np.asarray(line_coordinates, dtype=float)
    smoothed = np.zeros_like(values)
    valid_idx = np.flatnonzero(valid_mask)
    if valid_idx.size == 0:
        return smoothed

    start = int(valid_idx[0])
    stop = int(valid_idx[-1]) + 1
    segment = values[start:stop]
    if segment.size < 3:
        smoothed[start:stop] = segment
        return smoothed
    spacing = (
        abs(float(line_coordinates[1] - line_coordinates[0]))
        if line_coordinates.size >= 2
        else settings.default_spacing
    )
    window = autoscaled_savgol_window_points(spacing, segment.size, settings)
    if window < 3:
        smoothed[start:stop] = segment
        return smoothed
    poly_order = min(settings.poly_order, window - 1)
    smoothed[start:stop] = savgol_filter(
        segment,
        window_length=window,
        polyorder=poly_order,
        mode="interp",
    )
    return smoothed


def find_shock_node_on_line_result(
    line_sample,
    min_height,
    selection_mode,
    fallback_global,
    enforce_prominence_check=True,
    min_line_coordinate=None,
    max_line_coordinate=None,
    settings: PeakSettings = DEFAULT_PEAK_SETTINGS,
):
    """Select one shock-sensor peak from a sampled search line."""
    line_coordinates = np.asarray(line_sample["line_coordinates"], dtype=float)
    search_mask = np.asarray(line_sample["valid_mask"], dtype=bool).copy()
    if min_line_coordinate is not None:
        search_mask &= line_coordinates >= float(min_line_coordinate)
    if max_line_coordinate is not None:
        search_mask &= line_coordinates <= float(max_line_coordinate)

    valid_idx = np.flatnonzero(search_mask)
    if valid_idx.size == 0:
        return None, "no_valid_samples", None

    smoothed = smooth_line_profile(
        line_sample["shock_sensor_raw"],
        search_mask,
        line_coordinates,
        settings,
    )
    start = int(valid_idx[0])
    stop = int(valid_idx[-1]) + 1
    segment = smoothed[start:stop]
    local_max = float(np.max(segment))
    height = max(float(min_height), local_max * settings.height_fraction)
    prominence = local_max * settings.detection_prominence_fraction
    peaks, properties = find_peaks(segment, height=height, prominence=prominence)
    indices = [start + int(index) for index in peaks]
    prominence_by_index = {
        start + int(index): float(properties["prominences"][offset])
        for offset, index in enumerate(peaks)
    }

    if indices:
        if selection_mode == PEAK_MODE_FIRST_UPSTREAM:
            peak_index = indices[0]
        elif selection_mode == PEAK_MODE_NEAREST_CENTER:
            peak_index = min(indices, key=lambda index: abs(float(line_coordinates[index])))
        else:
            raise ValueError(f"unknown peak selection mode: {selection_mode}")
    elif fallback_global:
        peak_index = int(start + np.argmax(segment))
        if smoothed[peak_index] <= 0.0:
            return None, "nonpositive_global_peak", None
    else:
        return None, "no_detected_peak", None

    peak_height = float(smoothed[peak_index])
    peak_prominence = float(prominence_by_index.get(peak_index, 0.0))
    peak_prominence_ratio = peak_prominence / max(
        abs(peak_height), np.finfo(float).eps
    )
    candidate = {
        "point": line_sample["points"][peak_index],
        "density": float(line_sample["density"][peak_index]),
        "shock_sensor_raw": float(line_sample["shock_sensor_raw"][peak_index]),
        "shock_sensor_smoothed": peak_height,
        "shock_sensor_prominence": peak_prominence,
        "shock_sensor_prominence_ratio": peak_prominence_ratio,
        "sample_index": peak_index,
        "line_coordinate": float(line_coordinates[peak_index]),
    }
    if (
        enforce_prominence_check
        and peak_prominence_ratio < settings.acceptance_prominence_ratio
    ):
        return None, "peak_prominence_rejected", candidate
    return candidate, "", None
