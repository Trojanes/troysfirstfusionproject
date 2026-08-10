import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NESTING_DIR = ROOT / "nesting"
if str(NESTING_DIR) not in sys.path:
    sys.path.insert(0, str(NESTING_DIR))

from manufacturing_snapshot_export import (  # noqa: E402
    FORMAT,
    build_snapshot,
    write_cnjob,
)


def _record(features=None, outline_source="flatBody"):
    return {
        "entityKind": "body",
        "panelId": "P1",
        "bodyName": "Left Side",
        "metadataSource": "stored",
        "measuredThicknessMm": 18,
        "faceSummary": {
            "faces": [
                {
                    "faceClass": "SURFACE",
                    "faceId": "FACE-MILL",
                    "entityToken": "TOKEN-A",
                    "millingSurface": "MILLING",
                    "machiningPermission": "PRIMARY",
                    "finish": {"finishId": "white", "finishName": "White"},
                },
                {
                    "faceClass": "SURFACE",
                    "faceId": "FACE-BACK",
                    "entityToken": "TOKEN-B",
                    "millingSurface": "NON_MILLING",
                    "machiningPermission": "NOT_ALLOWED",
                    "finish": {"finishId": "white", "finishName": "White"},
                },
            ]
        },
        "metadata": {
            "identity": {
                "panelId": "P1",
                "module": "kitchen",
                "runId": "RUN-1",
                "boardType": "left_side",
            },
            "defaultAttributes": {
                "role": "left_side",
                "materialClass": "carcass_board",
            },
            "classification": {
                "boardType": {"value": "carcass"},
                "color": {"value": "white"},
                "cuttingFace": {"value": "MILLING"},
            },
            "dimensions": {"lengthMm": 720, "widthMm": 560, "thicknessMm": 18},
            "nestingFlatOutline": {
                "outline": {
                    "source": outline_source,
                    "points": [[0, 0], [560, 0], [560, 720], [0, 720], [0, 0]],
                }
            },
            "features": features
            if features is not None
            else [
                {
                    "featureId": "H1",
                    "kind": "hole",
                    "cutType": "HALF",
                    "depthMm": 12,
                    "center2d": [37, 80],
                    "radiusMm": 2.5,
                    "openSurfaceToken": "TOKEN-A",
                },
                {
                    "featureId": "G1",
                    "kind": "groove",
                    "cutType": "HALF",
                    "depthMm": 8,
                    "pointsLocal": [[10, 15], [550, 15], [550, 21], [10, 21]],
                    "openSurfaceToken": "TOKEN-A",
                },
            ],
        },
    }


