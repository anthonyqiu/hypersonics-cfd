from __future__ import annotations

import csv
from dataclasses import dataclass

import numpy as np
import pyvista as pv

from hypersonics_cfd.study import get_study_paths

from .frame import ShockFrame


def periodic_interp(angle, values, target):
    order = np.argsort(angle)
    angle = np.mod(np.asarray(angle)[order], 2.0 * np.pi)
    values = np.asarray(values)[order]
    angle, unique = np.unique(angle, return_index=True)
    values = values[unique]
    if len(angle) == 1:
        return np.full_like(target, values[0])
    return np.interp(
        target,
        np.r_[angle[-1] - 2.0 * np.pi, angle, angle[0] + 2.0 * np.pi],
        np.r_[values[-1], values, values[0]],
    )


def surface_frame(surface, origin=None, streamwise=None):
    if origin is None:
        origin = surface.field_data.get("BodyAnchor", [[0.0, 0.0, 0.0]])[0]
    if streamwise is None:
        streamwise = surface.field_data.get(
            "StreamwiseBasis", [[1.0, 0.0, 0.0]]
        )[0]
    streamwise = np.asarray(streamwise, dtype=float)
    streamwise /= np.linalg.norm(streamwise)
    if "NormalBasis" in surface.field_data:
        normal = np.asarray(surface.field_data["NormalBasis"][0], dtype=float)
        spanwise = np.asarray(surface.field_data["SpanwiseBasis"][0], dtype=float)
    else:
        spanwise = np.array([0.0, 1.0, 0.0])
        normal = np.cross(streamwise, spanwise)
        normal /= np.linalg.norm(normal)
    return ShockFrame(np.asarray(origin), streamwise, normal, spanwise)


@dataclass
class PolarSurface:
    frame: ShockFrame
    phi: np.ndarray
    theta: list[np.ndarray]
    radius: list[np.ndarray]
    standoff: float

    @classmethod
    def from_mesh(cls, surface, frame):
        radius, theta, phi = frame.spherical_coordinates(surface.points)
        shell = np.asarray(surface["ShellLayer"], dtype=int)
        ray_index = np.asarray(surface["RayIndex"], dtype=int)
        standoff = float(radius[shell == 0][0])
        ray_phi = []
        ray_theta = []
        ray_radius = []
        for ray in np.unique(ray_index[shell > 0]):
            mask = (ray_index == ray) & (shell > 0)
            values_theta = np.r_[0.0, theta[mask]]
            values_radius = np.r_[standoff, radius[mask]]
            order = np.argsort(values_theta)
            values_theta, unique = np.unique(
                values_theta[order], return_index=True
            )
            ray_phi.append(np.median(phi[mask]))
            ray_theta.append(values_theta)
            ray_radius.append(values_radius[order][unique])
        return cls(
            frame,
            np.asarray(ray_phi),
            ray_theta,
            ray_radius,
            standoff,
        )

    def theta_limit(self, target_phi):
        return periodic_interp(
            self.phi,
            [theta[-1] for theta in self.theta],
            target_phi,
        )

    def sample(self, target_theta, target_phi):
        ray_values = np.full((len(self.phi), len(target_theta)), np.nan)
        for index, (theta, radius) in enumerate(zip(self.theta, self.radius)):
            valid = target_theta <= theta[-1] + 1.0e-12
            ray_values[index, valid] = np.interp(
                target_theta[valid], theta, radius
            )
        result = np.full((len(target_theta), len(target_phi)), np.nan)
        for index in range(len(target_theta)):
            valid = np.isfinite(ray_values[:, index])
            if np.any(valid):
                result[index] = periodic_interp(
                    self.phi[valid],
                    ray_values[valid, index],
                    target_phi,
                )
        return result


def polar_surfaces(surfaces, axis_origin=None, streamwise=None):
    frame = surface_frame(surfaces[0], axis_origin, streamwise)
    return [PolarSurface.from_mesh(surface, frame) for surface in surfaces]


def shared_polar_limit(
    surfaces,
    phi_count=360,
    axis_origin=None,
    streamwise=None,
):
    phi = np.linspace(0.0, 2.0 * np.pi, phi_count, endpoint=False)
    polar = polar_surfaces(surfaces, axis_origin, streamwise)
    return np.min([surface.theta_limit(phi) for surface in polar], axis=0)


def weighted_percentile(values, weights, fraction):
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    index = np.searchsorted(np.cumsum(weights), fraction * weights.sum())
    return values[min(index, len(values) - 1)]


