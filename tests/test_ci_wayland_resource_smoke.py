"""Pure synthetic /proc tests for the CI-only native RicePlate growth probe."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'scripts' / 'ci_wayland_resource_smoke.py'
SPEC = importlib.util.spec_from_file_location('ci_wayland_resource_smoke', MODULE)
probe = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class NativeResourceSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.proc = self.root / 'proc'
        self.proc.mkdir()
        self.binary = self.root / 'riceplate-native'
        self.binary.write_bytes(b'ELF-test-only')
        self.runtime = self.root / 'run'
        self.runtime.mkdir(mode=0o700)
        self.baseline = self.runtime / 'baseline.json'

    def process(self, pid=111, *, start=123456, env=None, rss=45000,
                pss=25000, fds=5, threads=2, exe=None, name='native (test)'):
        path = self.proc / str(pid)
        path.mkdir()
        (path / 'exe').symlink_to(exe or self.binary)
        (path / 'environ').write_bytes(
            env if env is not None else b'XDG_RUNTIME_DIR=' + os.fsencode(self.runtime) + b'\0')
        # Fields 3..21 followed by kernel start-time field 22.
        (path / 'stat').write_text(
            f'{pid} ({name}) ' + ' '.join(['S'] + ['0'] * 18 + [str(start)] + ['0'] * 7))
        (path / 'smaps_rollup').write_text(f'Pss: {pss} kB\n')
        (path / 'status').write_text(f'VmRSS:\t{rss} kB\nThreads:\t{threads}\n')
        (path / 'fd').mkdir()
        for fd in range(fds):
            (path / 'fd' / str(fd)).touch()
        return path

    def snapshot(self):
        return probe.sample_native(self.binary, self.runtime, proc_root=self.proc, uid=os.geteuid())

    def test_exact_same_runtime_binary_and_starttime_are_required(self):
        process = self.process()
        row = self.snapshot()
        self.assertEqual((row.pid, row.start_ticks, row.pss_kib, row.rss_kib,
                          row.fds, row.threads), (111, 123456, 25000, 45000, 5, 2))
        self.assertTrue(probe.compare(row, row)['ok'])
        self.assertFalse(probe.compare(row, row)['hardware_accepted'])
        (process / 'environ').write_bytes(b'XDG_RUNTIME_DIR=/tmp/unrelated\0')
        with self.assertRaisesRegex(probe.ResourceSmokeError, 'exactly one'):
            self.snapshot()
        (process / 'environ').write_bytes(
            b'XDG_RUNTIME_DIR=' + os.fsencode(self.runtime) + b'\0'
            b'XDG_RUNTIME_DIR=' + os.fsencode(self.runtime) + b'\0')
        with self.assertRaisesRegex(probe.ResourceSmokeError, 'exactly one'):
            self.snapshot()

    def test_ambiguous_private_panels_never_report_a_passing_comparison(self):
        self.process(111)
        self.process(222)
        with self.assertRaisesRegex(probe.ResourceSmokeError, 'exactly one'):
            self.snapshot()

    def test_process_restart_growth_and_missing_counter_fail_closed(self):
        base = probe.Sample(111, 7, 32000, 40000, 11, 2)
        with self.assertRaisesRegex(probe.ResourceSmokeError, 'restarted'):
            probe.compare(base, replace(base, start_ticks=8))
        with self.assertRaisesRegex(probe.ResourceSmokeError, 'growth exceeds'):
            probe.compare(base, replace(base, fds=base.fds + 25))
        with self.assertRaisesRegex(probe.ResourceSmokeError, 'growth exceeds'):
            probe.compare(base, replace(base, pss_kib=base.pss_kib + 33000))
        self.process()
        (self.proc / '111' / 'smaps_rollup').write_text('Rss: 2 kB\n')
        with self.assertRaisesRegex(probe.ResourceSmokeError, 'Pss'):
            self.snapshot()

    def test_private_atomic_baseline_and_reject_symlink_or_tampering(self):
        data = probe.Sample(111, 7, 23000, 33000, 5, 2)
        probe._write_private(self.baseline, probe.asdict(data))
        self.assertEqual(self.baseline.stat().st_mode & 0o777, 0o600)
        self.assertEqual(probe._read_baseline(self.baseline), data)
        self.baseline.write_text(json.dumps({**probe.asdict(data), 'fds': True}))
        with self.assertRaisesRegex(probe.ResourceSmokeError, 'Invalid'):
            probe._read_baseline(self.baseline)
        self.baseline.unlink()
        other = self.root / 'outside'
        other.write_text(json.dumps(probe.asdict(data)))
        self.baseline.symlink_to(other)
        with self.assertRaisesRegex(probe.ResourceSmokeError, 'Invalid'):
            probe._read_baseline(self.baseline)
        self.baseline.unlink()
        self.runtime.chmod(0o777)
        with self.assertRaisesRegex(probe.ResourceSmokeError, 'owner-private'):
            probe._write_private(self.baseline, probe.asdict(data))


if __name__ == '__main__':
    unittest.main()
