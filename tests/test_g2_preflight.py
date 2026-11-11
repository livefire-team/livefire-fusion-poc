"""Unit tests for the self-contained G2 static preflight (no third-party dependencies)."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("g2_preflight", ROOT / "scripts" / "g2-preflight.py")
MODULE = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PreflightTest(unittest.TestCase):
    def test_actual_bundle_has_mandatory_files(self):
        found = {x.code: x for x in MODULE.checks(ROOT, None, "none", {})}
        self.assertEqual(found["REQUIRED_FILES"].status, "PASS")
        self.assertEqual(found["CONTRACT_VERSION"].status, "PASS")
        self.assertEqual(found["PLANNER_TOOLS"].status, "PASS")
        self.assertEqual(found["ENGINEER_TOOLS"].status, "PASS")

    def test_missing_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = {x.code: x for x in MODULE.checks(Path(tmp), None, "none", {})}
        self.assertEqual(found["REQUIRED_FILES"].status, "FAIL")

    def test_live_config_names_not_values(self):
        found = {x.code: x for x in MODULE.checks(ROOT, None, "agent", {"MCP_URL": "https://example.test"})}
        self.assertEqual(found["LIVE_CONFIG"].status, "FAIL")
        self.assertIn("PLANNER_AGENT", found["LIVE_CONFIG"].note)

    def test_wrong_runtime_repository_fails(self):
        fake = {key: "not-a-secret" for key in MODULE.AGENT_ENV + MODULE.WORKFLOW_ENV}
        fake["GITHUB_REPO"] = "livefire-team/ws4-new"
        found = {x.code: x for x in MODULE.checks(ROOT, None, "workflow", fake)}
        self.assertEqual(found["ENGINEER_REPO"].status, "FAIL")

    def test_short_and_full_sha_conflict_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".github" / "workflows"
            path.mkdir(parents=True)
            (path / "order-service.yml").write_text("SHORT_SHA=${GITHUB_SHA::7}", encoding="utf-8")
            found = {x.code: x for x in MODULE.checks(ROOT, Path(tmp), "none", {})}
        self.assertEqual(found["WS1_IMAGE_TAG"].status, "WARN")
        self.assertIn("mismatch", found["WS1_IMAGE_TAG"].note)


if __name__ == "__main__":
    unittest.main()
