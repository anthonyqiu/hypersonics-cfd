import argparse
import csv
from pathlib import Path

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


def surface_theta_limit(surface, frame, target_phi):
    _, theta, phi = frame.spherical_coordinates(surface.points)
    shell = np.asarray(surface["ShellLayer"], dtype=int)
    ray_index = np.asarray(surface["RayIndex"], dtype=int)
    ray_phi = []
    ray_theta_max = []
    for ray in np.unique(ray_index[shell > 0]):
        mask = (ray_index == ray) & (shell > 0)
        ray_phi.append(np.median(phi[mask]))
        ray_theta_max.append(np.max(theta[mask]))
    return periodic_interp(ray_phi, ray_theta_max, target_phi)


def shared_theta_limit(
    surfaces,
    phi_count=360,
    axis_origin=None,
    streamwise=None,
):
    phi = np.linspace(0.0, 2.0 * np.pi, phi_count, endpoint=False)
    frame = surface_frame(surfaces[0], axis_origin, streamwise)
    return np.min(
        [surface_theta_limit(surface, frame, phi) for surface in surfaces],
        axis=0,
    )


def weighted_percentile(values, weights, fraction):
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    index = np.searchsorted(np.cumsum(weights), fraction * weights.sum())
    return values[min(index, len(values) - 1)]


def stagnation_standoff(surface, axis_origin=None, streamwise=None):
    frame = surface_frame(surface, axis_origin, streamwise)
    radius, _, _ = frame.spherical_coordinates(surface.points)
    shell = np.asarray(surface["ShellLayer"], dtype=int)
    return float(radius[shell == 0][0])


def crop_surface(surface, frame, phi, theta_limit):
    surface = surface.extract_surface().triangulate().clean()
    _, theta, point_phi = frame.spherical_coordinates(surface.points)
    surface["ThetaMargin"] = periodic_interp(phi, theta_limit, point_phi) - theta
    return (
        surface.clip_scalar(scalars="ThetaMargin", value=0.0, invert=False)
        .extract_surface()
        .triangulate()
        .clean()
    )


def triangle_samples(surface):
    sized = surface.compute_cell_sizes(length=False, area=True, volume=False)
    areas = np.asarray(sized.cell_data["Area"], dtype=float)
    centers = np.asarray(sized.cell_centers().points, dtype=float)
    valid = areas > 0.0
    return centers[valid], areas[valid]


def directed_distances(source, target):
    centers, areas = triangle_samples(source)
    _, closest = target.find_closest_cell(centers, return_closest_point=True)
    distances = np.linalg.norm(centers - closest, axis=1)
    return distances, areas


def write_csv(path, rows):
    with Path(path).open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def common_surface_metrics(
    surface_a,
    surface_b,
    diameter=5.0,
    phi_count=360,
    axis_origin=None,
    streamwise=None,
    theta_limit=None,
):
    frame = surface_frame(surface_a, axis_origin, streamwise)
    phi = np.linspace(0.0, 2.0 * np.pi, phi_count, endpoint=False)
    limit = np.minimum(
        surface_theta_limit(surface_a, frame, phi),
        surface_theta_limit(surface_b, frame, phi),
    )
    if theta_limit is not None:
        limit = np.minimum(limit, theta_limit)
    cropped_a = crop_surface(surface_a, frame, phi, limit)
    cropped_b = crop_surface(surface_b, frame, phi, limit)
    distances_a, areas_a = directed_distances(cropped_a, cropped_b)
    distances_b, areas_b = directed_distances(cropped_b, cropped_a)
    difference = np.r_[distances_a, distances_b]
    weights = np.r_[areas_a, areas_b]
    mean = np.average(difference, weights=weights)
    rms = np.sqrt(np.average(difference**2, weights=weights))
    standoff_a = stagnation_standoff(surface_a, axis_origin, streamwise)
    standoff_b = stagnation_standoff(surface_b, axis_origin, streamwise)
    return {
        "common_mean_over_D": mean / diameter,
        "common_rms_over_D": rms / diameter,
        "common_p95_over_D": weighted_percentile(
            difference, weights, 0.95
        )
        / diameter,
        "common_max_over_D": np.max(difference) / diameter,
        "standoff_a_over_D": standoff_a / diameter,
        "standoff_b_over_D": standoff_b / diameter,
        "standoff_difference_over_D": abs(standoff_a - standoff_b) / diameter,
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
        limit = shared_theta_limit(
            list(surfaces.values()),
            axis_origin=body_origin,
            streamwise=streamwise,
        )
        comparisons = [*zip(levels[:-1], levels[1:]), (levels[0], levels[-1])]
        for level_a, level_b in comparisons:
            if level_a not in surfaces or level_b not in surfaces:
                continue
            metrics = common_surface_metrics(
                surfaces[level_a],
                surfaces[level_b],
                diameter,
                axis_origin=body_origin,
                streamwise=streamwise,
                theta_limit=limit,
            )
            rows.append(
                {
                    "mach": mach.removeprefix("m"),
                    "case_a": f"{mach}_{level_a}",
                    "mesh_level_a": level_a,
                    "case_b": f"{mach}_{level_b}",
                    "mesh_level_b": level_b,
                    "comparison": f"{level_a}-{level_b}",
                    "is_adjacent": str(
                        levels.index(level_b) - levels.index(level_a) == 1
                    ).lower(),
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
    write_csv(output_path, rows)
    print(f"wrote {output_path}")
    return rows


def compare_surface_pair(
    surface_a_path,
    surface_b_path,
    output_path,
    diameter=5.0,
    theta_limit_degrees=None,
):
    theta_limit = None
    if theta_limit_degrees is not None:
        theta_limit = np.full(360, np.radians(theta_limit_degrees))
    metrics = common_surface_metrics(
        pv.read(surface_a_path),
        pv.read(surface_b_path),
        diameter=diameter,
        theta_limit=theta_limit,
    )
    row = {
        "surface_a": str(surface_a_path),
        "surface_b": str(surface_b_path),
        **metrics,
    }
    write_csv(output_path, [row])
    print(f"RMS/D = {metrics['common_rms_over_D']:.6g}")
    print(f"stand-off/D = {metrics['standoff_difference_over_D']:.6g}")
    print(f"wrote {output_path}")
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("surface_a", nargs="?")
    parser.add_argument("surface_b", nargs="?")
    parser.add_argument("--output", default="shock_surface_deviation.csv")
    parser.add_argument("--diameter", type=float, default=5.0)
    parser.add_argument("--theta-limit", type=float)
    args = parser.parse_args()
    if args.surface_a:
        compare_surface_pair(
            args.surface_a,
            args.surface_b,
            args.output,
            args.diameter,
            args.theta_limit,
        )
        return

    paths = get_study_paths("orion")
    with (paths.study_root / "geometry" / "orion_profile_xy.csv").open() as file:
        profile = list(csv.DictReader(file))
    body_origin = [min(float(row["x"]) for row in profile), 0.0, 0.0]
    output = (
        paths.study_root / "data" / "shock_surface_deviation_refinement.csv"
    )
    compare_refinement_surfaces(paths.cases_dir, output, body_origin)
