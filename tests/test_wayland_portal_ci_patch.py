"""CI-only PipeWire portal source-patch fail-closed regressions."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ci_portal_generic_remote import END, START, REQUIRES, patch_source, patch_stream_buffers, STREAM_FLAGS


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

    def test_buffer_flag_patch_requires_exact_pinned_upstream(self):
        original = (
            "pub fn queue_frame(\n" + STREAM_FLAGS + "\n"
            "    stream: StreamBox<'static>,\n"
            "        // Connect as an output (we produce frames).\n"
            "        Ok(Self { stream, node_id })\n"
            "    /// Get the PipeWire node ID for this stream.\n"
        )
        result = patch_stream_buffers(original)
        self.assertIn("StreamFlags::MAP_BUFFERS | StreamFlags::DRIVER", result)
        self.assertNotIn("StreamFlags::ALLOC_BUFFERS", result)
        self.assertIn("SPA_PARAM_BUFFERS_dataType", result)
        self.assertIn("PORTAL_CI_BUFFERS_NEGOTIATED", result)
        self.assertIn(".param_changed(", result)
        self.assertIn("let ci_listener", result)
        self.assertIn("Ok(Self { ci_listener, stream, node_id })", result)
        for invalid in ("missing", STREAM_FLAGS, original + STREAM_FLAGS,
                        original + ".param_changed(", original.replace("queue_frame(", "enqueue(")):
            with self.subTest(source=invalid[:30]), self.assertRaises(ValueError):
                patch_stream_buffers(invalid)

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