class ManufacturingSnapshotExportTests(unittest.TestCase):
    def test_builds_single_side_snapshot_from_analyzed_metadata(self):
        result = build_snapshot(
            [_record()],
            "JOB-1",
            source={"cadApp": "Fusion 360", "pluginId": "test"},
        )

        self.assertTrue(result["ok"], result["errors"])
        snapshot = result["snapshot"]
        self.assertEqual(snapshot["schema"], FORMAT)
        workpiece = snapshot["workpieces"][0]
        self.assertEqual(workpiece["manufacturing"]["machiningFace"], "A")
        self.assertEqual(len(workpiece["geometry"]["outerProfile"]["points"]), 4)
        self.assertEqual(workpiece["features"][0]["kind"], "bore")
        self.assertEqual(workpiece["features"][0]["sourceFace"], "A")
        self.assertEqual(workpiece["features"][1]["kind"], "groove")
        self.assertEqual(workpiece["features"][1]["geometry"]["widthMm"], 6)

    def test_rejects_bbox_fallback(self):
        result = build_snapshot([_record(outline_source="bboxFallback")], "JOB-1")

        self.assertFalse(result["ok"])
        self.assertTrue(
            any(item["code"] == "non_production_outline" for item in result["errors"])
        )

    def test_rejects_rectangle_fallback(self):
        result = build_snapshot([_record(outline_source="rectangle")], "JOB-1")

        self.assertFalse(result["ok"])
        self.assertTrue(
            any(item["code"] == "non_production_outline" for item in result["errors"])
        )

    def test_rejects_degenerate_outline(self):
        record = _record()
        record["metadata"]["nestingFlatOutline"]["outline"]["points"] = [
            [0, 0],
            [10, 0],
            [20, 0],
        ]
        result = build_snapshot([record], "JOB-1")
        self.assertFalse(result["ok"])
        self.assertTrue(any(item["code"] == "outline_invalid" for item in result["errors"]))

    def test_rejects_blind_features_on_both_faces(self):
        features = [
            {
                "featureId": "A1",
                "kind": "hole",
                "cutType": "HALF",
                "depthMm": 5,
                "center2d": [10, 10],
                "radiusMm": 2.5,
                "openSurfaceToken": "TOKEN-A",
            },
            {
                "featureId": "B1",
                "kind": "hole",
                "cutType": "HALF",
                "depthMm": 5,
                "center2d": [20, 10],
                "radiusMm": 2.5,
                "openSurfaceToken": "TOKEN-B",
            },
        ]

        result = build_snapshot([_record(features=features)], "JOB-1")

        self.assertFalse(result["ok"])
        self.assertTrue(
            any(item["code"] == "double_side_unsupported" for item in result["errors"])
        )

    def test_normalizes_blind_B_features_to_snapshot_A(self):
        features = [
            {
                "featureId": "H1",
                "kind": "hole",
                "cutType": "HALF",
                "depthMm": 12,
                "center2d": [37, 80],
                "radiusMm": 2.5,
                "openSurfaceToken": "TOKEN-B",
            }
        ]
        result = build_snapshot([_record(features=features)], "JOB-1")

        self.assertTrue(result["ok"], result["errors"])
        workpiece = result["snapshot"]["workpieces"][0]
        self.assertEqual(workpiece["manufacturing"]["machiningFace"], "A")
        self.assertEqual(workpiece["features"][0]["sourceFace"], "A")
        # TOKEN-B was non-milling; after remap it becomes Snapshot A and is upgraded.
        face_a = next(f for f in workpiece["faces"] if f["faceId"] == "A")
        self.assertEqual(face_a["machiningPermission"], "PRIMARY")

    def test_rejects_missing_and_over_thickness_blind_depth(self):
        missing = [
            {
                "featureId": "P1",
                "kind": "pocket",
                "cutType": "HALF",
                "pointsLocal": [[0, 0], [10, 0], [10, 10]],
                "openSurfaceIs": "A",
            }
        ]
        result = build_snapshot([_record(features=missing)], "JOB-1")
        self.assertFalse(result["ok"])
        self.assertTrue(any(item["code"] == "feature_depth" for item in result["errors"]))

        missing[0]["depthMm"] = 20
        result = build_snapshot([_record(features=missing)], "JOB-1")
        self.assertFalse(result["ok"])
        self.assertTrue(
            any(
                item["code"] == "feature_depth_over_thickness"
                for item in result["errors"]
            )
        )

    def test_tessellated_rectangular_groove_simplifies_to_centerline(self):
        groove = {
            "featureId": "G1",
            "kind": "groove",
            "cutType": "HALF",
            "depthMm": 8,
            "openSurfaceIs": "A",
            "pointsLocal": [
                [10, 15],
                [200, 15],
                [550, 15],
                [550, 18],
                [550, 21],
                [200, 21],
                [10, 21],
                [10, 18],
            ],
        }
        result = build_snapshot([_record(features=[groove])], "JOB-1")
        self.assertTrue(result["ok"], result["errors"])
        geometry = result["snapshot"]["workpieces"][0]["features"][0]["geometry"]
        self.assertEqual(len(geometry["centerline"]), 2)
        self.assertEqual(geometry["widthMm"], 6)

    def test_noisy_and_capsule_grooves_export(self):
        noisy = {
            "featureId": "G-noisy",
            "kind": "groove",
            "cutType": "HALF",
            "depthMm": 6,
            "openSurfaceIs": "A",
            "pointsLocal": [
                [0, 0],
                [40, 0.08],
                [80, 0],
                [80.05, 3],
                [80, 6],
                [40, 5.95],
                [0, 6],
                [-0.04, 3],
            ],
        }
        capsule = {
            "featureId": "G-capsule",
            "kind": "groove",
            "cutType": "HALF",
            "depthMm": 5,
            "openSurfaceIs": "A",
            # Elongated stadium-like outline (many corners after simplify).
            "pointsLocal": [
                [0, 2],
                [1, 0.5],
                [3, 0],
                [97, 0],
                [99, 0.5],
                [100, 2],
                [100, 4],
                [99, 5.5],
                [97, 6],
                [3, 6],
                [1, 5.5],
                [0, 4],
            ],
        }
        for groove in (noisy, capsule):
            result = build_snapshot([_record(features=[groove])], "JOB-1")
            self.assertTrue(result["ok"], (groove["featureId"], result["errors"]))
            feature = result["snapshot"]["workpieces"][0]["features"][0]
            self.assertIn(feature["kind"], ("groove", "pocket"))
            if feature["kind"] == "groove":
                self.assertGreaterEqual(len(feature["geometry"]["centerline"]), 2)
                self.assertGreater(feature["geometry"]["widthMm"], 0)

    def test_shallow_b_open_remaps_to_a_on_export(self):
        result = build_snapshot(
            [
                _record(
                    features=[
                        {
                            "featureId": "P1",
                            "kind": "pocket",
                            "cutType": "HALF",
                            "depthMm": 2,
                            "openSurfaceIs": "B",
                            "pointsLocal": [[0, 0], [20, 0], [20, 20], [0, 20]],
                        }
                    ]
                )
            ],
            "JOB-1",
        )
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(
            result["snapshot"]["workpieces"][0]["features"][0]["sourceFace"], "A"
        )

    def test_rejects_unresolved_either_face(self):
        record = _record(
            features=[
                {
                    "featureId": "P1",
                    "kind": "pocket",
                    "cutType": "HALF",
                    "depthMm": 5,
                    "pointsLocal": [[0, 0], [10, 0], [10, 10]],
                }
            ]
        )
        record["faceSummary"] = {"faces": []}
        result = build_snapshot([record], "JOB-1")
        self.assertFalse(result["ok"])
        self.assertTrue(
            any(item["code"] == "feature_face_unknown" for item in result["errors"])
        )

    def test_analyzed_open_surface_wins_over_stale_token(self):
        feature = {
            "featureId": "H1",
            "kind": "hole",
            "cutType": "HALF",
            "depthMm": 12,
            "center2d": [37, 80],
            "radiusMm": 2.5,
            "openSurfaceIs": "A",
            "openSurfaceToken": "TOKEN-B",
        }
        result = build_snapshot([_record(features=[feature])], "JOB-1")
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(
            result["snapshot"]["workpieces"][0]["features"][0]["sourceFace"],
            "A",
        )

    def test_writes_cnjob_manifest_and_snapshot(self):
        result = build_snapshot([_record()], "JOB-1")
        self.assertTrue(result["ok"], result["errors"])
        with tempfile.TemporaryDirectory() as directory:
            path = write_cnjob(Path(directory) / "job.cnjob", result["snapshot"])
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(
                    set(archive.namelist()), {"manifest.json", "snapshot.json"}
                )
                manifest = json.loads(archive.read("manifest.json"))
                snapshot = json.loads(archive.read("snapshot.json"))
            self.assertEqual(manifest["format"], FORMAT)
            self.assertEqual(snapshot["jobId"], "JOB-1")

    def test_selected_body_records_become_one_job_list(self):
        first = _record()
        first["entityKind"] = "selected_body"
        first["panelId"] = "P1"
        first["metadata"]["identity"]["panelId"] = "P1"
        second = _record()
        second["entityKind"] = "selected_body"
        second["panelId"] = "P2"
        second["bodyName"] = "Right Side"
        second["metadata"]["identity"]["panelId"] = "P2"

        result = build_snapshot(
            [first, second],
            "SAMPLE-JOB",
            source={"exportScope": "selection"},
        )

        self.assertTrue(result["ok"], result["errors"])
        snapshot = result["snapshot"]
        self.assertEqual(snapshot["jobId"], "SAMPLE-JOB")
        self.assertEqual(len(snapshot["workpieces"]), 2)
        self.assertEqual(
            [item["workpieceId"] for item in snapshot["workpieces"]],
            ["P1", "P2"],
        )

    def test_uniquifies_duplicate_panel_ids(self):
        first = _record()
        first["panelId"] = "manual.Body1"
        first["occurrencePath"] = [0, 1]
        first["assemblyName"] = "Bunk"
        first["componentName"] = "SideA"
        first["metadata"]["identity"]["panelId"] = "manual.Body1"
        second = _record()
        second["panelId"] = "manual.Body1"
        second["occurrencePath"] = [0, 2]
        second["assemblyName"] = "Bunk"
        second["componentName"] = "SideB"
        second["bodyName"] = "Body1"
        second["metadata"]["identity"]["panelId"] = "manual.Body1"

        result = build_snapshot([first, second], "JOB-DUP")

        self.assertTrue(result["ok"], result["errors"])
        ids = [item["panelId"] for item in result["snapshot"]["workpieces"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "manual.Body1")
        self.assertEqual(ids[1], "manual.Body1@0-2")
        self.assertEqual(
            result["snapshot"]["workpieces"][1]["name"],
            "Bunk - SideB",
        )
        self.assertTrue(
            any(item["code"] == "panel_id_uniquified" for item in result["warnings"])
        )


if __name__ == "__main__":
    unittest.main()
