"""SG6 Mint-container policy checks. These are not a substitute for real CI."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/smoke_wayland_mint_compat.sh"
WORKFLOW = ROOT / ".github/workflows/riceplate-native.yml"


class MintCompatWorkflowPolicyTests(unittest.TestCase):
    def test_actual_mint_dpkg_lifecycle_not_an_ubuntu_relabel(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for must_have in (
            "packages[.]linuxmint[.]com", "xia[[:space:]]",
            "apt-cache policy mintsystem", "RICEBOWL_SOURCE_SHA",
            "apt-get install -y --no-install-recommends",
            "--reinstall", "corrupt-native.deb",
            "kill -KILL", "dpkg --audit", "apt-get purge -y",
            "check_private_data", "sha256sum --check --status",
            "XFCE_PANEL_MUST_SURVIVE=1",
        ):
            with self.subTest(required=must_have):
                self.assertIn(must_have, script)
        self.assertNotIn("os-release", script.split("apt-get -o Acquire::Retries=2 update", 1)[1])

    def test_separate_job_consumes_exact_native_ci_artifact_with_no_host_install(self):
        yaml = WORKFLOW.read_text(encoding="utf-8")
        job = yaml.split("\n  sg6-mint221-compat:\n", 1)[1].split(
            "\n  attest-native-preview:\n", 1
        )[0]
        for required in (
            "needs: native-layer-shell", "runs-on: ubuntu-24.04",
            "actions/download-artifact@v4", "riceplate-native-preview-",
            "sha256sum -c SHA256SUMS", "linuxmintd/mint22.1-amd64",
            "docker image inspect", "docker run --rm --pull=never",
            "--volume \"$PWD/dist/riceplate-native-preview:/packages:ro\"",
            "RICEBOWL_SOURCE_SHA", "/tests/mint-compat.sh",
        ):
            with self.subTest(required=required):
                self.assertIn(required, job)
        self.assertNotIn("id-token: write", job)
        self.assertNotIn("attestations: write", job)


if __name__ == "__main__":
    unittest.main()
