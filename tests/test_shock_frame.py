import sys
import unittest
from pathlib import Path

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hypersonics_cfd.shock.frame import ShockFrame  # noqa: E402


class ShockFrameTests(unittest.TestCase):
    def test_polar_angle_is_measured_from_upstream(self):
        frame = ShockFrame.from_aoa(0.0)
        points = np.array(
            [
                [-2.0, 0.0, 0.0],
                [0.0, 0.0, 3.0],
                [2.0, 0.0, 0.0],
            ]
        )

        radius, theta, phi = frame.spherical_coordinates(points)

        np.testing.assert_allclose(radius, [2.0, 3.0, 2.0])
        np.testing.assert_allclose(theta, [0.0, np.pi / 2.0, np.pi])
        np.testing.assert_allclose(phi, [0.0, 0.0, 0.0])

    def test_aoa_frame_is_orthonormal(self):
        frame = ShockFrame.from_aoa(40.0)
        basis = np.vstack((frame.streamwise, frame.normal, frame.spanwise))

        np.testing.assert_allclose(basis @ basis.T, np.eye(3), atol=1.0e-14)
        np.testing.assert_allclose(
            np.cross(frame.streamwise, frame.spanwise),
            frame.normal,
            atol=1.0e-14,
        )


if __name__ == "__main__":
    unittest.main()
