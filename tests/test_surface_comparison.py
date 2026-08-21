import sys
import unittest
from pathlib import Path

import numpy as np
import pyvista as pv


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hypersonics_cfd.shock.comparison import (  # noqa: E402
    common_polar_metrics,
    shared_polar_limit,
)


def spherical_surface(radius, theta_max, theta_count=16, phi_count=24):
    points = [[-radius, 0.0, 0.0]]
    shell = [0]
    ray_index = [-1]
    for ray, phi in enumerate(np.linspace(0.0, 2.0 * np.pi, phi_count, endpoint=False)):
        transverse = np.array([0.0, np.sin(phi), np.cos(phi)])
        for layer, theta in enumerate(
            np.linspace(theta_max / theta_count, theta_max, theta_count),
            start=1,
        ):
            direction = (
                -np.cos(theta) * np.array([1.0, 0.0, 0.0])
                + np.sin(theta) * transverse
            )
            points.append(radius * direction)
            shell.append(layer)
            ray_index.append(ray)

    surface = pv.PolyData(np.asarray(points))
    surface["ShellLayer"] = np.asarray(shell)
    surface["RayIndex"] = np.asarray(ray_index)
    surface.field_data["BodyAnchor"] = np.zeros((1, 3))
    surface.field_data["StreamwiseBasis"] = np.array([[1.0, 0.0, 0.0]])
    surface.field_data["NormalBasis"] = np.array([[0.0, 0.0, 1.0]])
    surface.field_data["SpanwiseBasis"] = np.array([[0.0, 1.0, 0.0]])
    return surface


class SurfaceComparisonTests(unittest.TestCase):
    def test_shared_limit_is_minimum_of_surface_maxima(self):
        surfaces = [
            spherical_surface(2.0, 1.2),
            spherical_surface(2.1, 0.8),
            spherical_surface(2.2, 0.6),
        ]

        limit = shared_polar_limit(surfaces, phi_count=48)

        np.testing.assert_allclose(limit, 0.6, atol=1.0e-12)

    def test_constant_radial_offset_has_known_metric(self):
        surface_a = spherical_surface(2.0, 1.2)
        surface_b = spherical_surface(2.2, 0.8)

        metrics = common_polar_metrics(
            surface_a,
            surface_b,
            diameter=5.0,
            theta_count=80,
            phi_count=96,
        )

        self.assertAlmostEqual(metrics["common_mean_over_D"], 0.04, places=12)
        self.assertAlmostEqual(metrics["common_rms_over_D"], 0.04, places=12)
        self.assertAlmostEqual(metrics["common_p95_over_D"], 0.04, places=12)
        self.assertAlmostEqual(metrics["common_max_over_D"], 0.04, places=12)
        self.assertAlmostEqual(metrics["standoff_difference_over_D"], 0.04, places=12)
        self.assertAlmostEqual(
            metrics["common_theta_max_degrees"],
            np.degrees(0.8),
            places=10,
        )


if __name__ == "__main__":
    unittest.main()
