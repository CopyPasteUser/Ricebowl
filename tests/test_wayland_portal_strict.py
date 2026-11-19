"""Strict portal wrapper must never silently fall back or leak runtimes."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_wayland_portals.sh"
from scripts.wayland_portal_frame_painter import allowed_private_frame_painter


class PortalRunnerFailClosedTests(unittest.TestCase):
    def launch(self, **updates):
        env = {**os.environ, **updates}
        return subprocess.run(["sh", str(SCRIPT)], env=env,
                              capture_output=True, text=True, timeout=5)

    def test_strict_portal_ci_preserves_frame_and_recovery_gates_with_bounded_archive(self):
        workflow = (ROOT / ".github/workflows/wayland-portal-strict.yml").read_text()
        archive = ("sudo env GITHUB_ACTIONS=true /usr/bin/python3 "
                   "scripts/ci_ubuntu_archive.py")
        self.assertEqual(workflow.count(archive), 3)
        self.assertEqual(workflow.count("Acquire::Retries=2"), 6)
        self.assertEqual(workflow.count("Acquire::http::Timeout=15"), 6)
        self.assertEqual(workflow.count("Acquire::https::Timeout=15"), 6)
        for gate in (
            "portal-unit:",
            "portal-pixman-repeat:",
            "portal-strict-software-frame:",
            "Repeat existing pixman acceptance and verify no runtime leftovers",
            "Crash labwc before socket creation and verify runtime recovery",
            "Strict no-DRM ScreenCast from real wlroots SHM frames to GStreamer",
            "RICEBOWL_PORTAL_STRICT_CI: '1'",
            "RICEBOWL_PORTAL_BACKEND: generic",
            "RICEBOWL_PORTAL_RENDERER: pixman",
            "scripts/smoke_wayland_portals.sh",
            "needs: portal-unit",
        ):
            self.assertIn(gate, workflow)
        self.assertNotIn("continue-on-error:", workflow)
        # Never quietly swap the real capture lane for a mock or a generic
        # endpoint probe. The CI-owned backend is pinned to a source commit.
        self.assertIn("09fe2bd00dcb7139c34f3d437376af81a2fec96b", workflow)
        self.assertIn("cargo build --release --locked", workflow)

    def test_strict_portal_ci_uses_runner_local_helper_without_gpu_host_mutation(self):
        workflow = (ROOT / ".github/workflows/wayland-portal-strict.yml").read_text()
        self.assertEqual(workflow.count("- 'scripts/ci_ubuntu_archive.py'"), 2)
        self.assertEqual(workflow.count("- 'docs/sg1-sg7-evidence-progress.md'"), 2)
        # The GPU lane is separately opt-in on self-hosted DRM-capable CI.
        self.assertIn("runs-on: [self-hosted, linux, drm-render]", workflow)
        gpu_lane = workflow.split("  portal-gpu-frame:", 1)[1]
        self.assertNotIn("scripts/ci_ubuntu_archive.py", gpu_lane)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.gpu",
                      gpu_lane)

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
                             RICEBOWL_PORTAL_BACKEND="wlr",
                             RICEBOWL_PORTAL_STRICT_CI="1")
        self.assertEqual(result.returncode, 3)
        self.assertIn("no accessible DRM render node", result.stderr)


    def test_generic_requires_strict_mode_and_matching_renderer(self):
        result = self.launch(RICEBOWL_PORTAL_BACKEND="generic",
                             RICEBOWL_PORTAL_RENDERER="pixman",
                             RICEBOWL_PORTAL_STRICT_CI="0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("reserved for strict", result.stderr)
        result = self.launch(RICEBOWL_PORTAL_BACKEND="generic",
                             RICEBOWL_PORTAL_RENDERER="gles2",
                             RICEBOWL_PORTAL_STRICT_CI="1")
        self.assertEqual(result.returncode, 3)
        self.assertIn("requires pixman", result.stderr)

    def test_frame_witness_requires_private_runtime_and_exact_strict_pair(self):
        with tempfile.TemporaryDirectory(prefix="ricebowl-portal-test-") as private:
            runtime = Path(private)
            marker = runtime / ".ricebowl-portal-ci"
            marker.touch(mode=0o600)
            env = {
                "XDG_RUNTIME_DIR": private,
                "GDK_BACKEND": "wayland",
                "RICEBOWL_PORTAL_CAPTURE_CI": "1",
                "RICEBOWL_PORTAL_STRICT_CI": "1",
                "RICEBOWL_PORTAL_BACKEND": "wlr",
                "WLR_RENDERER": "gles2",
            }
            self.assertTrue(allowed_private_frame_painter(env))
            self.assertTrue(allowed_private_frame_painter({
                **env, "RICEBOWL_PORTAL_BACKEND": "generic",
                "WLR_RENDERER": "pixman",
            }))
            for changed in (
                {"RICEBOWL_PORTAL_BACKEND": "wlr", "WLR_RENDERER": "pixman"},
                {"RICEBOWL_PORTAL_BACKEND": "generic", "WLR_RENDERER": "gles2"},
                {"RICEBOWL_PORTAL_STRICT_CI": "0"},
                {"RICEBOWL_PORTAL_CAPTURE_CI": "0"},
                {"GDK_BACKEND": "x11"},
            ):
                with self.subTest(changed=changed):
                    self.assertFalse(allowed_private_frame_painter({**env, **changed}))
            marker.unlink()
            marker.symlink_to(runtime / "other")
            self.assertFalse(allowed_private_frame_painter(env))
            marker.unlink()
            marker.touch(mode=0o600)
            os.chmod(runtime, 0o750)
            self.assertFalse(allowed_private_frame_painter(env))

if __name__ == "__main__":
    unittest.main()
