"""Unit tests for the ArtCAM-oriented nesting DXF writer."""

from __future__ import annotations

import os
import tempfile
import unittest

from nesting.dxf_writer import build_dxf_ascii, write_dxf_file


class NestingDxfWriterTests(unittest.TestCase):
    def test_builds_closed_polyline_entities(self):
        text = build_dxf_ascii(
            [
                [[0, 0], [100, 0], [100, 50], [0, 50]],
                [[10, 10], [20, 10], [20, 20], [10, 20]],
            ]
        )
        self.assertIn("$INSUNITS", text)
        self.assertIn("POLYLINE", text)
        self.assertIn("VERTEX", text)
        self.assertIn("SEQEND", text)
        self.assertEqual(text.count("0\nPOLYLINE"), 2)
        self.assertTrue(text.strip().endswith("EOF"))

    def test_skips_degenerate_rings(self):
        text = build_dxf_ascii([[[0, 0], [1, 0]], []])
        self.assertNotIn("POLYLINE", text)

    def test_write_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "nest.dxf")
            write_dxf_file(path, [[[0, 0], [10, 0], [10, 10], [0, 10]]])
            with open(path, "r", encoding="ascii") as handle:
                content = handle.read()
            self.assertIn("EOF", content)


if __name__ == "__main__":
    unittest.main()
