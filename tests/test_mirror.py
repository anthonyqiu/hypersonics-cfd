import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pyvista as pv


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hypersonics_cfd.postprocess.mirror import mirror_flow


class MirrorTests(unittest.TestCase):
    def test_coordinates_and_vectors_are_reflected(self):
        mesh = pv.PolyData([[0.0, 1.0, 0.0], [1.0, 2.0, 3.0]])
        mesh["Density"] = [1.0, 2.0]
        mesh["Momentum"] = [[4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "half.vtp"
            destination = Path(directory) / "full.vtp"
            mesh.save(source)
            mirror_flow(source, destination)
            full = pv.read(destination)

        np.testing.assert_allclose(
            np.sort(full.points[:, 1]),
            [-2.0, -1.0, 1.0, 2.0],
        )
        reflected = full.points[:, 1] < 0.0
        np.testing.assert_allclose(
            np.sort(full["Momentum"][reflected, 1]),
            [-8.0, -5.0],
        )
        np.testing.assert_allclose(
            np.sort(full["Density"]),
            [1.0, 1.0, 2.0, 2.0],
        )


if __name__ == "__main__":
    unittest.main()
