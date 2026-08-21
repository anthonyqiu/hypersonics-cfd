import sys
import unittest
from pathlib import Path

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hypersonics_cfd.shock.sensor import (  # noqa: E402
    PEAK_MODE_FIRST_UPSTREAM,
    PEAK_MODE_NEAREST_CENTER,
    autoscaled_savgol_window_points,
    find_shock_node_on_line_result,
)


class PeakDetectionTests(unittest.TestCase):
    @staticmethod
    def line_sample():
        coordinate = np.linspace(-1.0, 1.0, 201)
        sensor = (
            np.exp(-((coordinate + 0.45) / 0.06) ** 2)
            + 0.8 * np.exp(-((coordinate - 0.18) / 0.06) ** 2)
        )
        return {
            "line_coordinates": coordinate,
            "valid_mask": np.ones_like(coordinate, dtype=bool),
            "shock_sensor_raw": sensor,
            "points": np.column_stack(
                (coordinate, np.zeros_like(coordinate), np.zeros_like(coordinate))
            ),
            "density": 1.0 + sensor,
        }

    def test_first_upstream_selects_upstream_peak(self):
        candidate, reason, _ = find_shock_node_on_line_result(
            self.line_sample(),
            min_height=0.01,
            selection_mode=PEAK_MODE_FIRST_UPSTREAM,
            fallback_global=False,
        )

        self.assertEqual(reason, "")
        self.assertAlmostEqual(candidate["line_coordinate"], -0.45, delta=0.02)

    def test_nearest_center_selects_nearest_peak(self):
        candidate, reason, _ = find_shock_node_on_line_result(
            self.line_sample(),
            min_height=0.01,
            selection_mode=PEAK_MODE_NEAREST_CENTER,
            fallback_global=False,
        )

        self.assertEqual(reason, "")
        self.assertAlmostEqual(candidate["line_coordinate"], 0.18, delta=0.02)

    def test_smoothing_window_preserves_physical_length(self):
        self.assertEqual(autoscaled_savgol_window_points(0.01, 101), 25)
        self.assertEqual(autoscaled_savgol_window_points(0.005, 101), 31)


if __name__ == "__main__":
    unittest.main()
