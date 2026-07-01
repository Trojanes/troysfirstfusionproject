import math
import os
import sys
import unittest


PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
METADATA_DIR = os.path.join(PLUGIN_DIR, "metadata")
if METADATA_DIR not in sys.path:
    sys.path.insert(0, METADATA_DIR)

from face_geometry_signature import (  # noqa: E402
    build_body_frame_from_faces,
    express_point_in_frame,
    express_vector_in_frame,
)


def _box_face_infos(center, length, width, thickness):
    cx, cy, cz = center
    hl, hw, ht = length / 2.0, width / 2.0, thickness / 2.0
    return [
        {"centroid": [cx, cy, cz + ht], "normal": [0, 0, 1], "area": length * width},
        {"centroid": [cx, cy, cz - ht], "normal": [0, 0, -1], "area": length * width},
        {"centroid": [cx + hl, cy, cz], "normal": [1, 0, 0], "area": width * thickness},
        {"centroid": [cx - hl, cy, cz], "normal": [-1, 0, 0], "area": width * thickness},
        {"centroid": [cx, cy + hw, cz], "normal": [0, 1, 0], "area": length * thickness},
        {"centroid": [cx, cy - hw, cz], "normal": [0, -1, 0], "area": length * thickness},
    ]


def _matmul(matrix, vector):
    return [sum(matrix[r][c] * vector[c] for c in range(3)) for r in range(3)]


def _rotation(ax, ay, az):
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)
    rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]

    def mm(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

    return mm(rz, mm(ry, rx))


def _transform_infos(infos, rotation, translation):
    out = []
    for info in infos:
        c = _matmul(rotation, info["centroid"])
        c = [c[0] + translation[0], c[1] + translation[1], c[2] + translation[2]]
        n = _matmul(rotation, info["normal"])
        out.append({"centroid": c, "normal": n, "area": info["area"]})
    return out


class BodyFrameTests(unittest.TestCase):
    def test_returns_none_for_insufficient_faces(self):
        self.assertIsNone(build_body_frame_from_faces([]))
        self.assertIsNone(build_body_frame_from_faces([{"centroid": [0, 0, 0], "normal": [0, 0, 1], "area": 1}]))

    def test_frame_axes_are_orthonormal(self):
        frame = build_body_frame_from_faces(_box_face_infos([5, 7, 9], 200, 80, 18))
        self.assertIsNotNone(frame)
        for axis in ("x", "y", "z"):
            length = sum(v * v for v in frame[axis]) ** 0.5
            self.assertAlmostEqual(length, 1.0, places=6)
        self.assertAlmostEqual(sum(a * b for a, b in zip(frame["x"], frame["y"])), 0.0, places=6)
        self.assertAlmostEqual(sum(a * b for a, b in zip(frame["x"], frame["z"])), 0.0, places=6)

    def test_signature_invariant_under_rigid_move(self):
        infos = _box_face_infos([0, 0, 0], 200, 80, 18)
        frame0 = build_body_frame_from_faces(infos)
        baseline = [
            (
                express_point_in_frame(fi["centroid"], frame0),
                express_vector_in_frame(fi["normal"], frame0),
            )
            for fi in infos
        ]

        rotation = _rotation(0.6, -0.4, 1.1)
        moved = _transform_infos(infos, rotation, [123.0, -45.0, 67.0])
        frame1 = build_body_frame_from_faces(moved)

        for index, fi in enumerate(moved):
            point = express_point_in_frame(fi["centroid"], frame1)
            normal = express_vector_in_frame(fi["normal"], frame1)
            for axis in range(3):
                self.assertAlmostEqual(point[axis], baseline[index][0][axis], places=4)
                self.assertAlmostEqual(normal[axis], baseline[index][1][axis], places=4)


if __name__ == "__main__":
    unittest.main()
