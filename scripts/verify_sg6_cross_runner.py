#!/usr/bin/env python3
"""Compare four real .deb files from independent GitHub runner VMs.

A successful match demonstrates one workflow's two-runner byte consistency,
not independently audited build provenance or Mint hardware acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

FILES = (
    'ricebowl-wayland-core_0.1.0~preview2_all.deb',
    'ricebowl-wayland-session_0.1.0~preview3_all.deb',
    'ricebowl-riceplate-native_0.1.0~preview2_amd64.deb',
    'ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb',
)
SHA = re.compile(r'[0-9a-f]{40}\Z')
DIGEST = re.compile(r'[0-9a-f]{64}\Z')
WORKERS = ('host-a', 'host-b')


class ProvenanceError(ValueError):
    pass


def file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ProvenanceError(f'Package missing or symlinked: {path.name}')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def command(*cmd: str) -> str:
    return subprocess.check_output(cmd, text=True, timeout=15).strip()


def record(directory: Path, worker: str, source_sha: str) -> dict:
    if worker not in WORKERS or not SHA.fullmatch(source_sha):
        raise ProvenanceError('Invalid worker or exact-source SHA')
    if command('git', 'rev-parse', 'HEAD') != source_sha:
        raise ProvenanceError('Build checkout differs from claimed source')
    epoch = os.environ.get('SOURCE_DATE_EPOCH', '')
    if not epoch.isdecimal() or int(epoch) <= 0:
        raise ProvenanceError('Missing fixed source epoch')
    return {
        'schema_version': 1, 'worker': worker, 'source_sha': source_sha,
        'source_date_epoch': epoch,
        'runner_image': os.environ.get('ImageOS', ''),
        'runner_image_version': os.environ.get('ImageVersion', ''),
        'runner_name': os.environ.get('RUNNER_NAME', ''),
        # Opaque collision signal, not a cryptographic machine attestation.
        'hostname_sha256': hashlib.sha256(platform.node().encode()).hexdigest(),
        'rustc': command('rustc', '--version'),
        'cargo': command('cargo', '--version'),
        'dpkg': command('dpkg-deb', '--version').splitlines()[0],
        'cargo_lock_sha256': file_hash(Path('components/riceplate-wayland/Cargo.lock')),
        'packages': {name: file_hash(directory / name) for name in FILES},
        'hardware_accepted': False,
    }


def read_receipt(directory: Path, worker: str, source_sha: str) -> dict:
    path = directory / 'receipt.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise ProvenanceError(f'Missing/bad receipt for {worker}')
    try:
        obj = json.loads(path.read_text(encoding='utf-8'),
                         object_pairs_hook=_unique)
    except (UnicodeError, OSError, ValueError) as exc:
        raise ProvenanceError(f'Malformed receipt for {worker}') from exc
    if (type(obj) is not dict or obj.get('schema_version') != 1
            or obj.get('worker') != worker or obj.get('source_sha') != source_sha
            or obj.get('hardware_accepted') is not False
            or type(obj.get('packages')) is not dict
            or set(obj['packages']) != set(FILES)):
        raise ProvenanceError(f'Untrusted receipt identity for {worker}')
    for name in FILES:
        value = obj['packages'][name]
        if not isinstance(value, str) or not DIGEST.fullmatch(value):
            raise ProvenanceError(f'Invalid digest for {worker}: {name}')
        if file_hash(directory / name) != value:
            raise ProvenanceError(f'Artifact/receipt mismatch for {worker}: {name}')
    for field in ('runner_image', 'runner_image_version', 'runner_name', 'rustc',
                  'cargo', 'dpkg', 'cargo_lock_sha256', 'hostname_sha256',
                  'source_date_epoch'):
        if not isinstance(obj.get(field), str) or not obj[field]:
            raise ProvenanceError(f'Missing provenance field: {field}')
    for field in ('cargo_lock_sha256', 'hostname_sha256'):
        if not DIGEST.fullmatch(obj[field]):
            raise ProvenanceError(f'Invalid provenance hash: {field}')
    if not obj['source_date_epoch'].isdecimal() or int(obj['source_date_epoch']) <= 0:
        raise ProvenanceError('Invalid source epoch')
    return obj


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProvenanceError(f'Duplicate receipt key: {key}')
        result[key] = value
    return result


def compare(root: Path, source_sha: str) -> dict:
    if not SHA.fullmatch(source_sha):
        raise ProvenanceError('Invalid source commit')
    a, b = (read_receipt(root / worker, worker, source_sha) for worker in WORKERS)
    if a['runner_name'] == b['runner_name'] or a['hostname_sha256'] == b['hostname_sha256']:
        raise ProvenanceError('Independent runner identities were not observed')
    compared = ('source_date_epoch', 'runner_image', 'runner_image_version',
                'rustc', 'cargo', 'dpkg', 'cargo_lock_sha256')
    for key in compared:
        if a[key] != b[key]:
            raise ProvenanceError(f'Unpinned or divergent build environment: {key}')
    for name in FILES:
        if a['packages'][name] != b['packages'][name]:
            raise ProvenanceError(f'Cross-runner package mismatch: {name}')
    return {
        'schema_version': 1, 'source_sha': source_sha,
        'software_ci_only': True, 'hardware_accepted': False,
        'separate_runner_names_observed': True,
        'byte_identical_package_count': len(FILES),
        'same_runner_image_and_build_tools': True,
        'independent_external_provenance_certified': False,
        'packages': a['packages'],
        'runner_image_version': a['runner_image_version'],
        'cargo_lock_sha256': a['cargo_lock_sha256'],
        'limitations': [
            'Two GitHub-hosted runner VMs in one workflow are not independent third-party builders',
            'Runner name/hostname do not cryptographically attest machine identity',
            'Attestation binds comparison artifacts to Actions identity, not reproducible toolchain sources',
            'No Mint/ThinkPad, GPU, default-login or hardware sign-off',
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('record', 'compare'))
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--worker', choices=WORKERS)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == 'record':
            if args.worker is None:
                raise ProvenanceError('Recording requires worker identity')
            result = record(args.directory, args.worker, args.source_sha)
        else:
            result = compare(args.directory, args.source_sha)
        if args.output.is_symlink():
            raise ProvenanceError('Refuse symlink evidence output')
        with args.output.open('x', encoding='utf-8') as target:
            json.dump(result, target, indent=2, sort_keys=True)
            target.write('\n')
    except (ProvenanceError, OSError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as exc:
        print(f'SG6 cross-runner: BLOCKED — {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
