"""Real compositor Creator size/scale matrix guards (not mock captures)."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/smoke_wayland_shared_rice_engine.sh"


class CreatorCompositorMatrixTests(unittest.TestCase):
    def test_real_labwc_matrix_has_three_sizes_and_two_structurally_distinct_rices(self):
        script = SCRIPT.read_text(encoding="utf-8")
        # The matrix shares the *real compositor*, private D-Bus and the
        # source-locked native engine already exercised by this CI entrypoint.
        self.assertIn("dbus-run-session -- sh", script)
        self.assertIn("de start --nested --panel native", script)
        self.assertIn("for spec in 'compact 1024 768 1' "
                      "'laptop 1366 768 1.25' "
                      "'desktop 1600 900 1'", script)
        self.assertIn("wlr-randr --output", script)
        self.assertIn("--custom-mode", script)
        self.assertIn('capture_matrix chrome "$width" "$height" "$name"', script)
        self.assertIn('apply_rice chrome "$luna"', script)
        self.assertIn('capture_matrix "$luna" "$width" "$height" "$name"', script)
        self.assertIn('ImageChops.difference', script)
        self.assertIn('assert changed(a, b) > 100', script)
        self.assertIn('assert changed(a, c) < 6000', script)
        # A compositor repaint at fractional scale may lag behind the
        # acknowledged transaction. Retry real frames only, never weaken
        # the restore pixel threshold or hide a persistent mismatch.
        self.assertIn('while [ "$attempt" -lt 24 ]', script)
        self.assertIn('assert changed < 6000', script)
        self.assertIn('Creator restore did not converge', script)
        self.assertIn('Creator diagnostic: sizes', script)
        self.assertIn('restore-mismatch.png', script)

    def test_matrix_preserves_next_login_and_rejects_imaginary_visual_proof(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('assert reply["panel"] == "native"', script)
        self.assertIn('not reply["next_login_persisted"]', script)
        self.assertIn('recipes.current_selection() == ("classic", None)', script)
        self.assertIn('image.verify()', script)
        self.assertIn('image.load()', script)
        self.assertIn('image.size == (width, height)', script)
        self.assertIn('wlr-randr --output "$output" --custom-mode 1024x768@60Hz --scale 1',
                      script)
        self.assertNotIn("systemctl set-default", script)
        self.assertNotIn("update-alternatives", script)


if __name__ == "__main__":
    unittest.main()
