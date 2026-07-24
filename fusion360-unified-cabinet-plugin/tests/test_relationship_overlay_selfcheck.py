import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
if str(REL_DIR) not in sys.path:
    sys.path.insert(0, str(REL_DIR))

from relationship_visual_overlay_selfcheck import (  # noqa: E402
    EXPECTED_OVERLAY_FUSION_BUILD,
    run_overlay_selfcheck,
)


class RelationshipOverlaySelfcheckTests(unittest.TestCase):
    def test_overlay_selfcheck_passes(self):
        report = run_overlay_selfcheck(force_reload=True)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["expectedFusionBuild"], EXPECTED_OVERLAY_FUSION_BUILD)
        failed = [item for item in report.get("checks") or [] if not item.get("ok")]
        self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main()
