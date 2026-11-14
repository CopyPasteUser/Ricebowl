"""CI-only PipeWire portal source-patch fail-closed regressions."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ci_portal_generic_remote import END, START, REQUIRES, patch_source


class PrivateRemotePatchTests(unittest.TestCase):
    def test_replaces_only_known_socketpair_function(self):
        original = (
            "prefix\n" + START +
            "\n".join(["\n // " + marker for marker in REQUIRES]) +
            "\n\n" + END + "\nsuffix\n"
        )
        patched = patch_source(original)
        self.assertTrue(patched.startswith("prefix\n"))
        self.assertTrue(patched.endswith(END + "\nsuffix\n"))
        self.assertIn('PORTAL_CI_REMOTE_UNRESTRICTED', patched)
        self.assertIn('.ricebowl-portal-ci', patched)
        self.assertIn('mode() & 0o077', patched)
        self.assertNotIn('UnixStream::pair()', patched)

    def test_rejects_unexpected_or_multiply_defined_source(self):
        for source in (
            "missing source",
            START + " \n" + END,
            START + REQUIRES[0] + REQUIRES[1] + END,
            START + " ".join(REQUIRES) + "\n" + END + START,
        ):
            with self.subTest(source=source[:45]):
                with self.assertRaises(ValueError):
                    patch_source(source)


if __name__ == "__main__":
    unittest.main()
