"""Coordinate frames used by shock extraction and surface comparison."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ShockFrame:
    """
    Body-fixed frame for a shock surface.

    `streamwise` points downstream. `polar_angle` is measured away from the
    upstream direction, while `azimuth` rotates around the streamwise axis.
    """

    origin: np.ndarray
    streamwise: np.ndarray
    normal: np.ndarray
    spanwise: np.ndarray

    @classmethod
    def from_aoa(cls, aoa_degrees: float, origin=None):
        streamwise, normal, spanwise = streamwise_basis_from_aoa(aoa_degrees)
        if origin is None:
            origin = np.zeros(3)
        return cls(np.asarray(origin, dtype=float), streamwise, normal, spanwise)

    def with_origin(self, origin):
        return ShockFrame(
            np.asarray(origin, dtype=float),
            self.streamwise,
            self.normal,
            self.spanwise,
        )

    def local_coordinates(self, points):
        relative = np.asarray(points, dtype=float) - self.origin
        return np.column_stack(
            (
                relative @ self.streamwise,
                relative @ self.normal,
                relative @ self.spanwise,
            )
        )

    def cylindrical_coordinates(self, points):
        local = self.local_coordinates(points)
        stream_position = local[:, 0]
        transverse_radius = np.hypot(local[:, 1], local[:, 2])
        azimuth = np.mod(np.arctan2(local[:, 2], local[:, 1]), 2.0 * np.pi)
        return stream_position, transverse_radius, azimuth

    def spherical_coordinates(self, points):
        """
        Return `(radial_distance, polar_angle, azimuth)`.

        The upstream stagnation direction has `polar_angle=0`; downstream has
        `polar_angle=pi`.
        """
        stream_position, transverse_radius, azimuth = self.cylindrical_coordinates(points)
        radial_distance = np.hypot(stream_position, transverse_radius)
        polar_angle = np.arctan2(transverse_radius, -stream_position)
        polar_angle = np.where(radial_distance > 0.0, polar_angle, 0.0)
        return radial_distance, polar_angle, azimuth


def streamwise_basis_from_aoa(aoa_degrees: float):
    """Build the extractor's AoA-aligned orthonormal basis."""
    alpha = math.radians(float(aoa_degrees))
    streamwise = np.asarray([math.cos(alpha), 0.0, math.sin(alpha)], dtype=float)
    streamwise /= np.linalg.norm(streamwise)
    spanwise = np.asarray([0.0, 1.0, 0.0], dtype=float)
    normal = np.cross(streamwise, spanwise)
    normal /= np.linalg.norm(normal)
    return streamwise, normal, spanwise


def frame_coordinates(points, streamwise, normal, spanwise, origin=None):
    """Compatibility helper returning local streamwise/normal/spanwise coordinates."""
    frame = ShockFrame(
        np.zeros(3) if origin is None else np.asarray(origin, dtype=float),
        np.asarray(streamwise, dtype=float),
        np.asarray(normal, dtype=float),
        np.asarray(spanwise, dtype=float),
    )
    return frame.local_coordinates(points)


def perpendicular_radius(points, streamwise, origin=None):
    """Distance from each point to the supplied streamwise axis."""
    points = np.asarray(points, dtype=float)
    if origin is not None:
        points = points - np.asarray(origin, dtype=float)
    streamwise = np.asarray(streamwise, dtype=float)
    axial = np.outer(points @ streamwise, streamwise)
    return np.linalg.norm(points - axial, axis=1)