def stagnation_standoff(surface, axis_origin=None, streamwise=None):
    return polar_surfaces([surface], axis_origin, streamwise)[0].standoff


def common_polar_metrics(
    surface_a,
    surface_b,
    diameter=5.0,
    theta_count=240,
    phi_count=360,
    axis_origin=None,
    streamwise=None,
    polar_limit=None,
):
    a, b = polar_surfaces(
        [surface_a, surface_b], axis_origin, streamwise
    )
    phi = np.linspace(0.0, 2.0 * np.pi, phi_count, endpoint=False)
    limit = np.minimum(a.theta_limit(phi), b.theta_limit(phi))
    if polar_limit is not None:
        limit = np.minimum(limit, polar_limit)
    theta = np.linspace(0.0, np.max(limit), theta_count + 1)
    radius_a = a.sample(theta, phi)
    radius_b = b.sample(theta, phi)
    valid = (
        (theta[:, None] <= limit[None, :] + 1.0e-12)
        & np.isfinite(radius_a)
        & np.isfinite(radius_b)
    )
    difference = np.abs(radius_a - radius_b)[valid]
    weights = np.broadcast_to(np.sin(theta)[:, None], valid.shape)[valid]
    weights = np.maximum(weights, np.finfo(float).eps)
    mean = np.average(difference, weights=weights)
    rms = np.sqrt(np.average(difference**2, weights=weights))
    return {
        "common_mean_over_D": mean / diameter,
        "common_rms_over_D": rms / diameter,
        "common_p95_over_D": weighted_percentile(
            difference, weights, 0.95
        )
        / diameter,
        "common_max_over_D": np.max(difference) / diameter,
        "standoff_a_over_D": a.standoff / diameter,
        "standoff_b_over_D": b.standoff / diameter,
        "standoff_difference_over_D": abs(a.standoff - b.standoff)
        / diameter,
        "common_theta_min_degrees": np.degrees(np.min(limit)),
        "common_theta_mean_degrees": np.degrees(np.mean(limit)),
        "common_theta_max_degrees": np.degrees(np.max(limit)),
    }


def compare_refinement_surfaces(
    cases_dir,
    output_path,
    body_origin,
    streamwise=(1.0, 0.0, 0.0),
    diameter=5.0,
    machs=("m1p5", "m3", "m6", "m9"),
    levels=("coarse", "medium", "fine", "very_fine"),
):
    rows = []
    for mach in machs:
        surfaces = {
            level: pv.read(
                cases_dir / f"{mach}_{level}" / "shock_surface.vtp"
            )
            for level in levels
            if (
                cases_dir / f"{mach}_{level}" / "shock_surface.vtp"
            ).exists()
        }
        if len(surfaces) < 2:
            continue
        limit = shared_polar_limit(
            list(surfaces.values()),
            axis_origin=body_origin,
            streamwise=streamwise,
        )
        for level_a, level_b in zip(levels[:-1], levels[1:]):
            if level_a not in surfaces or level_b not in surfaces:
                continue
            metrics = common_polar_metrics(
                surfaces[level_a],
                surfaces[level_b],
                diameter,
                axis_origin=body_origin,
                streamwise=streamwise,
                polar_limit=limit,
            )
            rows.append(
                {
                    "mach": mach.removeprefix("m"),
                    "case_a": f"{mach}_{level_a}",
                    "mesh_level_a": level_a,
                    "case_b": f"{mach}_{level_b}",
                    "mesh_level_b": level_b,
                    "comparison": f"{level_a}-{level_b}",
                    "is_adjacent": "true",
                    "status": "ok",
                    **metrics,
                }
            )
            print(
                f"{mach}: {level_a} - {level_b}, "
                f"RMS/D = {metrics['common_rms_over_D']:.6g}, "
                f"stand-off/D = "
                f"{metrics['standoff_difference_over_D']:.6g}"
            )
    with output_path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {output_path}")
    return rows


def main():
    paths = get_study_paths("orion")
    with (paths.study_root / "geometry" / "orion_profile_xy.csv").open() as file:
        profile = list(csv.DictReader(file))
    body_origin = [min(float(row["x"]) for row in profile), 0.0, 0.0]
    output = (
        paths.study_root / "data" / "shock_surface_deviation_refinement.csv"
    )
    compare_refinement_surfaces(paths.cases_dir, output, body_origin)
