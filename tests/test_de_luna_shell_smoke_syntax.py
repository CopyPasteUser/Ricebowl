"""Prevent nested quote errors from skipping native Wayland taskbar smoke."""
from pathlib import Path
import shutil
import subprocess
import unittest


class LunaTaskbarShellSyntaxTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("sh"), "POSIX shell not available")
    def test_headless_window_smoke_is_valid_posix_shell(self):
        script = Path(__file__).resolve().parents[1] / "scripts/smoke_riceplate_windows.sh"
        result = subprocess.run(["sh", "-n", str(script)],
                                capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_embed_does_not_terminate_outer_quoted_script(self):
        script = (Path(__file__).resolve().parents[1] /
                  "scripts/smoke_riceplate_windows.sh").read_text()
        self.assertIn("dbus-run-session -- sh -eu -c '", script)
        self.assertNotIn("<<'PY'", script)
        self.assertIn("<<PY", script)


if __name__ == "__main__":
    unittest.main()
