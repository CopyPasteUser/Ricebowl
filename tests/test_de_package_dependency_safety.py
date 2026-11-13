"""Static opt-in DEB dependency and coexistence contract; no host mutation."""

from email.parser import Parser
from pathlib import Path
import unittest

from macrice.de.session import project_root


ROOT = project_root()
PACKAGE = ROOT / "packaging/wayland"


def control(filename):
    source = (PACKAGE / filename).read_text(encoding="utf-8")
    return Parser().parsestr(source, headersonly=True)


class WaylandPackagePolicyTests(unittest.TestCase):
    def test_required_lock_chain_is_install_dependency_not_optional_recommendation(self):
        session = control("control")
        required = {item.split(" (", 1)[0].strip() for item in
                    session["Depends"].split(",")}
        recommended = {item.strip() for item in session["Recommends"].split(",")}
        self.assertTrue({"labwc", "waybar", "swaylock", "swayidle",
                         "dbus-user-session", "foot", "fuzzel"} <= required)
        self.assertNotIn("swaylock", recommended)
        self.assertNotIn("swayidle", recommended)
        self.assertIn("swaybg", recommended)
        self.assertNotIn("xfce4-session", required)

    def test_complete_meta_package_pins_core_and_requires_native_and_session(self):
        core = control("core-control")
        session = control("control")
        native = control("native-control.in")
        desktop = control("desktop-control")
        self.assertEqual(desktop["Architecture"], "amd64")
        self.assertEqual(core["Architecture"], "all")
        self.assertEqual(session["Architecture"], "all")
        self.assertEqual(native["Architecture"], "amd64")
        self.assertIn(f"ricebowl-wayland-core (= {core['Version']})", desktop["Depends"])
        self.assertIn(f"ricebowl-wayland-session (>= {session['Version']})", desktop["Depends"])
        self.assertIn(f"ricebowl-riceplate-native (>= {native['Version']})", desktop["Depends"])
        self.assertNotIn("xdg-desktop-portal-wlr", desktop["Depends"])
        self.assertIn("xdg-desktop-portal-wlr", session["Depends"])

    def test_login_entries_are_opt_in_and_wrapper_never_changes_dm_or_xfce(self):
        launcher = (PACKAGE / "ricebowl-wayland-session").read_text(encoding="utf-8")
        native = (PACKAGE / "ricebowl-native.desktop").read_text(encoding="utf-8")
        regular = (PACKAGE / "ricebowl.desktop").read_text(encoding="utf-8")
        self.assertIn("TryExec=/usr/bin/riceplate-native", native)
        self.assertIn("Exec=/usr/bin/ricebowl-wayland-session --native", native)
        self.assertIn("Exec=/usr/bin/ricebowl-wayland-session", regular)
        self.assertIn("RICEBOWL_DM_SESSION=1", launcher)
        self.assertIn('exec "$app" de start', launcher)
        for forbidden in ("systemctl enable", "update-alternatives", "dpkg-reconfigure",
                          "xfconf-query", "lightdm.conf", "sddm.conf", "rm -rf"):
            self.assertNotIn(forbidden, launcher)

    def test_headless_startup_timestamps_are_not_labelled_hardware_results(self):
        smoke = (ROOT / "scripts/smoke_wayland_packaged_login.sh").read_text()
        self.assertIn("time.monotonic_ns()", smoke)
        self.assertIn("HEADLESS_SOCKET_READY_MS=", smoke)
        self.assertIn("HEADLESS_FRAME_CAPTURE_MS=", smoke)
        self.assertIn("HEADLESS_MEASUREMENT_SCOPE=disposable-ubuntu", smoke)
        self.assertNotIn("HARDWARE_ACCEPTED=true", smoke)

    def test_release_verifier_requires_only_namespaced_payloads_and_no_maintainers(self):
        verifier = (ROOT / "scripts/verify_wayland_package_set.sh").read_text()
        self.assertIn("dpkg-deb --ctrl-tarfile", verifier)
        self.assertIn("Refusing maintainer scripts", verifier)
        self.assertIn("Unexpected installed path", verifier)
        self.assertIn("The desktop meta package must not install files", verifier)
        self.assertIn("SOURCE_DATE_EPOCH", (ROOT / "scripts/build_wayland_core_deb.sh").read_text())
        # The existing package smoke performs real install / downgrade / purge
        # in disposable Ubuntu; these tests only check committed contracts.


if __name__ == "__main__":
    unittest.main()
