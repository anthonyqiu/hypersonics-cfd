#!/usr/bin/env python3
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np


AOA_LINE_RE = re.compile(r"^\s*AOA\s*=\s*([-+0-9.eE]+)")
AOA_NAME_RE = re.compile(r"_aoa(\d+(?:p\d+)?)")


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


def load_case_aoa_degrees(root: Path, case_path: Path) -> float:
    """Get the case AoA, preferring generated/local config files over the folder name."""
    generated_cfg = root / "config" / "generated" / f"{case_path.name}.cfg"
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
    - streamwise: freestream direction, rotated in the x-z plane
    - normal: local up/down direction in the AoA plane
    - spanwise: unchanged global y direction
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

    This is the "sideways" distance from the tilted centerline, not distance from the body.
    """
    pts = np.asarray(points, dtype=float)
    axial = np.outer(pts @ streamwise, streamwise)
    return np.linalg.norm(pts - axial, axis=1)


def point_from_frame(
    stream_coord: float,
    normal_coord: float,
    span_coord: float,
    streamwise: np.ndarray,
    normal: np.ndarray,
    spanwise: np.ndarray,
) -> np.ndarray:
    """Convert one local frame coordinate back into the global xyz system."""
    return (
        float(stream_coord) * np.asarray(streamwise, dtype=float)
        + float(normal_coord) * np.asarray(normal, dtype=float)
        + float(span_coord) * np.asarray(spanwise, dtype=float)
    )
