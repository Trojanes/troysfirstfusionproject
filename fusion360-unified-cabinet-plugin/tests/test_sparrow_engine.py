import os
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nesting import engine  # noqa: E402
from nesting.engines import sparrow  # noqa: E402


def _part(pid="p1"):
    return {
        "id": pid,
        "panelId": pid,
        "bodyName": pid,
        "boardTypeTag": "carcass",
        "colorTag": "white",
        "widthMm": 100,
        "depthMm": 50,
        "outline": {
            "source": "flatBody",
            "points": [[0, 0], [100, 0], [100, 50], [0, 50], [0, 0]],
        },
    }


def _normalized_response():
    return {
        "protocol": sparrow.PROTOCOL,
        "layout": {
            "placements": [{
                **_part(),
                "sheetIndex": 0,
                "groupIndex": 0,
                "itemIndex": 0,
                "localX": 10,
                "localY": 10,
                "targetX": 10,
                "targetY": 10,
                "rotationDeg": 0,
            }],
            "sheets": [{
                "sheetIndex": 0,
                "originX": 0,
                "originY": 0,
                "widthMm": 2440,
                "heightMm": 1220,
                "count": 1,
            }],
            "groups": [],
            "unplaced": [],
            "requiredWidthMm": 2440,
            "requiredDepthMm": 1220,
        },
    }


class SparrowEngineTests(unittest.TestCase):
    def test_request_uses_cabinetnc_and_sparrow_geometry(self):
        request = sparrow.build_request(
            [_part()],
            {
                "sheets": [{
                    "boardTypeTag": "carcass",
                    "widthMm": 2440,
                    "heightMm": 1220,
                }],
                "allowRotation": True,
                "rotationIncrementDeg": 90,
                "qualityTimeLimitSec": 12,
            },
            100,
            200,
        )
        self.assertEqual(request["protocol"], sparrow.PROTOCOL)
        self.assertEqual(request["timeLimitSec"], 12)
        self.assertEqual(request["origin"], {"xMm": 100.0, "yMm": 200.0})
        instance = request["jobs"][0]["sparrowInstance"]
        self.assertEqual(instance["items"][0]["demand"], 1)
        self.assertEqual(instance["items"][0]["shape"]["type"], "simple_polygon")

    def test_adapter_accepts_normalized_bridge_result(self):
        result = sparrow.layout(
            [_part()],
            {},
            0,
            0,
            runner=lambda request, executable=None: _normalized_response(),
        )
        self.assertEqual(result["engine"], sparrow.ENGINE_NAME)
        self.assertEqual(len(result["placements"]), 1)
        self.assertFalse(result["engineFallback"])

    def test_engine_falls_back_when_sparrow_unavailable(self):
        with patch.object(
            engine.sparrow,
            "layout",
            side_effect=sparrow.SparrowError("not installed"),
        ):
            result = engine.create_layout(
                [_part()],
                {},
                0,
                0,
                engine_name="sparrow",
            )
        self.assertEqual(result["requestedEngine"], sparrow.ENGINE_NAME)
        self.assertTrue(result["engineFallback"])
        self.assertIn("not installed", result["engineFallbackReason"])
        self.assertEqual(result["engine"], "sheet_pack_hybrid_v3")

    def test_malformed_bridge_result_is_rejected(self):
        with self.assertRaises(sparrow.SparrowError):
            sparrow.layout(
                [_part()],
                {},
                0,
                0,
                runner=lambda request, executable=None: {"layout": {}},
            )

    def test_bridge_timeout_is_reported(self):
        request = sparrow.build_request([_part()], {}, 0, 0, time_limit_sec=2)

        def timeout_runner(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="sparrow", timeout=2)

        with patch.object(sparrow.os.path, "isfile", return_value=True):
            with self.assertRaisesRegex(sparrow.SparrowError, "time limit"):
                sparrow.run_bridge(
                    request,
                    executable="sparrow-cabinetnc.exe",
                    run=timeout_runner,
                )


if __name__ == "__main__":
    unittest.main()
