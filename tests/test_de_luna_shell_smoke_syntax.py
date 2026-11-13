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

    def test_nested_python_heredocs_do_not_end_the_outer_shell_script(self):
        script = (Path(__file__).resolve().parents[1] /
                  "scripts/smoke_riceplate_windows.sh").read_text()
        # The DBus child is fed a quoted outer here-document. Python
        # here-documents inside it are parsed by the child shell.
        self.assertIn("dbus-run-session -- sh -eu -s -- ", script)
        self.assertEqual(script.count("<<'RICEBOWL_WINDOW_SMOKE_SH'"), 1)
        self.assertEqual(script.count("\nRICEBOWL_WINDOW_SMOKE_SH\n"), 1)
        self.assertNotIn("dbus-run-session -- sh -eu -c '", script)
        self.assertIn("<<PY", script)


if __name__ == "__main__":
    unittest.main()
