"""Strict portal wrapper must never silently fall back or leak runtimes."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_wayland_portals.sh"


class PortalRunnerFailClosedTests(unittest.TestCase):
    def launch(self, **updates):
        env = {**os.environ, **updates}
        return subprocess.run(["sh", str(SCRIPT)], env=env,
                              capture_output=True, text=True, timeout=5)

    def test_rejects_invalid_renderer_before_runtime_allocation(self):
        result = self.launch(RICEBOWL_PORTAL_RENDERER="vulkan",
                             RICEBOWL_PORTAL_STRICT_CI="1")
        self.assertEqual(result.returncode, 2)
        self.assertIn("PORTAL_SETUP_FAIL", result.stderr)

    def test_rejects_invalid_strict_flag(self):
        result = self.launch(RICEBOWL_PORTAL_RENDERER="pixman",
                             RICEBOWL_PORTAL_STRICT_CI="yes")
        self.assertEqual(result.returncode, 2)
        self.assertIn("strict flag", result.stderr)

    def test_refuses_strict_pixman_twice_without_creating_temp_files(self):
        pattern = "ricebowl-portals.*"
        before = set(Path("/tmp").glob(pattern))
        for _ in range(2):
            result = self.launch(RICEBOWL_PORTAL_RENDERER="pixman",
                                 RICEBOWL_PORTAL_STRICT_CI="1")
            self.assertEqual(result.returncode, 3)
            self.assertIn("PORTAL_STRICT_BLOCKED", result.stderr)
        self.assertEqual(before, set(Path("/tmp").glob(pattern)))

    def test_missing_render_node_reports_infrastructure_blocker(self):
        if any(path.is_char_device() and os.access(path, os.R_OK | os.W_OK)
               for path in Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").exists() else False:
            self.skipTest("DRM render node available; full acceptance runs in strict CI")
        result = self.launch(RICEBOWL_PORTAL_RENDERER="gles2",
                             RICEBOWL_PORTAL_STRICT_CI="1")
        self.assertEqual(result.returncode, 3)
        self.assertIn("no accessible DRM render node", result.stderr)


if __name__ == "__main__":
    unittest.main()
