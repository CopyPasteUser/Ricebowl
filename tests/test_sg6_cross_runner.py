"""CI-only negative tests for two-runner Debian receipt comparison."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from unittest import mock
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

    def compare(self, *, lock='f' * 64, epoch='1795102175'):
        return verifier.compare(self.root, SHA, expected_lock_sha=lock,
                                expected_epoch=epoch)

    def test_two_runners_matching_four_real_files(self):
        report = self.compare()
        self.assertEqual(report['byte_identical_package_count'], 4)
        self.assertFalse(report['independent_external_provenance_certified'])
        self.assertFalse(report['hardware_accepted'])
        self.assertTrue(report['same_runner_os_and_build_tools'])
        self.assertEqual(set(report['runner_image_versions']), {'host-a', 'host-b'})

    def test_different_hosted_image_patch_versions_are_recorded_not_hidden(self):
        # Hosted ubuntu-24.04 image patches can roll independently between jobs;
        # reproducibility is established by independent artifact bytes.
        self.receipts[1]['runner_image_version'] = '20261120.2'
        self.save('host-b', self.receipts[1])
        report = self.compare()
        self.assertEqual(report['runner_image_versions'], {
            'host-a': '20261119.1', 'host-b': '20261120.2'})
        self.assertEqual(report['byte_identical_package_count'], 4)

    def test_payload_tampering_and_missing_archive_are_rejected(self):
        file = self.root / 'host-b' / verifier.FILES[2]
        file.write_bytes(b'forged binary')
        with self.assertRaisesRegex(verifier.ProvenanceError, 'Artifact/receipt mismatch'):
            self.compare()
        file.unlink()
        with self.assertRaises(verifier.ProvenanceError):
            self.compare()

    def test_source_revision_environment_and_host_collisions(self):
        other = self.receipts[1]
        for field, change in (('source_sha', '0'*40),
                              ('runner_image', 'different-distribution'),
                              ('rustc', 'rustc 0.0.0'),
                              ('hostname_sha256', 'a'*64),
                              ('runner_name', 'host-a')):
            with self.subTest(field=field):
                old = other[field]
                other[field] = change
                self.save('host-b', other)
                with self.assertRaises(verifier.ProvenanceError):
                    self.compare()
                other[field] = old
                self.save('host-b', other)

    def test_receipts_are_bound_to_the_checked_out_lockfile_and_epoch(self):
        for key, value in [('cargo_lock_sha256', 'e' * 64),
                           ('source_date_epoch', '1795102176')]:
            with self.subTest(field=key):
                original = self.receipts[0][key]
                self.receipts[0][key] = value
                self.save('host-a', self.receipts[0])
                with self.assertRaises(verifier.ProvenanceError):
                    self.compare()
                self.receipts[0][key] = original
                self.save('host-a', self.receipts[0])
        with self.assertRaisesRegex(verifier.ProvenanceError, 'lockfile/epoch'):
            self.compare(lock='bad')
        with self.assertRaisesRegex(verifier.ProvenanceError, 'lockfile/epoch'):
            self.compare(epoch='not-a-timestamp')

    def test_reject_extra_fields_bool_schema_and_unsafe_directories(self):
        a = self.receipts[0]
        for field, value in [('unknown', 'spoofed'), ('schema_version', True),
                             ('source_date_epoch', '١٧٩٥١٠٢١٧٥')]:
            with self.subTest(field=field, value=value):
                old = a.get(field)
                a[field] = value
                self.save('host-a', a)
                with self.assertRaises(verifier.ProvenanceError):
                    self.compare()
                if old is None:
                    del a[field]
                else:
                    a[field] = old
                self.save('host-a', a)
        alias = self.root.parent / 'comparison-symlink'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(verifier.ProvenanceError, 'symlinked'):
            verifier.compare(alias, SHA, expected_lock_sha='f' * 64,
                             expected_epoch='1795102175')

    def test_record_rejects_wrong_commit_epoch_or_modified_tracked_source(self):
        with mock.patch.object(verifier, 'command', side_effect=lambda *args: {
            ('git', 'rev-parse', 'HEAD'): SHA,
            ('git', 'log', '-1', '--format=%ct', 'HEAD'): '1795102175',
            ('git', 'status', '--porcelain', '--untracked-files=no'): '',
            ('rustc', '--version'): 'rustc 1.88.0',
            ('cargo', '--version'): 'cargo 1.88.0',
            ('dpkg-deb', '--version'): 'dpkg 1',
        }[args]):
            with mock.patch.dict(verifier.os.environ, {'SOURCE_DATE_EPOCH': '1'}):
                with self.assertRaisesRegex(verifier.ProvenanceError, 'Source epoch'):
                    verifier.record(self.root / 'host-a', 'host-a', SHA)
            with mock.patch.dict(verifier.os.environ, {'SOURCE_DATE_EPOCH': '1795102175'}):
                with mock.patch.object(verifier, 'command', side_effect=lambda *args: (
                    ' M components/riceplate-wayland/Cargo.lock'
                    if args == ('git', 'status', '--porcelain', '--untracked-files=no')
                    else {('git', 'rev-parse', 'HEAD'): SHA,
                          ('git', 'log', '-1', '--format=%ct', 'HEAD'): '1795102175'}[args]
                )):
                    with self.assertRaisesRegex(verifier.ProvenanceError, 'Tracked source'):
                        verifier.record(self.root / 'host-a', 'host-a', SHA)

    def test_duplicate_receipt_keys_fail_closed(self):
        path = self.root / 'host-a' / 'receipt.json'
        path.write_text('{"worker":"host-a","worker":"host-a"}')
        with self.assertRaises(verifier.ProvenanceError):
            self.compare()

    def test_reject_symlinked_archive(self):
        directory = self.root / 'host-a'
        file = directory / verifier.FILES[0]
        file.unlink()
        file.symlink_to(directory / verifier.FILES[1])
        with self.assertRaises(verifier.ProvenanceError):
            self.compare()


if __name__ == '__main__':
    unittest.main()
