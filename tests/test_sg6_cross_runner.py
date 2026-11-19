"""CI-only negative tests for two-runner Debian receipt comparison."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'scripts' / 'verify_sg6_cross_runner.py'
SPEC = importlib.util.spec_from_file_location('verify_sg6_cross_runner', MODULE)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)
SHA = 'c' * 40


class CrossRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.receipts = []
        for worker in verifier.WORKERS:
            directory = self.root / worker
            directory.mkdir()
            digests = {}
            for name in verifier.FILES:
                file = directory / name
                file.write_bytes((name + '\n').encode())
                digests[name] = verifier.file_hash(file)
            receipt = {
                'schema_version': 1, 'worker': worker, 'source_sha': SHA,
                'source_date_epoch': '1795102175', 'runner_image': 'ubuntu24',
                'runner_image_version': '20261119.1', 'runner_name': worker,
                'hostname_sha256': ('a' if worker == 'host-a' else 'b') * 64,
                'rustc': 'rustc 1.88.0', 'cargo': 'cargo 1.88.0',
                'dpkg': 'Debian dpkg-deb version 1',
                'cargo_lock_sha256': 'f' * 64, 'packages': digests,
                'hardware_accepted': False,
            }
            self.receipts.append(receipt)
            self.save(worker, receipt)

    def save(self, worker, receipt):
        (self.root / worker / 'receipt.json').write_text(json.dumps(receipt))

    def test_two_runners_matching_four_real_files(self):
        report = verifier.compare(self.root, SHA)
        self.assertEqual(report['byte_identical_package_count'], 4)
        self.assertFalse(report['independent_external_provenance_certified'])
        self.assertFalse(report['hardware_accepted'])

    def test_payload_tampering_and_missing_archive_are_rejected(self):
        file = self.root / 'host-b' / verifier.FILES[2]
        file.write_bytes(b'forged binary')
        with self.assertRaisesRegex(verifier.ProvenanceError, 'Artifact/receipt mismatch'):
            verifier.compare(self.root, SHA)
        file.unlink()
        with self.assertRaises(verifier.ProvenanceError):
            verifier.compare(self.root, SHA)

    def test_source_revision_environment_and_host_collisions(self):
        other = self.receipts[1]
        for field, change in (('source_sha', '0'*40),
                              ('runner_image_version', 'outdated'),
                              ('hostname_sha256', 'a'*64),
                              ('runner_name', 'host-a')):
            with self.subTest(field=field):
                old = other[field]
                other[field] = change
                self.save('host-b', other)
                with self.assertRaises(verifier.ProvenanceError):
                    verifier.compare(self.root, SHA)
                other[field] = old
                self.save('host-b', other)

    def test_duplicate_receipt_keys_fail_closed(self):
        path = self.root / 'host-a' / 'receipt.json'
        path.write_text('{"worker":"host-a","worker":"host-a"}')
        with self.assertRaises(verifier.ProvenanceError):
            verifier.compare(self.root, SHA)

    def test_reject_symlinked_archive(self):
        directory = self.root / 'host-a'
        file = directory / verifier.FILES[0]
        file.unlink()
        file.symlink_to(directory / verifier.FILES[1])
        with self.assertRaises(verifier.ProvenanceError):
            verifier.compare(self.root, SHA)


if __name__ == '__main__':
    unittest.main()
