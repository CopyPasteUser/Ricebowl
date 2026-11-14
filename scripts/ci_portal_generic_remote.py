#!/usr/bin/python3
"""CI-only repair of the pinned generic portal's invalid PipeWire remote FD.

Only a disposable PipeWire daemon is reachable from this private runtime.
This fixture intentionally does NOT test the real portal's per-node grants,
sandbox isolation or user consent and MUST NOT be shipped as a runtime patch.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

START = "    fn create_remote_fd("
END = "    /// Create a new video source stream."
REQUIRES = ("UnixStream::pair()", ".connect_fd(server_fd, None)", "Ok(client_fd)")
REPLACEMENT = r"""    fn create_remote_fd(
        _context: &pipewire::context::ContextBox<'_>,
    ) -> Result<OwnedFd, PortalError> {
        use std::os::unix::fs::{FileTypeExt, PermissionsExt};
        use std::os::unix::net::UnixStream;
        use std::path::PathBuf;

        // CI fixture ONLY. No production PipeWire grants, consent or sandbox
        // semantics are provided by this direct private-daemon socket.
        if std::env::var("RICEBOWL_PORTAL_STRICT_CI").ok().as_deref() != Some("1")
            || std::env::var("RICEBOWL_PORTAL_BACKEND").ok().as_deref() != Some("generic")
        {
            return Err(PortalError::PipeWire("CI-only remote cannot run outside strict generic test".into()));
        }
        let runtime = PathBuf::from(std::env::var_os("XDG_RUNTIME_DIR")
            .ok_or_else(|| PortalError::PipeWire("missing private CI runtime".into()))?);
        let meta = runtime.symlink_metadata()
            .map_err(|e| PortalError::PipeWire(format!("CI runtime not accessible: {e}")))?;
        if !runtime.is_absolute() || !meta.is_dir() || meta.file_type().is_symlink()
            || meta.permissions().mode() & 0o077 != 0
        {
            return Err(PortalError::PipeWire("CI runtime is not a private directory".into()));
        }
        let marker = runtime.join(".ricebowl-portal-ci").symlink_metadata()
            .map_err(|e| PortalError::PipeWire(format!("CI marker missing: {e}")))?;
        if !marker.is_file() || marker.file_type().is_symlink() {
            return Err(PortalError::PipeWire("invalid CI-only session marker".into()));
        }
        let socket_path = runtime.join("pipewire-0");
        let socket_type = socket_path.symlink_metadata()
            .map_err(|e| PortalError::PipeWire(format!("private CI PipeWire socket missing: {e}")))?;
        if !socket_type.file_type().is_socket() {
            return Err(PortalError::PipeWire("private CI PipeWire path is not a socket".into()));
        }
        let socket = UnixStream::connect(&socket_path)
            .map_err(|e| PortalError::PipeWire(format!("private CI PipeWire connect failed: {e}")))?;
        eprintln!("PORTAL_CI_REMOTE_UNRESTRICTED: private test daemon only");
        Ok(socket.into())
    }

"""


def patch_source(source: str) -> str:
    """Replace only the known-broken socketpair implementation; fail closed."""
    if source.count(START) != 1:
        raise ValueError("unsupported pinned upstream source structure")
    begin = source.index(START)
    if source.count(END, begin) != 1:
        raise ValueError("unexpected source structure following remote FD function")
    end = source.index(END, begin)
    old = source[begin:end]
    if any(marker not in old for marker in REQUIRES):
        raise ValueError("upstream PipeWire remote implementation changed")
    return source[:begin] + REPLACEMENT + source[end:]


# The pinned backend has no add_buffer handler and may not advertise that it
# allocates buffers. PipeWire's ALLOC_BUFFERS flag means the *application*
# must allocate data in an add_buffer callback; that callback is absent.
STREAM_FLAGS = "StreamFlags::MAP_BUFFERS | StreamFlags::ALLOC_BUFFERS | StreamFlags::DRIVER"


def patch_stream_buffers(source: str) -> str:
    if source.count(STREAM_FLAGS) != 1 or "pub fn queue_frame(" not in source:
        raise ValueError("unsupported pinned upstream buffer allocation layout")
    return source.replace(STREAM_FLAGS, "StreamFlags::MAP_BUFFERS | StreamFlags::DRIVER")


def main() -> int:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("CI fixture must never modify a developer or production install")
    if len(sys.argv) != 3:
        raise SystemExit("usage: ci_portal_generic_remote.py .ci-generic-portal/src/pipewire/mod.rs .ci-generic-portal/src/pipewire/stream.rs")
    remote_path, stream_path = (Path(arg).resolve() for arg in sys.argv[1:])
    if not str(remote_path).endswith("/.ci-generic-portal/src/pipewire/mod.rs"):
        raise RuntimeError("remote source must be the disposable CI checkout")
    if stream_path != remote_path.parent / "stream.rs":
        raise RuntimeError("stream source must share the pinned CI checkout")
    if not remote_path.is_file() or not stream_path.is_file():
        raise RuntimeError("missing pinned CI source file")
    # Validate BOTH functions before writing either; abort on upstream drift.
    remote_source = patch_source(remote_path.read_text(encoding="utf-8"))
    stream_source = patch_stream_buffers(stream_path.read_text(encoding="utf-8"))
    remote_path.write_text(remote_source, encoding="utf-8")
    stream_path.write_text(stream_source, encoding="utf-8")
    print("PORTAL_CI_PATCH_OK: isolated FD and PipeWire buffer flags; not for production")
    return 0


if __name__ == "__main__":
    sys.exit(main())
